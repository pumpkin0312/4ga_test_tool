"""
task2_agent/executor.py
基于 Playwright 的浏览器操作执行器
封装 navigate / click / input / wait / screenshot 等基础动作
"""

import time
from pathlib import Path
from datetime import datetime
from rich.console import Console

console = Console(legacy_windows=False)


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
            locale="zh-CN",
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout)
        console.print("[green]浏览器已启动[/green]")

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

    def click(self, selector: str) -> bool:
        """点击元素（支持 CSS / 文本 / aria-label 多策略查找）"""
        try:
            el = self._find(selector)
            if el:
                el.scroll_into_view_if_needed()
                el.click()
                # 等待网络稳定，忽略超时（有些操作不会触发请求）
                try:
                    self._page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                return True
        except Exception as e:
            console.print(f"[yellow]点击失败 '{selector}': {e}[/yellow]")
        return False

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
                self._page.keyboard.press("Control+A")
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

    # ── 截图 ──────────────────────────────────────────────────────────────────

    def screenshot(self, name: str = None) -> str:
        """截图保存到 screenshot_dir，返回文件路径"""
        try:
            if not name:
                name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = self.screenshot_dir / f"{name}.png"
            self._page.screenshot(path=str(path))
            return str(path)
        except Exception as e:
            console.print(f"[yellow]截图失败: {e}[/yellow]")
            return ""

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
            console.print(f"[{'green' if success else 'red'}]"
                          f"登录{'成功' if success else '失败'}（URL: {url}）[/]")
            if not success:
                self.screenshot("login_failed_state")
            return success

        except Exception as e:
            console.print(f"[red]登录异常: {e}[/red]")
            self.screenshot("login_exception")
            return False

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

    def _find(self, selector: str, timeout: int = None):
        """
        多策略元素查找。返回第一个可见的 ElementHandle，找不到返回 None。

        关键优化：当页面有打开的对话框/弹窗时，**优先**在弹窗作用域内查找，
        避免 "Add Project" 这种侧边栏链接和对话框提交按钮文字相同时的误点。
        """
        t = timeout or min(self.timeout, 4000)
        page = self._page

        # CSS selector 的常见特征：包含 [ . # > 或以 input/button/div 等开头
        looks_like_css = any(c in selector for c in "[].#>:") or selector.startswith(
            ("input", "button", "div", "span", "a[", "form")
        )

        # 检测当前是否有可见的对话框/弹窗（优先查找作用域）
        DIALOG_SEL = (
            "[role='dialog'], [role='alertdialog'], dialog, "
            "[class*='Popup' i], [class*='Modal' i], [class*='Dialog' i]"
        )
        scope_loc = None
        try:
            loc = page.locator(DIALOG_SEL)
            for i in range(min(loc.count(), 5)):
                el = loc.nth(i)
                try:
                    if el.is_visible(timeout=300):
                        scope_loc = el
                        break
                except Exception:
                    continue
        except Exception:
            scope_loc = None

        strategies = []

        # ── 第一优先：作用域内查找（有对话框时）────────────────────────────
        if scope_loc is not None:
            if looks_like_css:
                strategies.append(lambda: scope_loc.locator(selector).first.element_handle(timeout=1500))
            strategies.extend([
                lambda: scope_loc.get_by_role("button", name=selector).first.element_handle(timeout=1500),
                lambda: scope_loc.get_by_role("link",   name=selector).first.element_handle(timeout=1500),
                lambda: scope_loc.locator(f"button:has-text('{selector}')").first.element_handle(timeout=1200),
                lambda: scope_loc.get_by_text(selector, exact=False).first.element_handle(timeout=1200),
                # 模态框里"提交"类按钮的兜底
                lambda: scope_loc.locator("button[type='submit']").first.element_handle(timeout=800),
            ])

        # ── 第二优先：全页面 CSS / 文本查找 ─────────────────────────────────
        if looks_like_css:
            strategies.append(lambda: page.wait_for_selector(selector, timeout=t))

        strategies.extend([
            lambda: page.get_by_role("button", name=selector).first.element_handle(timeout=1500),
            lambda: page.get_by_role("link",   name=selector).first.element_handle(timeout=1500),
            lambda: page.get_by_role("menuitem", name=selector).first.element_handle(timeout=1200),
            lambda: page.locator(f"button:has-text('{selector}')").first.element_handle(timeout=1200),
            lambda: page.locator(f"a:has-text('{selector}')").first.element_handle(timeout=1200),
            lambda: page.locator(f"[aria-label='{selector}' i]").first.element_handle(timeout=1200),
            lambda: page.locator(f"[placeholder*='{selector}' i]").first.element_handle(timeout=1200),
            lambda: page.locator(f"[title='{selector}' i]").first.element_handle(timeout=1200),
            lambda: page.get_by_text(selector, exact=False).first.element_handle(timeout=1500),
        ])

        if not looks_like_css:
            strategies.append(lambda: page.wait_for_selector(selector, timeout=2000))

        for strategy in strategies:
            try:
                el = strategy()
                if el:
                    return el
            except Exception:
                continue

        return None
