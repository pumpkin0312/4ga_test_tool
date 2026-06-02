"""
task1_rag/dom_snapshot.py
抓取 4ga Boards 关键页面的真实可交互 DOM 元素，用于约束场景生成。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

try:
    from config import (BROWSER_LOCALE, DATA_DIR, DEMO_PASSWORD, DEMO_USERNAME,
                        TARGET_APP_LANGUAGE, TARGET_APP_URL)
except Exception:
    BROWSER_LOCALE = "en-US"
    DATA_DIR = "data"
    TARGET_APP_URL = "https://demo.4gaboards.com"
    TARGET_APP_LANGUAGE = "en"
    DEMO_USERNAME = "demo@demo.demo"
    DEMO_PASSWORD = "demo"


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / DATA_DIR / "dom_snapshots.json"

PAGES_TO_SNAPSHOT = [
    {"name": "login", "url": TARGET_APP_URL, "need_login": False},
    {"name": "dashboard", "url": TARGET_APP_URL, "need_login": True},
    {"name": "board", "url": "__first_board__", "need_login": True},
]


def _login(page: Page) -> None:
    page.goto(f"{TARGET_APP_URL.rstrip('/')}/login", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector('input[name="emailOrUsername"]', state="attached", timeout=30000)
    page.locator('input[name="emailOrUsername"]').first.fill(DEMO_USERNAME, timeout=30000, force=True)
    page.locator('input[name="password"], input[type="password"]').first.fill(DEMO_PASSWORD, timeout=30000, force=True)
    page.locator('button[type="submit"]').first.click(timeout=10000)
    page.wait_for_load_state("domcontentloaded", timeout=10000)
    page.wait_for_function(
        """() => window.location.pathname === '/'
            && document.body.innerText.trim().length > 0
            && document.querySelectorAll('button,a,input,[role="button"]').length > 0""",
        timeout=30000,
    )
    _ensure_app_language(page)


def _ensure_app_language(page: Page) -> None:
    if not TARGET_APP_LANGUAGE:
        return

    changed = page.evaluate(
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
        TARGET_APP_LANGUAGE,
    )
    if changed:
        page.reload(wait_until="domcontentloaded", timeout=30000)
        page.wait_for_function(
            """() => window.location.pathname === '/'
                && document.body.innerText.trim().length > 0
                && document.querySelectorAll('button,a,input,[role="button"]').length > 0""",
            timeout=30000,
        )


def _open_first_project(page: Page) -> None:
    candidates = [
        ".project-wrapper",
        "a[href*='/projects/']",
        "a[href*='/boards/']",
        "button:has-text('Open')",
    ]
    for selector in candidates:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.click(timeout=5000)
                page.wait_for_load_state("domcontentloaded", timeout=10000)
                page.wait_for_timeout(1500)
                return
        except PlaywrightTimeoutError:
            continue


def _open_first_board(page: Page) -> None:
    _open_first_project(page)
    page.wait_for_timeout(1500)
    if "/boards/" in page.url:
        _ensure_board_content(page)
        return

    candidates = [
        "a[href*='/boards/']",
        "button:has-text('Kanban Test Board')",
        "button:has-text('Learn 4ga Boards')",
        "a:has-text('Kanban Test Board')",
        "a:has-text('Learn 4ga Boards')",
    ]
    for selector in candidates:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.click(timeout=5000)
                page.wait_for_load_state("domcontentloaded", timeout=10000)
                page.wait_for_function(
                    """() => window.location.pathname.includes('/boards/')
                        && document.body.innerText.trim().length > 0
                        && document.querySelectorAll('button,a,input,[role="button"]').length > 0""",
                    timeout=15000,
                )
                _ensure_board_content(page)
                return
        except PlaywrightTimeoutError:
            continue


def _ensure_board_content(page: Page) -> None:
    """等看板主体异步数据加载完成，并尽量切到 Kanban 列视图。"""
    page.wait_for_function(
        """() => window.location.pathname.includes('/boards/')
            && (
                document.body.innerText.includes('Add card')
                || document.querySelectorAll(
                    '[class*="Board_main"], [class*="Board_list"], [class*="List_"], ' +
                    '[class*="Card_"], [class*="Table_"], [class*="NameCell"]'
                ).length > 0
            )""",
        timeout=20000,
    )

    # demo 账号会记住上次视图；如果停在表格视图，切到 Kanban 视图以抓到列表/卡片/Add card。
    for _ in range(3):
        try:
            is_kanban = page.evaluate("""() => document.body.innerText.includes('Add card')""")
            if is_kanban:
                break

            page.wait_for_selector('[class*="BoardActions_switchViewButton"]', timeout=5000)
            page.evaluate(
                """() => {
                    const buttons = Array.from(document.querySelectorAll('[class*="BoardActions_switchViewButton"]'));
                    const target = buttons.find((button) => !String(button.className).includes('active')) || buttons[0];
                    if (target) target.click();
                }"""
            )
            page.wait_for_function(
                """() => document.body.innerText.includes('Add card')
                    || document.querySelectorAll('[class*="List_addCardButton"], [class*="Card_"]').length > 0""",
                timeout=8000,
            )
        except Exception:
            page.wait_for_timeout(1000)

    page.wait_for_timeout(2000)


def snapshot_page(page: Page, limit: int = 100) -> dict[str, Any]:
    """提取当前页面中可交互元素的关键属性和可复用选择器线索。"""
    elements = page.evaluate(
        """(limit) => {
            const interactiveSelector = [
                'button',
                'a',
                'input',
                'textarea',
                'select',
                '[role="button"]',
                '[role="menuitem"]',
                '[role="tab"]',
                '[contenteditable="true"]'
            ].join(',');
            const boardSelector = [
                'h1',
                'h2',
                'h3',
                'div[class*="BoardActions"]',
                'div[class*="Board_"]',
                'div[class*="List_"]',
                'div[class*="Card_"]',
                'div[class*="NameCell"]',
                'div[class*="ListNameCell"]',
                'div[class*="Label_"]',
                'div[class*="TasksCell"]',
                'div[class*="Table_"]'
            ].join(',');
            const selector = `${interactiveSelector},${boardSelector}`;

            const cssPath = (el) => {
                if (el.id) return `#${CSS.escape(el.id)}`;
                const name = el.getAttribute('name');
                if (name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;
                const type = el.getAttribute('type');
                if (type) return `${el.tagName.toLowerCase()}[type="${CSS.escape(type)}"]`;
                const aria = el.getAttribute('aria-label');
                if (aria) return `[aria-label="${CSS.escape(aria)}"]`;
                const cls = Array.from(el.classList || []).find(Boolean);
                if (cls) {
                    const stablePrefix = cls.split('__')[0];
                    if (stablePrefix) return `${el.tagName.toLowerCase()}[class*="${CSS.escape(stablePrefix)}"]`;
                }
                return el.tagName.toLowerCase();
            };

            const priorityOf = (item) => {
                const text = item.text.toLowerCase();
                const cls = item.classes;
                if (/List_addCardButton/.test(cls) || text === 'add card') return 0;
                if (/List_header|List_headerName|Card_name|Card_detailsTitle|BoardActions_title/.test(cls)) return 1;
                if (/Card_|List_|BoardActions/.test(cls)) return 2;
                if (text === 'add board' || text === 'add project') return 3;
                if (/Sidebar_|Header_|ExternalLink_/.test(cls)) return 8;
                return 5;
            };

            return Array.from(document.querySelectorAll(selector))
                .filter((el) => {
                    const style = window.getComputedStyle(el);
                    const text = (el.textContent || '').trim().toLowerCase();
                    const rect = el.getBoundingClientRect();
                    const cls = Array.from(el.classList || []).join(' ');
                    const isVisible = style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && rect.width > 0
                        && rect.height > 0;
                    if (!isVisible) return false;
                    if (['create an account', 'register', 'sign up'].includes(text)) return false;
                    if (el.tagName === 'DIV') {
                        const usefulBoardDiv = /BoardActions|Board_|List_|Card_|NameCell|ListNameCell|Label_|TasksCell|Table_/.test(cls);
                        if (!usefulBoardDiv) return false;
                        if (!text && !el.getAttribute('role')) return false;
                        if (text.length > 240 && !/BoardActions_title|List_header|Card_name|NameCell|ListNameCell|Label_/.test(cls)) return false;
                    }
                    return style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && !['create an account', 'register', 'sign up'].includes(text);
                })
                .map((el, index) => {
                    const rect = el.getBoundingClientRect();
                    const item = {
                        visible: Boolean(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
                        tag: el.tagName.toLowerCase(),
                        selector: cssPath(el),
                        type: el.getAttribute('type') || '',
                        name: el.getAttribute('name') || '',
                        placeholder: el.getAttribute('placeholder') || '',
                        text: (el.textContent || '').trim().slice(0, 80),
                        aria_label: el.getAttribute('aria-label') || '',
                        classes: Array.from(el.classList).join(' '),
                        role: el.getAttribute('role') || '',
                        id: el.id || '',
                        href: el.getAttribute('href') || '',
                        _x: rect.x,
                        _y: rect.y,
                        _index: index,
                    };
                    item._priority = priorityOf(item);
                    return item;
                })
                .sort((a, b) => (
                    a._priority - b._priority
                    || a._y - b._y
                    || a._x - b._x
                    || a._index - b._index
                ))
                .slice(0, limit)
                .map(({_priority, _x, _y, _index, ...item}) => item);
        }""",
        limit,
    )

    return {
        "url": page.url,
        "title": page.title(),
        "elements": elements,
    }


def build_snapshot_cache(output_path: str | os.PathLike[str] = DEFAULT_OUTPUT_PATH) -> dict[str, Any]:
    """启动浏览器抓取关键页面 DOM，并保存到 data/dom_snapshots.json。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    snapshots: dict[str, Any] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for item in PAGES_TO_SNAPSHOT:
            context = browser.new_context(locale=BROWSER_LOCALE)
            page = context.new_page()

            if item["need_login"]:
                _login(page)

            if item["url"] == "__first_project__":
                _open_first_project(page)
            elif item["url"] == "__first_board__":
                _open_first_board(page)
            elif item["need_login"] and item["url"].rstrip("/") == TARGET_APP_URL.rstrip("/"):
                pass
            else:
                page.goto(item["url"], wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)

            snapshots[item["name"]] = snapshot_page(page)
            context.close()

        browser.close()

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)

    return snapshots


if __name__ == "__main__":
    path = DEFAULT_OUTPUT_PATH
    snapshots = build_snapshot_cache(path)
    print(f"Saved {len(snapshots)} DOM snapshots to {path}")
