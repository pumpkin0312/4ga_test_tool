"""
task1_rag/crawler.py
爬取 docs.4gaboards.com 文档页面，提取纯文本。
若网络受限，自动回退到内置的 4ga Boards 功能知识库。
"""

import time
import json
import requests
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import track

console = Console(legacy_windows=False)

# 手动整理的文档页面路径（防止爬取被限速或返回 415）
KNOWN_DOC_PAGES = [
    "/docs/intro/",
    "/docs/user-manual/",
    "/docs/user-manual/registration/",
    "/docs/user-manual/structure/",
    "/docs/user-manual/lists/",
    "/docs/user-manual/cards/",
    "/docs/user-manual/sidebar/",
    "/docs/user-manual/settings/",
    "/docs/admin-guide/",
    "/docs/admin-guide/instance-settings/",
    "/docs/admin-guide/project-settings/",
    "/docs/faq/",
]

# 内置知识库：网络不可用时的备用内容
FALLBACK_KNOWLEDGE = """
## 账户注册与登录
支持邮箱/密码注册，以及 Google、GitHub、Microsoft 第三方登录。
注册需要填写用户名、邮箱地址和密码。登录后可访问个人设置和所有项目。
支持忘记密码后通过邮件重置。

## 四级组织结构
4ga Boards 使用四级结构管理工作：
实例(Instance)是整个部署；项目(Project)是最高层容器；
看板(Board)包含多个列表；卡片(Card)是最小任务单元。

## 项目管理
创建项目：点击侧边栏"+"按钮，输入项目名称。
项目设置：修改名称、背景、成员权限。
删除项目需要管理员权限。
支持从 Trello (.json) 和其他工具 (.csv) 导入数据。

## 看板操作
创建看板：在项目内点击"添加看板"。
看板展示所有列表和卡片，支持自定义背景颜色或图片。
实时更新：无需刷新页面即可看到他人的变更。

## 列表管理
列表是看板上代表工作流阶段的列，默认看板模板包含 5 个空列表。
添加列表：点击看板右侧"+ 添加列表"。
重命名：双击列表标题。
折叠列表：点击折叠按钮节省空间。
删除列表会同时删除其中所有卡片。
拖拽列表标题可调整顺序。

## 卡片管理
创建卡片：点击列表底部"+ 添加卡片"，输入标题后确认。
移动卡片：拖拽到其他列表，或在菜单中选择目标列表/看板。
复制卡片：右键菜单中选择"复制"。
删除卡片：在卡片菜单中选择"删除"。
支持快速编辑卡片标题。

## 卡片详情
每张卡片支持以下信息：
描述(Description)：富文本 Markdown 编辑器，支持彩色文字。
截止日期(Due Date)：设置任务截止时间。
成员(Members)：分配团队成员。
标签(Labels)：彩色标签分类，可自定义名称和颜色。
任务清单(Tasks/Checklist)：子任务列表，支持勾选完成。
附件(Attachments)：上传文件。
评论(Comments)：团队讨论区。
活动记录(Activities)：自动记录操作历史。

## 侧边栏导航
侧边栏始终可用，提供快速导航。
显示项目列表和看板列表，支持收藏常用看板。
可折叠/展开以获得更大工作区。

## 搜索与过滤
全局搜索：搜索卡片、项目、看板名称。
过滤器：按标签、成员、截止日期过滤卡片。

## 个人设置
修改用户名和头像。
更改密码。
通知设置：配置邮件和应用内通知。
界面设置：切换深色/浅色模式。
语言设置：切换界面语言。

## 实例设置（管理员）
用户管理：查看、禁用、删除用户。
注册设置：开启/关闭公开注册。
SSO 配置：配置第三方登录。

## 项目设置
修改项目名称和背景。
管理项目成员和权限。
转让项目所有权。

## 实时协作
多用户同时操作，所有变更实时同步。
通知系统：@提及、卡片更新通知。
活动日志：查看完整操作历史。
"""


class DocsCrawler:
    """爬取 4ga Boards 文档站点"""

    def __init__(self, base_url: str, output_dir: str = "data"):
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; TestBot/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        })

    def _fetch_page(self, path: str) -> dict | None:
        """爬取单个页面，返回 {url, title, content}"""
        url = urljoin(self.base_url, path)
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "lxml")

            # 提取标题
            title = ""
            if soup.find("h1"):
                title = soup.find("h1").get_text(strip=True)
            elif soup.title:
                title = soup.title.string or ""

            # 移除导航、页眉、页脚等干扰内容
            for tag in soup(["nav", "header", "footer", "script", "style", "aside"]):
                tag.decompose()

            # 优先取 main/article 区域
            main = (soup.find("main")
                    or soup.find("article")
                    or soup.find("div", class_=lambda c: c and "content" in c.lower()))
            content_el = main if main else soup.body
            content = content_el.get_text(separator="\n", strip=True) if content_el else ""

            if len(content) < 50:
                return None

            return {"url": url, "path": path, "title": title, "content": content}

        except Exception as e:
            console.print(f"[yellow]爬取失败 {url}: {e}[/yellow]")
            return None

    def crawl(self) -> list[dict]:
        """爬取所有已知页面；若全部失败则使用内置知识库"""
        console.print(f"[cyan]开始爬取文档: {self.base_url}[/cyan]")
        pages = []
        for path in track(KNOWN_DOC_PAGES, description="爬取文档页面"):
            page = self._fetch_page(path)
            if page:
                pages.append(page)
                console.print(f"  [green]✓[/green] {page['title'] or path}")
            time.sleep(0.3)   # 礼貌性延迟

        if not pages:
            console.print("[yellow]所有页面爬取失败，切换到内置知识库[/yellow]")
            pages = self._fallback_pages()

        self._save(pages)
        console.print(f"[green]完成，共 {len(pages)} 个文档块[/green]")
        return pages

    def _fallback_pages(self) -> list[dict]:
        """将内置知识库按章节切分为多个伪页面"""
        pages = []
        for i, section in enumerate(FALLBACK_KNOWLEDGE.strip().split("\n## ")):
            if not section.strip():
                continue
            lines = section.strip().split("\n")
            title = lines[0].lstrip("# ").strip()
            content = "\n".join(lines[1:]).strip()
            pages.append({
                "url": f"builtin://4gaboards/{i}",
                "path": f"/builtin/{i}",
                "title": title,
                "content": content,
            })
        return pages

    def _save(self, pages: list[dict]):
        out = self.output_dir / "crawled_docs.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False, indent=2)
        console.print(f"[dim]文档已缓存至 {out}[/dim]")

    def load_cached(self) -> list[dict]:
        """加载已缓存的文档，不存在则返回空列表"""
        cache = self.output_dir / "crawled_docs.json"
        if cache.exists():
            with open(cache, encoding="utf-8") as f:
                data = json.load(f)
            console.print(f"[green]加载缓存文档：{len(data)} 个块[/green]")
            return data
        return []


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from config import DOCS_BASE_URL, DATA_DIR
    crawler = DocsCrawler(DOCS_BASE_URL, DATA_DIR)
    pages = crawler.crawl()
    print(f"共 {len(pages)} 个文档块")
