"""
task2_agent/executor.py
基于 Playwright 的浏览器操作执行器
封装 navigate / click / input / wait / screenshot 等基础动作
"""

import functools
import platform
import time
from pathlib import Path
from datetime import datetime
from rich.console import Console

console = Console(legacy_windows=False)


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
        """在项目视图下打开第一个看板。同样需要先等加载完。"""
        try:
            try:
                self._page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            self.sleep(1.0)

            # 尝试 1：href 形式
            for sel in ["main a[href*='/boards/']",
                        "a[href*='/boards/']",
                        "aside a[href*='/boards/']"]:
                try:
                    loc = self._page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible(timeout=500):
                        loc.scroll_into_view_if_needed()
                        loc.click()
                        self.sleep(2)
                        console.print(f"[green]打开看板（href: {sel}）[/green]")
                        return True
                except Exception:
                    continue

            # 尝试 2：DOM 探测主区域可点击卡片
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
                        if (/^\\+?\\s*(add|create)/i.test(txt)) continue;
                        card.scrollIntoView({block:'center'});
                        card.click();
                        return txt;
                    }
                }
                return null;
            }""")
            if picked:
                console.print(f"[green]打开看板（DOM 探测: '{picked}'）[/green]")
                self.sleep(2)
                return True

            console.print("[yellow]未找到可点击的看板[/yellow]")
            return False
        except Exception as e:
            console.print(f"[yellow]打开看板异常: {e}[/yellow]")
            return False

    # ── 登录（4ga Boards 专用）────────────────────────────────────────────────

    def login(self, username: str, password: str) -> bool:
        """完成 4ga Boards 登录流程（SPA 站点，需等待表单加载）"""
        try:
            self.navigate("/")

            # SPA 应用首次加载需较长时间，等到登录表单的输入框真正可见
            email_selector = (
                "input[type='email'], input[name='emailOrUsername'], "
                "input[name='email'], input[autocomplete='username'], "
                "input[placeholder*='email' i], input[placeholder*='用户' i]"
            )
            console.print("[dim]等待登录表单加载...[/dim]")
            if not self.wait_for_selector(email_selector, state="visible", timeout=30000):
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
                self._page.wait_for_url(
                    lambda url: "/login" not in url and "/register" not in url,
                    timeout=10000,
                )
            except Exception:
                self.sleep(3)  # 兜底等待

            url     = self.get_url()
            success = "/login" not in url and "/register" not in url
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
                secs = float(value) if value else 2.0
                if secs >= 3:
                    console.print(f"  [dim]等待 {secs:.0f} 秒...（非卡死，请耐心等待）[/dim]")
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

    def _locate_visible_css(self, scope, selector: str, timeout: int):
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

    def _visible_dialog_or_page(self):
        """返回可见弹窗的 Locator，若无弹窗则返回 page。用于消歧同名按钮。"""
        DIALOG_SEL = (
            "[role='dialog'], [role='alertdialog'], dialog, "
            "[class*='Popup' i], [class*='Modal' i], [class*='Dialog' i]"
        )
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
        - 快速层 timeout: 150-250ms（精确匹配优先）
        - 慢速层 timeout: 500-800ms（模糊匹配兜底）
        - 全函数受 deadline 控制（默认 5s），避免坏 selector 拖垮全量执行。
        - 有弹窗时优先在弹窗内查找（保留原有消歧逻辑）。
        """
        deadline = time.time() + (timeout or min(self.timeout, 5000)) / 1000
        page = self._page
        scope = self._visible_dialog_or_page()
        in_dialog = scope is not page

        looks_like_css = any(c in selector for c in "[].#>:") or selector.startswith(
            ("input", "button", "div", "span", "a[", "form")
        )

        # ── 快速层（精确匹配，150-250ms）─────────────────────────────────
        fast_strategies = []
        if looks_like_css:
            fast_strategies.append(lambda: self._locate_visible_css(scope, selector, 250))
        fast_strategies.extend([
            lambda: scope.get_by_role("button", name=selector).first.element_handle(timeout=250),
            lambda: scope.get_by_role("link", name=selector).first.element_handle(timeout=250),
            lambda: scope.get_by_role("menuitem", name=selector).first.element_handle(timeout=250),
            lambda: scope.get_by_placeholder(selector).first.element_handle(timeout=250),
        ])

        # ── 慢速层（模糊匹配，500-800ms）─────────────────────────────────
        slow_strategies = []
        # CSS selector 兜底（用更长的 timeout 再试一次）
        if looks_like_css:
            slow_strategies.append(lambda: self._locate_visible_css(scope, selector, 800))
        slow_strategies.extend([
            lambda: scope.get_by_role("button", name=selector).first.element_handle(timeout=600),
            lambda: scope.get_by_role("link", name=selector).first.element_handle(timeout=600),
            lambda: scope.get_by_role("menuitem", name=selector).first.element_handle(timeout=600),
            lambda: scope.locator("button:has-text('" + selector + "')").first.element_handle(timeout=600),
            lambda: scope.locator("a:has-text('" + selector + "')").first.element_handle(timeout=600),
            lambda: scope.get_by_text(selector, exact=False).first.element_handle(timeout=800),
        ])

        # 对话框内的兜底（submit 类按钮）
        if in_dialog:
            slow_strategies.append(
                lambda: scope.locator("button[type='submit']").first.element_handle(timeout=600)
            )

        # 非弹窗时才做全页面兜底（避免弹窗外同名按钮干扰）
        if not in_dialog:
            slow_strategies.extend([
                lambda: page.get_by_role("button", name=selector).first.element_handle(timeout=600),
                lambda: page.get_by_role("link", name=selector).first.element_handle(timeout=600),
                lambda: page.get_by_role("menuitem", name=selector).first.element_handle(timeout=600),
                lambda: page.locator("[aria-label='" + selector + "' i]").first.element_handle(timeout=600),
                lambda: page.locator("[placeholder*='" + selector + "' i]").first.element_handle(timeout=600),
                lambda: page.locator("[title='" + selector + "' i]").first.element_handle(timeout=600),
                lambda: page.get_by_text(selector, exact=False).first.element_handle(timeout=800),
            ])

        for strategy in fast_strategies + slow_strategies:
            if time.time() > deadline:
                break
            try:
                el = strategy()
                if el:
                    return el
            except Exception:
                continue

        return None
