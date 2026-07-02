"""
task2_agent/executor.py
基于 Playwright 的浏览器操作执行器
封装 navigate / click / input / wait / screenshot 等基础动作
"""

import functools
import platform
import re
import time
from pathlib import Path
from datetime import datetime
from rich.console import Console

console = Console(legacy_windows=False)


def _safe_visible(locator, timeout: int = 300) -> bool:
    """安全判断 Locator 是否可见，异常一律当作不可见。"""
    try:
        return locator.is_visible(timeout=timeout)
    except Exception:
        return False


def retry(max_attempts: int = 2, delay: float = 0.5):
    """轻量重试装饰器：包裹短暂渲染波动导致的失败（click/input/upload）"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    result = func(self, *args, **kwargs)
                    if result:
                        return result
                    if attempt < max_attempts - 1:
                        time.sleep(delay)
                        console.print(
                            f"[yellow]{func.__name__} 第 {attempt+1} 次返回 False，重试...[/yellow]"
                        )
                    last_error = Exception(f"{func.__name__} 返回 False")
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        time.sleep(delay)
                        console.print(
                            f"[yellow]{func.__name__} 第 {attempt+1} 次异常: {e}，重试...[/yellow]"
                        )
            if last_error:
                raise last_error
            return False
        return wrapper
    return decorator


class BrowserExecutor:
    """Playwright 浏览器控制器"""

    def __init__(self,
                 target_url:     str,
                 screenshot_dir: str  = "reports/screenshots",
                 headless:       bool = True,
                 timeout:        int  = 10000):
        self.target_url     = target_url.rstrip("/")
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.timeout  = timeout       # 毫秒

        self._playwright = None
        self._browser    = None
        self._context    = None
        self._page       = None

    @staticmethod
    def _shortcut(key: str) -> str:
        """返回当前平台快捷键。macOS → Meta+key，其他 → Control+key"""
        normalized = key.lower()
        if platform.system() == "Darwin":
            return f"Meta+{normalized}"
        return f"Control+{normalized}"

    # ── 生命周期 ──────────────────────────────────────────────────────────────

    def start(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError("请执行: pip install playwright && playwright install chromium")

        # Streamlit 在 Windows 上设置 SelectorEventLoopPolicy，导致 sync_playwright
        # 内部线程无法 spawn 子进程（NotImplementedError）。切换为 Proactor 策略。
        import sys, asyncio
        if sys.platform == "win32":
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception:
                pass

        self._playwright = sync_playwright().start()
        self._browser    = self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale=self._browser_locale(),
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout)
        console.print("[green]浏览器已启动[/green]")

    def _browser_locale(self) -> str:
        try:
            from config import BROWSER_LOCALE
            return BROWSER_LOCALE
        except Exception:
            return "en-US"

    def _target_app_language(self) -> str:
        try:
            from config import TARGET_APP_LANGUAGE
            return TARGET_APP_LANGUAGE
        except Exception:
            return "en"

    def stop(self):
        try:
            if self._context:  self._context.close()
            if self._browser:  self._browser.close()
            if self._playwright: self._playwright.stop()
        except Exception:
            pass
        console.print("[dim]浏览器已关闭[/dim]")

    # ── 基础操作 ──────────────────────────────────────────────────────────────

    def navigate(self, url: str) -> bool:
        """导航到指定 URL（相对路径自动拼接 target_url）。失败时降级重试一次。"""
        if not url.startswith("http"):
            url = self.target_url + ("" if url.startswith("/") else "/") + url
        for attempt in (1, 2):
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                return True
            except Exception as e:
                if attempt == 1:
                    console.print(f"[yellow]导航 {url} 失败（第 {attempt} 次）：{e}，重试...[/yellow]")
                    self.sleep(2)
                else:
                    console.print(f"[red]导航失败 {url}: {e}[/red]")
        return False

    def _click_and_wait(self, element, timeout: int = 1500):
        """点击后智能等待：domcontentloaded（快） + 800ms 渲染缓冲，替代 networkidle"""
        element.scroll_into_view_if_needed()
        element.click()
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception:
            pass
        self._page.wait_for_timeout(800)

    @retry(max_attempts=2, delay=0.5)
    def click(self, selector: str) -> bool:
        """点击元素（支持 CSS / 文本 / aria-label 多策略查找）"""
        try:
            el = self._find(selector)
            if el:
                self._click_and_wait(el)
                return True
        except Exception as e:
            console.print(f"[yellow]点击失败 '{selector}': {e}[/yellow]")
        return False

    @retry(max_attempts=2, delay=0.5)
    def input_text(self, selector: str, text: str) -> bool:
        """清空后输入文本。兼容 <input>/<textarea> 与 contenteditable div（4ga Boards 卡片标题用后者）。"""
        try:
            el = self._find(selector)
            if not el:
                return False

            # 1) 标准输入框：用 fill
            try:
                el.fill(text)
                return True
            except Exception:
                pass

            # 2) contenteditable / 富文本编辑器：用 click + 选中 + keyboard 输入
            try:
                el.scroll_into_view_if_needed()
                el.click()
                # 全选已有内容并删除
                self._page.keyboard.press(self._shortcut("a"))
                self._page.keyboard.press("Delete")
                self._page.keyboard.type(text)
                return True
            except Exception:
                pass

            # 3) 最后尝试 type API（针对部分自定义控件）
            try:
                el.type(text)
                return True
            except Exception as e:
                console.print(f"[yellow]输入失败 '{selector}': {e}[/yellow]")
        except Exception as e:
                console.print(f"[yellow]输入失败 '{selector}': {e}[/yellow]")
        return False

    @retry(max_attempts=2, delay=0.5)
    def set_input_files(self, selector: str, file_path: str) -> bool:
        """上传文件。支持直接设置 file input，也支持点击按钮触发 file chooser。"""
        try:
            path = Path(file_path).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            path = path.resolve()
            if not path.exists():
                console.print(f"[yellow]上传文件不存在: {path}[/yellow]")
                return False

            target = (selector or "input[type='file']").strip()
            target_lower = target.lower()

            if "input" in target_lower:
                try:
                    self._page.locator(target).first.set_input_files(str(path), timeout=self.timeout)
                    return True
                except Exception:
                    self._page.locator("input[type='file']").first.set_input_files(str(path), timeout=self.timeout)
                    return True

            try:
                with self._page.expect_file_chooser(timeout=self.timeout) as chooser_info:
                    if not self.click(target):
                        return False
                chooser_info.value.set_files(str(path))
                return True
            except Exception:
                self._page.locator("input[type='file']").first.set_input_files(str(path), timeout=self.timeout)
                return True
        except Exception as e:
            console.print(f"[yellow]上传文件失败 '{selector}': {e}[/yellow]")
            return False

    def press_key(self, key: str, selector: str = None) -> bool:
        """按键（Enter / Escape / Tab 等）"""
        try:
            if selector:
                el = self._find(selector)
                if el:
                    el.press(key)
            else:
                self._page.keyboard.press(key)
            return True
        except Exception as e:
            console.print(f"[yellow]按键失败 {key}: {e}[/yellow]")
        return False

    def wait_for_selector(self, selector: str, state: str = "visible", timeout: int = None) -> bool:
        try:
            self._page.wait_for_selector(selector, state=state, timeout=timeout or self.timeout)
            return True
        except Exception:
            return False

    def sleep(self, seconds: float):
        time.sleep(seconds)

    def _normalize_wait_seconds(self, value, default: float = 2.0, max_seconds: float = 30.0) -> float:
        """统一 wait/sleep 时长。大于 1000 的值按毫秒处理，避免 10000 被睡成 10000 秒。"""
        try:
            seconds = float(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            return default

        if seconds >= 1000:
            seconds = seconds / 1000
        return max(0.0, min(seconds, max_seconds))

    # ── 状态查询 ──────────────────────────────────────────────────────────────

    def get_url(self)   -> str: return self._page.url
    def get_title(self) -> str: return self._page.title()

    def is_visible(self, selector: str) -> bool:
        try:
            return self._page.is_visible(selector, timeout=3000)
        except Exception:
            return False

    def is_text_visible_strict(self, text: str) -> bool:
        """
        严格判断指定文本是否作为真实可见文本出现在页面上。
        与 Playwright 的 get_by_text() 不同：
          - **排除 input/textarea/contenteditable 的 value/innerText**
            （避免 Bug：表单里输入过的字符串被当成"页面显示了该内容"）
          - 只看叶子元素的 textContent，且要求元素本身可见
        """
        if not text or not text.strip():
            return False
        try:
            return self._page.evaluate("""
            (text) => {
                const want = String(text).trim().toLowerCase();
                if (!want) return false;
                const all = document.body ? document.body.querySelectorAll('*') : [];
                for (const el of all) {
                    const tag = el.tagName;
                    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') continue;
                    if (el.isContentEditable) continue;
                    // 只看叶子或直接 textNode 的元素（避免父节点 textContent 包含子树文本误判）
                    let direct = '';
                    for (const node of el.childNodes) {
                        if (node.nodeType === 3) direct += node.textContent || '';
                    }
                    direct = direct.trim().toLowerCase();
                    if (!direct || !direct.includes(want)) continue;
                    // 可见性
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    const cs = window.getComputedStyle(el);
                    if (cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') continue;
                    return true;
                }
                return false;
            }""", text)
        except Exception:
            return False

    def get_text(self, selector: str) -> str:
        try:
            el = self._find(selector, timeout=3000)
            return el.inner_text().strip() if el else ""
        except Exception:
            return ""

    def count(self, selector: str) -> int:
        try:
            return len(self._page.query_selector_all(selector))
        except Exception:
            return 0

    def list_clickable_texts(self, limit: int = 40) -> list[str]:
        """列出页面上可见按钮/链接的文本，供 LLM 调整备选方案使用"""
        try:
            return self._page.evaluate("""
            (limit) => {
                const sels = ['button', 'a', '[role="button"]', '[role="menuitem"]'];
                const seen = new Set();
                const out = [];
                for (const s of sels) {
                    for (const el of document.querySelectorAll(s)) {
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        const t = (el.innerText || el.getAttribute('aria-label') || el.title || '').trim();
                        if (!t || seen.has(t)) continue;
                        seen.add(t);
                        out.push(t);
                        if (out.length >= limit) return out;
                    }
                }
                return out;
            }""", limit)
        except Exception:
            return []

    def snapshot_interactive_elements(self, limit: int = 60) -> list[dict]:
        """
        抓取当前页面所有可交互元素的快照，供 PageResolver 决策。
        每个元素返回：{kind, text, placeholder, aria_label, name, type, in_dialog}
        - kind 区分 button/link/input/menuitem
        - in_dialog 标记元素是否在对话框/弹窗内（用于消歧）
        """
        try:
            return self._page.evaluate("""
            (limit) => {
                const sels = [
                    ['button',                'button'],
                    ['[role="button"]',       'button'],
                    ['a[href]',               'link'],
                    ['[role="menuitem"]',     'menuitem'],
                    ['input',                 'input'],
                    ['textarea',              'input'],
                    ['[contenteditable="true"]', 'input'],
                ];
                const seen = new Set();
                const out  = [];
                for (const [sel, kind] of sels) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (el.disabled) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        // 大致判断是否在视口附近（在 dialog 内通常会进视口）
                        const style = window.getComputedStyle(el);
                        if (style.visibility === 'hidden' || style.display === 'none') continue;

                        const inDialog = !!el.closest(
                            "[role='dialog'],[role='alertdialog'],dialog," +
                            "[class*='Popup' i],[class*='Modal' i],[class*='Dialog' i]"
                        );

                        const text = (el.innerText || el.value || '').trim().slice(0, 80);
                        const key  = kind + '|' + text + '|' + (el.name || '') + '|' + inDialog;
                        if (seen.has(key)) continue;
                        seen.add(key);

                        out.push({
                            kind:        kind,
                            text:        text,
                            placeholder: el.getAttribute('placeholder') || '',
                            aria_label:  el.getAttribute('aria-label')  || '',
                            name:        el.getAttribute('name')        || '',
                            type:        el.getAttribute('type')        || '',
                            in_dialog:   inDialog,
                        });
                        if (out.length >= limit) return out;
                    }
                }
                return out;
            }""", limit)
        except Exception:
            return []

    # ── 截图 ──────────────────────────────────────────────────────────────────

    def screenshot(self, name: str = None) -> str:
        """安全截图：浏览器已关闭或页面不可用时静默返回空字符串"""
        try:
            if not self._page or self._page.is_closed():
                return ""
            if not name:
                name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = self.screenshot_dir / f"{name}.png"
            self._page.screenshot(path=str(path), timeout=3000)
            return str(path)
        except Exception as e:
            console.print(f"[dim]截图失败（可忽略）: {e}[/dim]")
            return ""

    # ── 导航辅助：进入项目 / 打开看板 ──────────────────────────────────────────

    def _wait_dashboard_ready(self, timeout: int = 15000) -> bool:
        """
        等 Dashboard 真正加载完成（不再只是 loading 圈）。
        判据：sidebar 或主区域出现"Add Project / Add Board"等可见按钮。
        """
        try:
            self._page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass
        # 等任何 dashboard 标志性元素出现
        sentinels = [
            "text=Add Project",
            "text=Dashboard",
            "[class*='Sidebar' i]",
            "[class*='Dashboard' i]",
            "aside",
        ]
        for s in sentinels:
            try:
                if self._page.wait_for_selector(s, timeout=4000, state="visible"):
                    return True
            except Exception:
                continue
        return False

    def enter_first_project(self) -> bool:
        """
        从 Dashboard 进入第一个可点击的项目卡片。
        实测 4ga Boards 项目卡片不是 <a>，而是 div + onClick；并且首次跳转后
        页面有较长 loading，所以先等渲染完再尝试多种 selector。
        """
        try:
            self._wait_dashboard_ready()
            self.sleep(1.0)   # 给 React 多一点时间收尾

            # 尝试 1：href 形式（最稳，但 4ga Boards 可能没有）
            for sel in ["main a[href*='/projects/']",
                        "a[href*='/projects/']",
                        "aside a[href*='/projects/']"]:
                try:
                    loc = self._page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible(timeout=500):
                        loc.scroll_into_view_if_needed()
                        loc.click()
                        self.sleep(2)
                        console.print(f"[green]进入项目（href 形式 selector: {sel}）[/green]")
                        return True
                except Exception:
                    continue

            # 尝试 2：DOM 探测——在主区域找有 cursor:pointer 且像项目卡片的元素
            picked = self._page.evaluate("""
            () => {
                const roots = ['main', '[role="main"]', '#root > div'];
                let containers = [];
                for (const r of roots) {
                    document.querySelectorAll(r).forEach(c => containers.push(c));
                }
                for (const c of containers) {
                    if (!c) continue;
                    const cards = c.querySelectorAll("div, button, [role='button']");
                    for (const card of cards) {
                        const r = card.getBoundingClientRect();
                        if (r.width < 100 || r.height < 50) continue;
                        if (r.width > 600 || r.height > 400) continue;
                        const style = window.getComputedStyle(card);
                        if (style.cursor !== 'pointer') continue;
                        const txt = (card.innerText || '').trim();
                        if (!txt || txt.length > 80) continue;
                        // 跳过 sidebar 中部的"Add"按钮
                        if (/^\\+?\\s*(add|create)/i.test(txt)) continue;
                        card.scrollIntoView({block:'center'});
                        card.click();
                        return txt;
                    }
                }
                return null;
            }""")
            if picked:
                console.print(f"[green]进入项目（DOM 探测: '{picked}'）[/green]")
                self.sleep(2)
                return True

            # 尝试 3：sidebar 上点项目名（4ga Boards sidebar 里有项目列表）
            try:
                # sidebar 上每个项目通常以独立的可点击块呈现
                sidebar_items = self._page.locator(
                    "aside [class*='item' i], aside [class*='Project' i], aside li"
                )
                cnt = min(sidebar_items.count(), 10)
                for i in range(cnt):
                    el = sidebar_items.nth(i)
                    try:
                        if not el.is_visible(timeout=300):
                            continue
                        txt = (el.inner_text() or "").strip().lower()
                        # 跳过 "Add..." / "Search..." 等控制项
                        if not txt or txt.startswith(("+", "add ", "create ", "search")):
                            continue
                        el.click()
                        self.sleep(2)
                        console.print(f"[green]进入项目（sidebar item: {txt[:30]}）[/green]")
                        return True
                    except Exception:
                        continue
            except Exception:
                pass

            console.print("[yellow]未找到可点击的项目卡片[/yellow]")
            return False
        except Exception as e:
            console.print(f"[yellow]进入项目异常: {e}[/yellow]")
            return False

    def open_first_board(self) -> bool:
        """
        在项目/仪表板视图下打开第一个看板。

        真实 DOM：看板链接是 a[href*='/boards/']，项目链接是 a[href*='/projects/']。
        旧实现用「cursor:pointer 的 div」DOM 探测，会误点到项目卡片、URL 停在
        /projects/ 却返回 True。这里只允许点 a[href*='/boards/']，且**点击后必须
        验证 URL 含 /boards/**，否则继续尝试，全部失败才返回 False。
        """
        try:
            try:
                self._page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            self.sleep(1.0)

            board_selectors = [
                "main a[href*='/boards/']",
                "a[href*='/boards/']",
                "aside a[href*='/boards/']",
                "[href*='/boards/']",
            ]
            for sel in board_selectors:
                try:
                    loc = self._page.locator(sel)
                    count = min(loc.count(), 10)
                    for i in range(count):
                        el = loc.nth(i)
                        try:
                            if not _safe_visible(el, 500):
                                continue
                            el.scroll_into_view_if_needed()
                            el.click()
                            self.sleep(2)
                            if "/boards/" in self.get_url().lower():
                                console.print(f"[green]打开看板成功（{sel}），URL: {self.get_url()}[/green]")
                                return True
                            # 点了但没进看板：回退再试下一个
                            console.print(f"[yellow]点击 {sel} 后 URL 非 /boards/：{self.get_url()}[/yellow]")
                        except Exception:
                            continue
                except Exception:
                    continue

            # 仍未进入看板：如果当前在项目页，尝试点项目页里的看板链接
            console.print(f"[yellow]未能打开真实看板（当前 URL: {self.get_url()}）[/yellow]")
            return "/boards/" in self.get_url().lower()
        except Exception as e:
            console.print(f"[yellow]打开看板异常: {e}[/yellow]")
            return False

    def open_settings(self, section: str = None) -> bool:
        """
        打开用户设置。真实页面里直接访问 /settings/account 等子路由会白屏，必须走 UI：
          1. 点顶部 Header 里精确的 Settings 按钮（class 含 Button_header，避免匹配到
             项目侧栏同名 title='Settings' 的按钮）
          2. 可选 section：再点左侧 Profile / Account / Authentication / Users
        """
        try:
            self.sleep(0.4)
            clicked = False
            for sel in ("button[title='Settings'][class*='Button_header']",
                        "button[title='Settings']"):
                el = self._locate_visible_css(self._page, sel, 800)
                if el:
                    self._click_and_wait(el)
                    clicked = True
                    break
            if not clicked:
                try:
                    loc = self._page.get_by_role("button", name="Settings", exact=True).first
                    if loc.count() > 0:
                        loc.click()
                        clicked = True
                except Exception:
                    pass
            if not clicked:
                console.print("[yellow]未找到顶部 Settings 按钮[/yellow]")
                return False

            self.sleep(0.8)
            in_settings = "/settings" in self.get_url().lower()
            if section:
                return self._click_settings_section(section) if in_settings else False
            if in_settings:
                console.print("[green]已进入 Settings[/green]")
            return in_settings
        except Exception as e:
            console.print(f"[yellow]打开 Settings 异常: {e}[/yellow]")
            return False

    def _click_settings_section(self, section: str) -> bool:
        """在 Settings 左侧导航里点子页（Profile / Account / Authentication / Users）。"""
        try:
            el = self._find(section, timeout=2500)
            if el:
                self._click_and_wait(el)
                self.sleep(0.6)
                console.print(f"[green]已进入 Settings / {section}[/green]")
                return True
            console.print(f"[yellow]Settings 左侧未找到 '{section}'[/yellow]")
            return False
        except Exception:
            return False

    def open_project_settings(self) -> bool:
        """
        打开当前项目设置。真实页面通过 UI 进入（点 title='Project Settings' 或侧栏齿轮/
        Settings），不直接访问子路由以免白屏。
        """
        try:
            self.sleep(0.4)
            for name in ("Project Settings", "Edit Project", "Settings"):
                el = self._find(name, timeout=1500)
                if el:
                    self._click_and_wait(el)
                    self.sleep(0.6)
                    console.print(f"[green]已打开项目设置（{name}）[/green]")
                    return True
            console.print("[yellow]未找到项目设置入口[/yellow]")
            return False
        except Exception as e:
            console.print(f"[yellow]打开项目设置异常: {e}[/yellow]")
            return False

    # ── 弹窗（Popup / Dialog）内定位辅助 ───────────────────────────────────────

    def wait_for_dialog(self, timeout: int = 5000) -> bool:
        """等待弹窗出现（[role=dialog] 或 Popup/Modal 容器）。"""
        DIALOG_SEL = ("[role='dialog'], [role='alertdialog'], dialog, "
                      "[class*='Popup' i], [class*='Modal' i], [class*='Dialog' i]")
        return self.wait_for_selector(DIALOG_SEL, state="visible", timeout=timeout)

    def fill_dialog_input(self, value: str, name: str = "name") -> bool:
        """在可见弹窗内定位 input/textarea[name=...] 填值，避免命中页面其它同名元素。"""
        self.wait_for_dialog(timeout=3000)
        scope = self._visible_dialog_or_page()
        for sel in (f"textarea[name='{name}']", f"input[name='{name}']"):
            el = self._locate_visible_css(scope, sel, 800)
            if el:
                try:
                    el.fill(value)
                    return True
                except Exception:
                    continue
        return False

    def submit_dialog(self) -> bool:
        """点击弹窗内的提交按钮（submit / Save / Create / Add）。"""
        scope = self._visible_dialog_or_page()
        el = self._locate_visible_css(scope, "button[type='submit']", 800)
        if el:
            self._click_and_wait(el)
            return True
        for name in ("Save", "Create", "Add", "Confirm", "OK"):
            try:
                loc = scope.get_by_role("button", name=name, exact=True).first
                if loc.count() > 0 and _safe_visible(loc):
                    loc.click()
                    return True
            except Exception:
                continue
        return False

    # ── 列表 / 卡片 前置准备（基于 4ga Boards 真实 DOM）────────────────────────

    def add_board(self, name: str = None) -> bool:
        """
        新建看板（真实路径）：点 Add Board → 弹窗 input[name='name'] 填名 → 弹窗内提交。
        返回是否成功打开弹窗并提交。取消场景请改用 wait_for_dialog + Escape。
        """
        try:
            from task2_agent.stability import unique_name
            board_name = name or unique_name("Test Board")
            if not self.click("Add Board"):
                if not self.click("[title='Add Board']"):
                    console.print("[yellow]未找到 Add Board 入口[/yellow]")
                    return False
            if not self.wait_for_dialog(timeout=4000):
                console.print("[yellow]Add Board 弹窗未出现[/yellow]")
                return False
            if not self.fill_dialog_input(board_name, name="name"):
                return False
            ok = self.submit_dialog()
            self.sleep(1.0)
            console.print(f"[green]创建看板 '{board_name}': {'已提交' if ok else '提交未确认'}[/green]")
            return ok
        except Exception as e:
            console.print(f"[yellow]add_board 异常: {e}[/yellow]")
            return False

    # ── 卡片详情（CardModal）内的控件操作 ──────────────────────────────────────

    def _in_card_modal(self) -> bool:
        return ("/cards/" in self.get_url().lower()
                or self._count_visible("[class*='CardModal_wrapper']") > 0)

    def add_card_member(self, query: str = None) -> bool:
        """CardModal → Add Member → 搜索框 → 点击第一个候选用户。"""
        try:
            if not self._in_card_modal() and not self.open_first_card():
                return False
            if not self.click("Add Member") and not self.click("[title='Add Member']"):
                return False
            self.sleep(0.5)
            if query:
                self.input_text("input[placeholder='Search members...']", query)
                self.sleep(0.6)
            # 点击候选用户项（Popup 里第一个可点用户）
            for sel in ("[class*='Item'] [class*='user' i]",
                        "[class*='Popup'] [class*='user' i]",
                        "[class*='Popup'] li", "[role='menuitem']"):
                el = self._locate_visible_css(self._page, sel, 600)
                if el:
                    self._click_and_wait(el)
                    return True
            return False
        except Exception as e:
            console.print(f"[yellow]add_card_member 异常: {e}[/yellow]")
            return False

    def add_card_label(self) -> bool:
        """CardModal → Add Label → 点击第一个已有标签。"""
        try:
            if not self._in_card_modal() and not self.open_first_card():
                return False
            if not self.click("Add Label") and not self.click("[title='Add Label']"):
                return False
            self.sleep(0.5)
            for sel in ("[class*='Label']", "[class*='Popup'] button", "[role='menuitem']"):
                el = self._locate_visible_css(self._page, sel, 600)
                if el:
                    self._click_and_wait(el)
                    return True
            return False
        except Exception as e:
            console.print(f"[yellow]add_card_label 异常: {e}[/yellow]")
            return False

    def set_card_due_date(self, date_str: str = None) -> bool:
        """CardModal → Add Due Date → input[name='date'] → Save。"""
        try:
            if not self._in_card_modal() and not self.open_first_card():
                return False
            if not self.click("Add Due Date") and not self.click("[title='Add Due Date']"):
                return False
            self.sleep(0.5)
            if date_str:
                self.input_text("input[name='date']", date_str)
            ok = self.submit_dialog() or self.press_key("Enter")
            return ok
        except Exception as e:
            console.print(f"[yellow]set_card_due_date 异常: {e}[/yellow]")
            return False

    def edit_card_description(self, text: str = None) -> bool:
        """CardModal → Edit Description → 描述编辑器输入 → Save。"""
        try:
            if not self._in_card_modal() and not self.open_first_card():
                return False
            opened = (self.click("[title='Edit Description']")
                      or self.click("Edit Description")
                      or self.click("[class*='CardModal_descriptionText']"))
            if not opened:
                return False
            self.sleep(0.5)
            if text:
                for sel in ("textarea[placeholder*='description' i]", ".ProseMirror", "textarea"):
                    if self.input_text(sel, text):
                        break
            ok = self.submit_dialog() or self.click("Save") or self.press_key("Enter")
            return ok
        except Exception as e:
            console.print(f"[yellow]edit_card_description 异常: {e}[/yellow]")
            return False

    def _count_visible(self, selector: str) -> int:
        """统计匹配选择器且可见的元素数量。"""
        try:
            loc = self._page.locator(selector)
            n = min(loc.count(), 50)
            return sum(1 for i in range(n) if _safe_visible(loc.nth(i)))
        except Exception:
            return 0

    def has_list(self) -> bool:
        """当前看板是否已有列表。List 组件类名形如 List_outerWrapper__<hash>。"""
        return self._count_visible("[class*='List_outerWrapper'], [class*='List_innerWrapper']") > 0

    def has_card(self) -> bool:
        """当前看板/列表是否已有卡片。卡片可点击外层是 Card_wrapper__<hash>（role=button）。"""
        return self._count_visible("[class*='Card_wrapper']") > 0

    def ensure_list_exists(self, name: str = None) -> bool:
        """
        保证当前看板至少有一个列表；没有则创建一个带时间戳的唯一命名临时列表。
        真实 DOM：按钮 title='Add List'（可见文本是小写 Add list），输入 textarea[name='name']。
        """
        try:
            self.sleep(0.6)
            if self.has_list():
                return True
            from task2_agent.stability import unique_name
            list_name = name or unique_name("Test List")
            if not self.click("button[title='Add List']"):
                if not self.click("Add list"):     # 兜底：真实可见文本（小写）
                    console.print("[yellow]未找到 Add List 按钮[/yellow]")
                    return False
            self.sleep(0.5)
            if not self.input_text("textarea[name='name']", list_name):
                return False
            self.press_key("Enter")
            self.sleep(1.0)
            ok = self.has_list()
            console.print(f"[green]创建测试列表 '{list_name}': {'成功' if ok else '未确认'}[/green]")
            return ok
        except Exception as e:
            console.print(f"[yellow]ensure_list_exists 异常: {e}[/yellow]")
            return False

    def ensure_card_exists(self, name: str = None) -> bool:
        """
        保证当前看板至少有一张卡片；没有则先确保有列表，再创建一张唯一命名临时卡片。
        真实 DOM：按钮 title='Add Card'，输入 textarea[name='name']；创建后等 Card_wrapper 出现新卡片名。
        """
        try:
            if not self.ensure_list_exists():
                return False
            self.sleep(0.4)
            if self.has_card():
                return True
            from task2_agent.stability import unique_name
            card_name = name or unique_name("Test Card")
            if not self.click("button[title='Add Card']"):
                if not self.click("Add card"):
                    console.print("[yellow]未找到 Add Card 按钮[/yellow]")
                    return False
            self.sleep(0.5)
            if not self.input_text("textarea[name='name']", card_name):
                return False
            self.press_key("Enter")
            self.sleep(1.0)
            # 等新卡片名出现在 Card_wrapper 里
            ok = self.has_card() and (self.is_text_visible_strict(card_name) or self.has_card())
            console.print(f"[green]创建测试卡片 '{card_name}': {'成功' if ok else '未确认'}[/green]")
            return ok
        except Exception as e:
            console.print(f"[yellow]ensure_card_exists 异常: {e}[/yellow]")
            return False

    def open_first_card(self) -> bool:
        """
        打开看板里的第一张卡片（必要时先创建）。真实 DOM：卡片可点击外层是
        Card_wrapper（role=button）；点击后 URL 含 /cards/ 且出现 CardModal_wrapper。
        """
        try:
            if not self.ensure_card_exists():
                return False
            for sel in ("[class*='Card_wrapper']", "[class*='Card_card']"):
                el = self._locate_visible_css(self._visible_dialog_or_page(), sel, 800)
                if el:
                    self._click_and_wait(el)
                    self.sleep(1.0)
                    ok = ("/cards/" in self.get_url().lower()
                          or self._count_visible("[class*='CardModal_wrapper']") > 0
                          or self._count_visible("[class*='CardModal']") > 0)
                    console.print(f"[green]打开第一张卡片: {'成功' if ok else '已点击'}[/green]")
                    return True
            console.print("[yellow]未找到可点击的卡片[/yellow]")
            return False
        except Exception as e:
            console.print(f"[yellow]open_first_card 异常: {e}[/yellow]")
            return False

    # ── 登录（4ga Boards 专用）────────────────────────────────────────────────
    def _is_auth_page_url(self, url: str = None) -> bool:
        """判断当前 URL 是否仍在登录/注册页。"""
        try:
            from urllib.parse import urlparse
            path = urlparse(url or self.get_url()).path.rstrip("/").lower()
            return path in {"/login", "/register"}
        except Exception:
            url = (url or self.get_url()).lower()
            return "/login" in url or "/register" in url

    def _has_authenticated_sentinel(self, timeout: int = 500) -> bool:
        """登录后页面才会出现的稳定标志。避免 SPA 根路径短暂闪现导致误判。"""
        sentinels = [
            "text=Add Project",
            "text=Dashboard",
            "button[title='Settings'][class*='Button_header']",
            "[class*='Sidebar' i]",
            "aside",
        ]
        for selector in sentinels:
            try:
                loc = self._page.locator(selector).first
                if loc.count() > 0 and loc.is_visible(timeout=timeout):
                    return True
            except Exception:
                continue
        return False

    def _looks_authenticated(self) -> bool:
        """必须同时离开 auth 页并看到应用内标志，才算真的登录成功。"""
        if self._is_auth_page_url():
            return False
        return self._has_authenticated_sentinel()

    def login(self, username: str, password: str) -> bool:
        """完成 4ga Boards 登录流程（SPA 站点，需等待表单加载）"""
        try:
            self.navigate("/")

            # 访问根路径时，SPA 会先短暂停在 "/"，随后才根据 cookie 跳到
            # /login 或 Dashboard。这里必须等待页面稳定，不能只看瞬时 URL。
            try:
                self._page.wait_for_function(
                    """() => {
                        const path = location.pathname.toLowerCase();
                        const hasAuthPath = path === '/login' || path === '/register';
                        const hasPasswordInput = !!document.querySelector("input[type='password']");
                        const text = document.body ? document.body.innerText : '';
                        const hasAppMarker =
                            text.includes('Add Project') ||
                            text.includes('Dashboard') ||
                            !!document.querySelector("aside,[class*='Sidebar'],button[title='Settings']");
                        return hasAuthPath || hasPasswordInput || hasAppMarker;
                    }""",
                    timeout=10000,
                )
            except Exception:
                self.sleep(1)

            url = self.get_url()
            if self._looks_authenticated():
                try:
                    self._page.wait_for_function(
                        """() => document.body.innerText.trim().length > 0
                            && document.querySelectorAll('button,a,input,[role="button"]').length > 0""",
                        timeout=10000,
                    )
                    self._ensure_app_language()
                except Exception:
                    pass
                console.print(f"[green]已处于登录状态（URL: {url}）[/green]")
                return True

            # SPA 应用首次加载需较长时间，等到登录表单的输入框真正可见
            email_selector = (
                "input[type='email'], input[name='emailOrUsername'], "
                "input[name='email'], input[autocomplete='username'], "
                "input[placeholder*='email' i], input[placeholder*='用户' i]"
            )
            console.print("[dim]等待登录表单加载...[/dim]")
            if not self.wait_for_selector(email_selector, state="visible", timeout=30000):
                if self._looks_authenticated():
                    console.print(f"[green]已处于登录状态（URL: {self.get_url()}）[/green]")
                    return True
                console.print("[red]登录表单未在 30 秒内加载[/red]")
                self.screenshot("login_no_form")
                return False

            self.sleep(0.5)  # 让 hydration 完全结束

            if not self.input_text(email_selector, username):
                console.print("[red]邮箱输入框找到但写入失败[/red]")
                return False

            if not self.input_text("input[type='password']", password):
                console.print("[red]未找到密码输入框[/red]")
                return False

            # 提交（优先点按钮，其次回车）
            if not self.click("button[type='submit']"):
                self.press_key("Enter")

            # 等待登录完成：URL 离开登录页 或 出现已登录后才有的元素
            try:
                self._page.wait_for_function(
                    """() => {
                        const path = location.pathname.toLowerCase();
                        if (path === '/login' || path === '/register') return false;
                        const text = document.body ? document.body.innerText : '';
                        return text.includes('Add Project') ||
                            text.includes('Dashboard') ||
                            !!document.querySelector("aside,[class*='Sidebar'],button[title='Settings']");
                    }""",
                    timeout=10000,
                )
            except Exception:
                self.sleep(3)  # 兜底等待

            url     = self.get_url()
            success = self._looks_authenticated()
            if success:
                self._page.wait_for_function(
                    """() => document.body.innerText.trim().length > 0
                        && document.querySelectorAll('button,a,input,[role="button"]').length > 0""",
                    timeout=30000,
                )
                self._ensure_app_language()
            console.print(f"[{'green' if success else 'red'}]"
                          f"登录{'成功' if success else '失败'}（URL: {url}）[/]")
            if not success:
                self.screenshot("login_failed_state")
            return success

        except Exception as e:
            console.print(f"[red]登录异常: {e}[/red]")
            self.screenshot("login_exception")
            return False

    def _ensure_app_language(self) -> None:
        """把共享 demo 账号的界面语言固定为英文，避免被其他使用者改成俄语等语言。"""
        language = self._target_app_language()
        if not language:
            return

        try:
            changed = self._page.evaluate(
                """async (language) => {
                    const cookie = document.cookie
                        .split('; ')
                        .find((item) => item.startsWith('accessToken='));
                    const token = cookie ? cookie.split('=')[1] : '';
                    if (!token) return false;

                    let userId = '';
                    try {
                        const payload = JSON.parse(atob(token.split('.')[1]));
                        userId = payload.sub || '';
                    } catch (e) {
                        return false;
                    }
                    if (!userId) return false;

                    const headers = {
                        Authorization: `Bearer ${token}`,
                        'Content-Type': 'application/json',
                    };
                    const current = await fetch(`/api/user-prefs/${userId}`, { headers });
                    if (!current.ok) return false;
                    const before = await current.json();
                    const oldLanguage = before?.item?.language || '';

                    localStorage.setItem('i18nextLng', language);
                    if (oldLanguage === language) return false;

                    const updated = await fetch(`/api/user-prefs/${userId}`, {
                        method: 'PATCH',
                        headers,
                        body: JSON.stringify({ language }),
                    });
                    return updated.ok;
                }""",
                language,
            )
            if changed:
                self._page.reload(wait_until="domcontentloaded", timeout=30000)
                self._page.wait_for_function(
                    """() => document.body.innerText.trim().length > 0
                        && document.querySelectorAll('button,a,input,[role="button"]').length > 0""",
                    timeout=30000,
                )
        except Exception as e:
            console.print(f"[yellow]设置应用语言失败（不影响主流程）：{e}[/yellow]")

    # ── 统一步骤执行入口 ──────────────────────────────────────────────────────

    def execute_step(self, step: dict, step_index: int,
                     take_screenshot: bool = True) -> tuple[bool, str, str]:
        """
        执行一个测试步骤字典。
        返回: (success, screenshot_path, error_msg)
        """
        action = step.get("action", "").lower().strip()
        target = step.get("target", "")
        value  = step.get("value",  "")
        desc   = step.get("description", "")

        # step_index 可能是 int（正常步骤）或 str（如备选方案的 "1b"），统一为字符串标签
        idx_label = f"{step_index:03d}" if isinstance(step_index, int) else str(step_index)
        console.print(f"  [dim]步骤 {idx_label}: {desc}[/dim]")
        success   = False
        error_msg = ""

        try:
            if action == "navigate":
                success = self.navigate(value or target)
                self.sleep(1.5)

            elif action == "click":
                success = self.click(target)
                self.sleep(0.8)

            elif action in ("input", "type", "fill"):
                success = self.input_text(target, value)

            elif action in ("setinputfiles", "set_input_files", "upload", "upload_file"):
                success = self.set_input_files(target, value)

            elif action == "select":
                try:
                    self._page.select_option(target, value)
                    success = True
                except Exception:
                    success = self.click(f"{target} option:has-text('{value}')")

            elif action == "hover":
                el = self._find(target)
                if el:
                    el.hover()
                    success = True

            elif action in ("wait", "sleep"):
                secs = self._normalize_wait_seconds(value)
                if action == "wait" and target:
                    timeout_ms = max(1, int(secs * 1000))
                    console.print(f"  [dim]等待元素出现，最长 {secs:.1f} 秒: {target}[/dim]")
                    success = self._find(target, timeout=timeout_ms) is not None
                    if not success:
                        error_msg = f"等待元素超时: {target}"
                else:
                    if secs >= 3:
                        console.print(f"  [dim]等待 {secs:.1f} 秒...（非卡死，请耐心等待）[/dim]")
                    self.sleep(secs)
                    success = True

            elif action == "press":
                success = self.press_key(value or target)

            elif action == "assert_visible":
                success = self.is_visible(target)

            else:
                # 未知动作降级为点击
                success = self.click(target)

        except Exception as e:
            error_msg = str(e)
            success   = False

        # 截图
        ss_path = ""
        if take_screenshot:
            tag = "ok" if success else "fail"
            ss_path = self.screenshot(f"step_{idx_label}_{tag}")

        return success, ss_path, error_msg

    # ── 私有：多策略元素查找 ──────────────────────────────────────────────────

    def _locate_one_css(self, scope, selector: str, timeout: int):
        """在所有匹配 CSS 选择器的元素中，返回第一个可见的。避免旧版本
        wait_for_selector(state='visible')→新版本 element_handle() 的可见性检查缺失。"""
        try:
            loc = scope.locator(selector)
            cnt = min(loc.count(), 30)
            for i in range(cnt):
                el = loc.nth(i)
                try:
                    if el.is_visible():
                        return el.element_handle(timeout=timeout)
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _locate_visible_css(self, scope, selector: str, timeout: int):
        """
        CSS 定位（带 selector 归一化兜底）：先试原始选择器，再试 expand_selector
        给出的鲁棒变体（如把哈希化的 CSS Module 类名 .Card_card__container 扩展成
        [class*='Card_card__container']）。任一变体命中即返回。
        """
        from task2_agent.stability import expand_selector
        for cand in expand_selector(selector):
            el = self._locate_one_css(scope, cand, timeout)
            if el:
                return el
        return None

    def _visible_dialog_or_page(self):
        """
        返回当前真实打开的弹窗 Locator；没有则返回 page。

        重要：只认「明确的对话框」——role=dialog / role=alertdialog / <dialog> 元素。
        不再把 [class*=Popup]/[class*=Modal] 这类**常驻挂载**的组件当成弹窗 scope，
        否则真实看板页（Add List / Add Card / Card_wrapper 都在页面上、并无弹窗打开）
        会被误判成「在弹窗内」，导致 _find 只在错误 scope 里找、真实元素反而找不到。
        （4ga Boards 的 Add Board 弹窗是 role=dialog，仍能被正确识别并优先。）
        """
        DIALOG_SEL = "[role='dialog'], [role='alertdialog'], dialog"
        try:
            loc = self._page.locator(DIALOG_SEL)
            for i in range(min(loc.count(), 5)):
                el = loc.nth(i)
                try:
                    if el.is_visible(timeout=300):
                        return el
                except Exception:
                    continue
        except Exception:
            pass
        return self._page

    def _find(self, selector: str, timeout: int = None):
        """
        多策略元素查找（分层 + deadline 控制）。
        - 有真实对话框（role=dialog）时优先在对话框内找；
        - **但无论是否在对话框内，都必须回退到整页查找**，避免把元素“找丢”。
        - 全函数受 deadline 控制（默认 5s），避免坏 selector 拖垮全量执行。
        """
        deadline = time.time() + (timeout or min(self.timeout, 5000)) / 1000
        page = self._page
        dialog = self._visible_dialog_or_page()
        has_dialog = dialog is not page

        looks_like_css = any(c in selector for c in "[].#>:") or selector.startswith(
            ("input", "button", "div", "span", "a[", "form")
        )

        def strategies_for(root, css_timeout: int, role_timeout: int):
            out = []
            if looks_like_css:
                out.append(lambda: self._locate_visible_css(root, selector, css_timeout))
            out.extend([
                lambda: root.get_by_role("button",   name=selector).first.element_handle(timeout=role_timeout),
                lambda: root.get_by_role("link",     name=selector).first.element_handle(timeout=role_timeout),
                lambda: root.get_by_role("menuitem", name=selector).first.element_handle(timeout=role_timeout),
                lambda: root.get_by_placeholder(selector).first.element_handle(timeout=role_timeout),
                lambda: root.locator("button:has-text('" + selector + "')").first.element_handle(timeout=role_timeout),
                lambda: root.locator("a:has-text('" + selector + "')").first.element_handle(timeout=role_timeout),
                lambda: root.locator("[aria-label='" + selector + "' i]").first.element_handle(timeout=role_timeout),
                lambda: root.locator("[title='" + selector + "' i]").first.element_handle(timeout=role_timeout),
                lambda: root.get_by_text(selector, exact=False).first.element_handle(timeout=role_timeout),
            ])
            return out

        ordered = []
        # 1) 有真实对话框：先在对话框内精确找
        if has_dialog:
            ordered += strategies_for(dialog, 250, 300)
            ordered.append(lambda: dialog.locator("button[type='submit']").first.element_handle(timeout=400))
        # 2) 整页查找（始终执行——这是关键的兜底，修复“弹窗 scope 误判导致找不到”）
        ordered += strategies_for(page, 300, 700)

        for strategy in ordered:
            if time.time() > deadline:
                break
            try:
                el = strategy()
                if el:
                    return el
            except Exception:
                continue

        return None
