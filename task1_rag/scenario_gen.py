"""
task1_rag/scenario_gen.py
核心模块：RAG + Claude API → 提取功能点 → 生成结构化测试场景
"""

import json
import re
import sys
import os
from urllib.parse import urlparse
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pydantic import BaseModel, Field
from rich.console import Console
from rich.progress import track

from llm_client import LLMClient, DEFAULT_BASE_URL

console = Console(legacy_windows=False)


# ══════════════════════════════════════════════════════════════════════════════
# 数据模型（Pydantic）
# ══════════════════════════════════════════════════════════════════════════════

class TestStep(BaseModel):
    """单个操作步骤"""
    action:      str = Field(description="操作类型：navigate/click/input/select/hover/wait/press/setInputFiles")
    target:      str = Field(description="操作目标：元素描述或 CSS 选择器提示")
    value:       str = Field(default="", description="输入值或选项（无则为空）")
    description: str = Field(description="步骤的中文自然语言描述")


class TestExpectation(BaseModel):
    """预期状态（测试预言）"""
    condition:   str = Field(description="验证方式：visible/not_visible/url_contains/text_contains/count_greater_than")
    target:      str = Field(description="验证目标：元素或页面区域")
    value:       str = Field(description="期望值")
    description: str = Field(description="预期状态的中文描述")


class TestScenario(BaseModel):
    """一个完整的测试场景"""
    id:           str
    name:         str
    feature_id:   str
    priority:     str = Field(default="medium", description="high / medium / low")
    precondition: str = Field(default="")
    steps:        list[TestStep]
    expectations: list[TestExpectation]
    tags:         list[str] = Field(default_factory=list)


class Feature(BaseModel):
    """一个软件功能点"""
    id:          str
    name:        str
    description: str
    category:    str = Field(description="功能分类，如：用户管理/项目管理/卡片操作")
    scenarios:   list[TestScenario] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# 提示词
# ══════════════════════════════════════════════════════════════════════════════

FEATURE_PROMPT = """\
你是一名专业的软件测试工程师，正在分析 4ga Boards（看板式项目管理工具）的用户手册。

## 参考文档
{context}

## 任务
从文档中提取**测试视角的主要功能点**，重点关注核心业务操作，避免被次要细节淹没。

## 必须覆盖的核心功能（如文档提到，务必单独成项）
**用户管理**
- 登录、登出、修改密码、用户资料维护
- 注意：4ga Boards demo 站没有公开注册页，不要把“公开注册账号”作为功能点

**项目管理**
- 创建项目、修改项目设置、删除项目、邀请成员

**看板操作**
- 创建看板、切换看板视图、删除看板、导入看板

**列表管理**
- 创建列表、重命名列表、移动列表、折叠/展开列表、删除列表

**卡片管理**（核心操作 + 富文本合并）
- 创建卡片、移动卡片（拖拽/菜单）、复制卡片、删除卡片、编辑卡片标题
- 设置卡片成员、设置标签、设置截止日期、设置任务清单
- 添加附件、添加评论
- **编辑卡片描述**（把富文本编辑器的所有特性如：彩色文本/代码块/表格/列表/@提及 等**合并成"编辑卡片描述（富文本）"一个功能点**，不要拆成多个）

**设置**
- 修改用户资料、修改通知偏好、切换深色/浅色模式、切换侧边栏样式

## 输出格式
```json
[
  {{
    "id": "f001",
    "name": "动宾短语（如：创建卡片）",
    "description": "一句话描述",
    "category": "用户管理/项目管理/看板操作/列表管理/卡片管理/设置"
  }}
]
```

## 关键约束
1. 功能点总数必须在 **23-28 个**之间
2. 每个分类 3-6 个，卡片管理不超过 7 个
3. **富文本编辑器只算 1 个功能点**，不要把彩色文本/表格/列表/快捷键等单独拆开
4. 优先 **CRUD（创建/读取/更新/删除）核心操作**，次要细节合并或省略
5. 不要生成公开注册账号功能点
6. 只输出 JSON，不要任何解释
"""

SCENARIO_PROMPT = """\
你是一名专业的 Web 自动化测试工程师，请为以下功能点生成可被 Playwright 直接执行的测试场景。

## 功能点
- ID: {feature_id}
- 名称: {feature_name}
- 描述: {feature_description}
- 分类: {feature_category}

## 相关文档
{context}

## 真实页面 DOM 参考（以下元素已通过自动化抓取确认存在）
{dom_reference}

## 目标应用
URL: https://demo.4gaboards.com
界面语言：优先参考 DOM 快照；若账号偏好导致按钮文案不是英文，必须优先使用 CSS selector、name、aria-label 等稳定属性
演示账号: demo@demo.demo / demo

## 已知 URL 映射（登录后实际跳转路径）
- 登录成功后：URL 为 `/`（不是 `/dashboard`）
- 项目详情页：`/projects/{{slug}}`
- 看板页：`/boards/{{id}}`
- 设置页：无独立 URL，通过弹窗打开

## 应用限制（必须遵守）
- 4ga Boards demo 站没有公开注册页，不要生成注册相关场景
- 修改密码功能在用户设置弹窗中，不是独立页面
- 删除项目需要在项目设置中操作，不能直接在 dashboard 删除
- Dashboard 上创建项目按钮的真实文本通常是 `Add Project`，不要写成 `Create new project`
- 用户菜单在 demo 账号中通常显示为 `DD`，不要编造 `UserMenu` class

## ⚠️ 关键要求：target 字段必须可被自动化工具识别
**禁止**用中文描述按钮（如"创建项目按钮"）。**必须**使用以下三种之一：
1. **CSS 选择器**（优先）：`button[type='submit']`, `input[name='name']`
2. **英文按钮/链接文本**：`Create new project`, `Add Project`, `Save`, `Cancel`, `Submit`
3. **英文 placeholder/aria-label**：`Email or Username`, `Enter project name`

### 严格 DOM 约束
- target 字段只能使用上方 DOM 参考中确实存在的元素属性、文本或通用 HTML selector
- expectations 的 target 同样必须来自 DOM 参考或页面 URL
- 禁止编造 `data-testid`、不存在的 class 名、不存在的 id
- 如果 DOM 快照里的文本不是英文，不要自行翻译成英文 target
- 禁止把 `button[type='button']`、`button`、`input` 这类过泛 selector 作为核心 expectation
- 登录成功的 expectation 应验证 `/` URL + Dashboard 上的具体元素（如 `Add Project`、`Settings`、`DD`），不要只验证“页面存在按钮”
- 取消/删除/保存后必须验证具体弹窗或具体 URL 状态，不要使用空字符串或无意义 target
- 测试数据也必须使用英文，例如 `Test Card Title`、`Temporary Card`，不要把中文测试数据写进 target

### 4ga Boards 常见英文术语对照（用于猜测 target）
- 创建/添加 → `Create`, `Add`, `+`
- 项目 → `Project`
- 看板 → `Board`
- 列表 → `List`
- 卡片 → `Card`
- 标签 → `Label`
- 成员 → `Member`
- 设置 → `Settings`
- 保存 → `Save`
- 删除 → `Delete`, `Remove`
- 取消 → `Cancel`
- 关闭 → `Close`
- 用户名/邮箱框 → `input[name='emailOrUsername']` 或 `input[type='email']`
- 密码框 → `input[type='password']`
- 提交按钮 → `button[type='submit']`

## 任务
生成 1~3 个测试场景，以 JSON 数组格式输出，不要输出其他任何内容。

## 输出格式
```json
[
  {{
    "id": "场景ID，如 f001_s01",
    "name": "场景名称（中文可）",
    "feature_id": "{feature_id}",
    "priority": "high/medium/low",
    "precondition": "前置条件",
    "steps": [
      {{
        "action": "navigate|click|input|select|hover|wait|press|setInputFiles",
        "target": "CSS selector 或英文文本（不要中文）",
        "value":  "输入值（无则留空）",
        "description": "步骤的中文说明，仅用于阅读"
      }}
    ],
    "expectations": [
      {{
        "condition": "visible|not_visible|url_contains|text_contains|count_greater_than",
        "target":    "CSS selector 或英文文本（不要中文）",
        "value":     "期望值",
        "description": "预期状态描述（中文可）"
      }}
    ],
    "tags": ["标签"]
  }}
]
```

## 示例
```json
{{
  "action": "click",
  "target": "Add Project",
  "value": "",
  "description": "点击仪表板上的『Add Project』按钮"
}}
```

要求：
1. **target 字段绝对不能是中文描述**，必须可直接被 Playwright 用作 selector 或 has-text 文本
2. 步骤精简，每步只做一件事
3. 以正常流程（happy path）为主
4. 只输出 JSON，不要任何解释文字
"""


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def parse_json(text: str) -> list:
    """从 LLM 返回文本中安全提取 JSON 数组，带多级修复（Bug-2/Bug-15）"""
    if not text or not text.strip():
        console.print("[red]LLM 返回为空（可能是思考型模型 max_tokens 不足或网络异常）[/red]")
        return []

    raw = text

    # 第 1 级：提取 markdown ```json ... ``` 代码块
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        # 退而求其次：找第一个 [ ... ] 区间
        start = text.find("[")
        end   = text.rfind("]") + 1
        if start >= 0 and end > 0:
            text = text[start:end]

    # 第 2 级：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 第 3 级：用 json_repair 库修复（支持嵌套结构、未闭合字符串等）
    try:
        from json_repair import repair_json
        repaired = repair_json(text, return_objects=True)
        if isinstance(repaired, list):
            console.print(f"[yellow]JSON 已通过 json_repair 修复，恢复 {len(repaired)} 项[/yellow]")
            return repaired
        if isinstance(repaired, dict):
            return [repaired]
    except Exception:
        pass

    # 第 4 级：手动截断修复（从后往前逐 } 尝试截断并补 ]）
    for i in range(len(text) - 1, 0, -1):
        if text[i] == '}':
            candidate = text[:i + 1].rstrip().rstrip(",") + "\n]"
            try:
                result = json.loads(candidate)
                console.print(f"[yellow]截断修复成功，恢复 {len(result)} 项[/yellow]")
                return result
            except json.JSONDecodeError:
                continue

    console.print(f"[red]JSON 解析彻底失败[/red]")
    console.print(f"[dim]原始返回前 500 字: {raw[:500]}[/dim]")
    return []


# ══════════════════════════════════════════════════════════════════════════════
# 核心生成器
# ══════════════════════════════════════════════════════════════════════════════

class ScenarioGenerator:
    """RAG + GLM → 功能点提取 + 测试场景生成"""

    def __init__(self,
                 api_key: str,
                 model: str,
                 rag_engine=None,
        base_url: str = DEFAULT_BASE_URL):
        self.llm   = LLMClient(api_key=api_key, model=model, base_url=base_url)
        self.model = model
        self.rag   = rag_engine
        self._dom_snapshots: dict | None = None

    # ── 内部：调用 LLM ────────────────────────────────────────────────────────

    def _llm(self, prompt: str, max_tokens: int = 4096) -> str:
        return self.llm.generate(prompt, max_tokens=max_tokens)

    # ── DOM 快照：为 LLM 提供真实页面元素参考 ───────────────────────────────

    def _dom_snapshot_path(self) -> str:
        try:
            from config import DATA_DIR
        except Exception:
            DATA_DIR = "data"
        root = os.path.dirname(os.path.dirname(__file__))
        return os.path.join(root, DATA_DIR, "dom_snapshots.json")

    def _load_dom_snapshots(self) -> dict:
        if self._dom_snapshots is not None:
            return self._dom_snapshots

        path = self._dom_snapshot_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._dom_snapshots = json.load(f)
        except FileNotFoundError:
            self._dom_snapshots = {}
        except Exception as e:
            console.print(f"[yellow]DOM 快照读取失败：{e}[/yellow]")
            self._dom_snapshots = {}
        return self._dom_snapshots

    def _get_dom_reference(self, category: str) -> str:
        snapshots = self._load_dom_snapshots()
        if not snapshots:
            return "（DOM 快照未生成，可运行 python -m task1_rag.dom_snapshot 生成；当前仅允许通用 HTML selector 和明确英文文本）"

        category_page_map = {
            "用户管理": ["login"],
            "项目管理": ["dashboard"],
            "看板操作": ["dashboard", "board"],
            "列表管理": ["board"],
            "卡片管理": ["board"],
            "卡片操作": ["board"],
            "设置": ["dashboard", "board"],
        }
        pages = category_page_map.get(category, ["dashboard", "board"])
        lines = []

        for page_name in pages:
            snap = snapshots.get(page_name, {})
            lines.append(f"### {page_name} 页面 (URL: {snap.get('url', '?')})")
            for el in snap.get("elements", [])[:35]:
                attrs = []
                for key, label in (
                    ("selector", "selector"),
                    ("name", "name"),
                    ("placeholder", "placeholder"),
                    ("text", "text"),
                    ("aria_label", "aria-label"),
                    ("classes", "class"),
                    ("role", "role"),
                    ("id", "id"),
                ):
                    value = (el.get(key) or "").strip()
                    if value:
                        attrs.append(f'{label}="{value.replace(chr(34), chr(39))}"')
                lines.append(f"  - <{el.get('tag', '?')}> {' '.join(attrs)}")

        return "\n".join(lines)

    def _all_dom_texts(self) -> set[str]:
        texts: set[str] = set()
        for snap in self._load_dom_snapshots().values():
            for el in snap.get("elements", []):
                for key in ("text", "placeholder", "aria_label", "classes", "name", "id", "selector"):
                    value = (el.get(key) or "").strip().lower()
                    if value:
                        texts.add(value)
        return texts

    def _polish_scenarios(self, feature: Feature, scenarios: list[TestScenario]) -> list[TestScenario]:
        """修正常见可执行性问题，避免 LLM 继续输出旧文档里的猜测 target。"""
        text_rewrites = {
            "测试卡片标题": "Test Card Title",
            "临时卡片": "Temporary Card",
            "测试列表": "Test List",
            "临时列表": "Temporary List",
            "测试项目": "Test Project",
            "临时项目": "Temporary Project",
        }

        for scenario in scenarios:
            feature_name = feature.name
            is_create_project_cancel = "创建项目" in feature_name and "取消" in scenario.name
            is_login_success = "登录" in feature_name and "成功" in scenario.name
            is_logout = "登出" in feature_name
            is_board_switch = "看板" in feature_name and "切换" in feature_name
            is_import_board = "导入" in feature_name or "导入" in scenario.name
            if is_login_success:
                scenario.steps = [
                    TestStep(
                        action="login",
                        target="login_form",
                        value="demo@demo.demo|demo",
                        description="使用演示账号登录并等待 Dashboard 渲染完成",
                    )
                ]
            has_dashboard_wait = any(
                step.action.lower() in {"wait", "sleep"} and "dashboard" in step.description.lower()
                for step in scenario.steps
            )
            has_cancel_action = any(
                (
                    step.action.lower() == "press"
                    and (step.value or step.target).strip().lower() == "escape"
                )
                or (
                    step.action.lower() == "click"
                    and "cancel" in step.target.strip().lower()
                )
                for step in scenario.steps
            )
            has_logout_wait = any(
                step.action.lower() in {"wait", "sleep"} and "登出" in step.description
                for step in scenario.steps
            )
            polished_steps: list[TestStep] = []

            for step in scenario.steps:
                for old, new in text_rewrites.items():
                    step.target = step.target.replace(old, new)
                    step.value = step.value.replace(old, new)

                target = step.target.strip()
                target_lower = target.lower()

                if is_create_project_cancel and step.action.lower() in {"input", "type", "fill"}:
                    continue

                if "登出" in feature_name and ("usermenu" in target_lower or "profile" in target_lower):
                    step.target = "DD"
                    step.description = "点击右上角用户菜单（demo 账号显示为 DD）"

                if "创建项目" in feature_name and "create new project" in target_lower:
                    step.target = "Add Project"
                    step.description = step.description.replace("创建新项目", " Add Project").replace("点击Add Project", "点击 Add Project")

                if "创建项目" in feature_name and "enter project name" in target_lower:
                    step.target = "input"

                if feature.category == "列表管理" and target in {"button[type='button']:has-text('+')", "+", "Add Board"}:
                    step.target = "Add list"
                    step.description = step.description.replace("『+』", "Add list")

                if step.action.lower() == "press" and target_lower == "body" and step.value.strip():
                    step.target = step.value.strip()
                    step.value = ""

                if "编辑卡片标题" in feature_name and target_lower == "h2":
                    step.target = "[contenteditable='true']"
                    step.description = step.description.replace("卡片标题", "卡片标题编辑区域")

                if is_import_board:
                    if step.action.lower() == "click" and "4ga boards" in target_lower:
                        continue
                    if step.action.lower() in {"setinputfiles", "set_input_files", "upload", "upload_file"}:
                        if "4gaboards_export" in step.value:
                            step.target = "From 4ga Boards"
                            step.description = "选择 From 4ga Boards 并上传 TGZ 文件"
                        elif "trello_export" in step.value:
                            step.target = "From Trello"
                            step.description = "选择 From Trello 并上传 JSON 文件"
                    if step.action.lower() in {"input", "type", "fill"} and "boardname" in target_lower:
                        step.target = "input[name='name']"

                if is_create_project_cancel and step.action.lower() == "click" and "cancel" in target_lower:
                    step = TestStep(
                        action="press",
                        target="Escape",
                        value="Escape",
                        description="按 Escape 取消创建项目",
                    )
                    has_cancel_action = True

                polished_steps.append(step)

                if (
                    is_login_success
                    and not has_dashboard_wait
                    and step.action.lower() == "click"
                    and ("submit" in step.target.lower() or "log in" in step.target.lower())
                ):
                    polished_steps.append(TestStep(
                        action="wait",
                        target="Add Project",
                        value="3",
                        description="等待 Dashboard 渲染完成",
                    ))
                    has_dashboard_wait = True

                if (
                    is_logout
                    and not has_logout_wait
                    and step.action.lower() == "click"
                    and "log out" in step.target.lower()
                ):
                    polished_steps.append(TestStep(
                        action="wait",
                        target="Email or username",
                        value="2",
                        description="等待登出后的登录页渲染完成",
                    ))
                    has_logout_wait = True

            if is_create_project_cancel and not has_cancel_action:
                polished_steps.append(TestStep(
                    action="press",
                    target="Escape",
                    value="Escape",
                    description="按 Escape 取消创建项目",
                ))

            scenario.steps = polished_steps
            if is_create_project_cancel:
                deduped_steps: list[TestStep] = []
                seen_escape = False
                for step in scenario.steps:
                    is_escape = (
                        step.action.lower() == "press"
                        and (step.value or step.target).strip().lower() == "escape"
                    )
                    if is_escape and seen_escape:
                        continue
                    if is_escape:
                        seen_escape = True
                    deduped_steps.append(step)
                scenario.steps = deduped_steps

            for exp in scenario.expectations:
                for old, new in text_rewrites.items():
                    exp.target = exp.target.replace(old, new)
                    exp.value = exp.value.replace(old, new)

                target = exp.target.strip()
                target_lower = target.lower()
                desc = exp.description.lower()

                if "登录" in feature_name and exp.condition == "visible" and self._is_overbroad_target(target):
                    exp.target = "Add Project"
                    exp.value = ""
                    exp.description = "Dashboard 上的 Add Project 按钮可见，表示已登录"

                if exp.condition in {"visible", "not_visible"} and "enter project name" in target_lower:
                    exp.target = "input"

                if feature.category == "列表管理" and exp.condition == "visible" and "list" in target_lower:
                    if "输入框" in exp.description or "input" in target_lower:
                        exp.target = "input"

                if "编辑卡片标题" in feature_name and target_lower == "h2":
                    if exp.condition == "text_contains" and exp.value.strip():
                        exp.condition = "visible"
                        exp.target = exp.value.strip()
                        exp.value = ""
                    else:
                        exp.target = "[contenteditable='true']"
                    exp.description = exp.description.replace("卡片标题", "卡片标题编辑区域")

                if is_board_switch and "filter boards" in target_lower:
                    exp.target = "Kanban Test Board"
                    exp.value = ""
                    exp.description = "目标看板名称可见，表示已进入看板页面"

                if exp.condition == "url_contains" and not exp.value.strip():
                    exp.value = self._infer_url_expectation_value(exp)

                if self._is_overbroad_target(exp.target) and "login" not in desc and "警告：" not in exp.description:
                    exp.description = f"{exp.description}（警告：该验证目标过泛，建议替换为具体 DOM 文本或 selector）"

            if is_create_project_cancel:
                scenario.expectations = [
                    TestExpectation(
                        condition="url_contains",
                        target="/",
                        value="/",
                        description="取消后仍停留在 Dashboard",
                    ),
                    TestExpectation(
                        condition="visible",
                        target="Add Project",
                        value="",
                        description="Dashboard 上仍显示 Add Project",
                    ),
                ]

            if is_logout:
                scenario.expectations = [
                    TestExpectation(
                        condition="visible",
                        target="input[name='emailOrUsername']",
                        value="",
                        description="登出后重新显示用户名/邮箱输入框",
                    ),
                    TestExpectation(
                        condition="visible",
                        target="button[type='submit']",
                        value="",
                        description="登出后重新显示登录提交按钮",
                    ),
                ]

        return scenarios

    def _is_overbroad_target(self, target: str) -> bool:
        target = (target or "").strip().lower()
        return target in {
            "button",
            "button[type='button']",
            'button[type="button"]',
            "input",
            "div",
            "span",
            "a",
        }

    def _fix_expectations(self, scenarios: list[TestScenario]) -> list[TestScenario]:
        known_fixes = {
            "/dashboard": "/",
            "/home": "/",
            "/register": "/",
        }
        dom_texts = self._all_dom_texts()
        dynamic_texts = {
            "test project",
            "temporary project",
            "test board",
            "kanban test board",
            "test list",
            "temporary list",
            "test card title",
            "temporary card",
            "updated card title",
            "temporary title",
        }
        missing_dom_warning = "（警告：该目标未在 DOM 快照中找到）"

        for scenario in scenarios:
            for exp in scenario.expectations:
                if missing_dom_warning in exp.description:
                    exp.description = exp.description.replace(missing_dom_warning, "")

                if exp.condition == "url_contains":
                    if not exp.value.strip():
                        exp.value = self._infer_url_expectation_value(exp)
                    exp.value = known_fixes.get(exp.value, exp.value)
                    continue

                if exp.condition == "visible" and exp.target and dom_texts:
                    target = exp.target.strip().lower()
                    looks_like_selector = any(c in target for c in "[].#>:=") or target.startswith(
                        ("button", "input", "textarea", "select", "a", "h1", "h2", "h3", "h4", "h5", "h6")
                    )
                    if not looks_like_selector and target not in dom_texts and target not in dynamic_texts:
                        exp.description = f"{exp.description}（警告：该目标未在 DOM 快照中找到）"

        return scenarios

    def _infer_url_expectation_value(self, exp: TestExpectation) -> str:
        target = exp.target.strip()
        description = exp.description.strip()

        if target.startswith(("http://", "https://")):
            path = urlparse(target).path
            return path or "/"

        if target.startswith("/"):
            return target

        match = re.search(r"/(?:boards|projects|login)(?:/|$)", description)
        if match:
            return match.group(0)

        if "根路径" in description or "首页" in description or "dashboard" in description.lower():
            return "/"

        return "/"

    def _dedup_scenarios(self, scenarios: list[TestScenario]) -> list[TestScenario]:
        seen = set()
        result = []
        for scenario in scenarios:
            step_signature = "|".join(f"{step.action}:{step.target}" for step in scenario.steps[:3])
            key = re.sub(r"\s+", "", f"{scenario.name}:{step_signature}").lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(scenario)
        return result

    def _normalize_features(self, features: list[Feature]) -> list[Feature]:
        seen = set()
        result = []
        blocked_keywords = ("公开注册", "用户注册", "注册账号", "注册账户")
        synonym_names = {
            "维护用户资料": "修改用户资料",
        }
        canonical_categories = {
            "修改用户资料": "用户管理",
        }
        card_property_names = {"设置卡片成员", "设置标签", "设置截止日期", "设置任务清单"}
        card_count = 0
        max_per_category = {"卡片管理": 7}

        for feature in features:
            name_desc = f"{feature.name} {feature.description}"
            if any(keyword in name_desc for keyword in blocked_keywords):
                console.print(f"[yellow]跳过 demo 站不可执行功能点: {feature.name}[/yellow]")
                continue

            feature.name = synonym_names.get(feature.name, feature.name)
            if feature.name in canonical_categories:
                feature.category = canonical_categories[feature.name]

            if feature.category == "卡片管理" and feature.name in card_property_names:
                feature.name = "设置卡片属性"
                feature.description = "为卡片设置成员、标签、截止日期或任务清单等常用属性"

            key = re.sub(r"\s+", "", f"{feature.category}:{feature.name}").lower()
            if key in seen:
                continue

            if feature.category == "卡片管理":
                if card_count >= max_per_category["卡片管理"]:
                    console.print(f"[yellow]跳过超出卡片管理上限的功能点: {feature.name}[/yellow]")
                    continue
                card_count += 1

            seen.add(key)
            result.append(feature)

        for i, feature in enumerate(result, 1):
            feature.id = f"f{i:03d}"

        return result

    # ── 步骤一：提取功能点 ────────────────────────────────────────────────────

    def extract_features(self, pages: list[dict] | None = None) -> list[Feature]:
        console.print("[cyan]步骤 1/2：提取功能点...[/cyan]")

        # 用 RAG 检索最相关内容，或直接拼接文档
        if self.rag:
            # 多组查询保证各分类（项目/看板/列表/卡片/设置）的核心 CRUD 都被召回，
            # 避免单一查询被 card.md 这种长文档全部占满。
            queries = [
                "create project board list card",
                "delete remove board list card project",
                "move drag card to another list",
                "edit rename card list board title",
                "register login logout password user account",
                "settings preferences notifications profile sidebar",
                "import export project board",
            ]
            seen_chunks: set[int] = set()
            parts = []
            for q in queries:
                for chunk_text_val, _score, meta in self.rag.search(q, top_k=4):
                    # Bug-11: chunk 级去重，避免同一片段在不同 query 中被重复计入
                    normalized = " ".join(chunk_text_val.split())
                    chunk_hash = hash(normalized)
                    if chunk_hash in seen_chunks:
                        continue
                    seen_chunks.add(chunk_hash)
                    title = meta.get("source_title", "")
                    parts.append(f"[来源: {title}]\n{chunk_text_val}")
            context = "\n\n---\n\n".join(parts)
        elif pages:
            parts, total = [], 0
            for p in pages:
                chunk = f"## {p.get('title','')}\n{p.get('content','')}"
                if total + len(chunk) > 12000:
                    break
                parts.append(chunk)
                total += len(chunk)
            context = "\n\n".join(parts)
        else:
            context = "（无文档，基于 4ga Boards 通用功能生成）"

        raw = parse_json(self._llm(FEATURE_PROMPT.format(context=context), max_tokens=6000))

        features = []
        for item in raw:
            try:
                features.append(Feature(
                    id=item.get("id", f"f{len(features)+1:03d}"),
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    category=item.get("category", "通用"),
                ))
            except Exception as e:
                console.print(f"[yellow]跳过无效功能点: {e}[/yellow]")

        features = self._normalize_features(features)

        console.print(f"[green]提取到 {len(features)} 个功能点[/green]")
        return features

    # ── 步骤二：为每个功能点生成测试场景 ──────────────────────────────────────

    def generate_scenarios(self, feature: Feature, max_retries: int = 2) -> list[TestScenario]:
        dom_reference = self._get_dom_reference(feature.category)

        for attempt in range(max_retries + 1):
            context = (
                self.rag.get_context(f"{feature.name} {feature.description}", top_k=4)
                if self.rag
                else feature.description
            )

            raw = parse_json(self._llm(
                SCENARIO_PROMPT.format(
                    feature_id=feature.id,
                    feature_name=feature.name,
                    feature_description=feature.description,
                    feature_category=feature.category,
                    context=context,
                    dom_reference=dom_reference,
                ),
                max_tokens=4096,
            ))

            scenarios = []
            for i, item in enumerate(raw):
                try:
                    scenarios.append(TestScenario(
                        id=item.get("id", f"{feature.id}_s{i+1:02d}"),
                        name=item.get("name", f"{feature.name}场景{i+1}"),
                        feature_id=feature.id,
                        priority=item.get("priority", "medium"),
                        precondition=item.get("precondition", ""),
                        steps=[TestStep(**s) for s in item.get("steps", [])],
                        expectations=[TestExpectation(**e) for e in item.get("expectations", [])],
                        tags=item.get("tags", []),
                    ))
                except Exception as e:
                    console.print(f"[yellow]跳过无效场景: {e}[/yellow]")

            scenarios = self._fix_expectations(self._polish_scenarios(feature, self._dedup_scenarios(scenarios)))
            if scenarios:
                return scenarios

            if attempt < max_retries:
                console.print(f"[yellow]功能点 {feature.name} 第 {attempt + 1} 次生成为空，重试...[/yellow]")

        console.print(f"[red]功能点 {feature.name} 重试 {max_retries} 次仍为空[/red]")
        return []

    # ── 完整流程 ──────────────────────────────────────────────────────────────

    def run(self,
            pages: list[dict] | None = None,
            scenarios_path: str = "data/test_scenarios.json",
            features_path:  str = "data/features.json",
            ) -> tuple[list[Feature], list[TestScenario]]:
        """
        完整执行：提取功能点 → 逐个生成测试场景 → 保存结果
        返回 (features, all_scenarios)
        """
        os.makedirs(os.path.dirname(scenarios_path), exist_ok=True)

        # 1. 提取功能点
        features = self.extract_features(pages)

        # 2. 为每个功能点生成场景
        console.print("[cyan]步骤 2/2：生成测试场景...[/cyan]")
        all_scenarios: list[TestScenario] = []

        for feature in track(features, description="生成测试场景"):
            try:
                scenarios = self.generate_scenarios(feature)
                feature.scenarios = scenarios
                all_scenarios.extend(scenarios)
                console.print(f"  [green]✓[/green] {feature.name}（{len(scenarios)} 个场景）")
            except Exception as e:
                console.print(f"  [red]✗[/red] {feature.name}: {e}")

        all_scenarios = self._dedup_scenarios(all_scenarios)

        # Bug-3 / Bug-10: 数量守护 — 低于 A 版本基线时补充空场景功能点
        if len(features) < 23 or len(all_scenarios) < 50:
            console.print(
                f"[yellow]⚠ 功能点/场景数量低于 A 版本验收线："
                f"{len(features)} features, {len(all_scenarios)} scenarios，"
                f"尝试对空场景功能点重新生成...[/yellow]"
            )
            for feature in features:
                if not feature.scenarios:
                    retried = self.generate_scenarios(feature, max_retries=3)
                    if retried:
                        feature.scenarios = retried
                        all_scenarios.extend(retried)
                        console.print(
                            f"  [yellow]↻ 补充 {feature.name}（{len(retried)} 个场景）[/yellow]"
                        )
            all_scenarios = self._dedup_scenarios(all_scenarios)

        # 3. 保存 JSON
        with open(features_path, "w", encoding="utf-8") as f:
            json.dump([ft.model_dump() for ft in features], f, ensure_ascii=False, indent=2)

        with open(scenarios_path, "w", encoding="utf-8") as f:
            json.dump([s.model_dump() for s in all_scenarios], f, ensure_ascii=False, indent=2)

        console.print(f"\n[bold green]✅ 完成！"
                      f"{len(features)} 个功能点，{len(all_scenarios)} 个测试场景[/bold green]")
        console.print(f"  功能点 → {features_path}")
        console.print(f"  测试场景 → {scenarios_path}")

        # 4. 写入知识图谱（Neo4j 优先，networkx 兜底）
        try:
            from task1_rag.knowledge_graph import KnowledgeGraph
            from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, GRAPH_PATH
            kg = KnowledgeGraph(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, GRAPH_PATH)
            kg.ingest(
                [ft.model_dump() for ft in features],
                [s.model_dump()  for s in all_scenarios],
            )
            console.print(f"[green]知识图谱已更新（backend: {kg.backend_name}）[/green]")
            kg.close()
        except Exception as e:
            console.print(f"[yellow]知识图谱更新失败（不影响主流程）：{e}[/yellow]")

        return features, all_scenarios


# ── 单独运行测试 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from config import (GLM_API_KEY, GLM_BASE_URL, LLM_MODEL, DATA_DIR,
                        VECTOR_DB_PATH, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP,
                        SCENARIOS_PATH, FEATURES_PATH, DOCS_BASE_URL)
    from task1_rag.crawler    import DocsCrawler
    from task1_rag.rag_engine import RAGEngine

    crawler = DocsCrawler(DOCS_BASE_URL, DATA_DIR)
    pages   = crawler.load_cached() or crawler.crawl()

    rag = RAGEngine(VECTOR_DB_PATH, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP)
    if not rag.load_index():
        rag.build_index(pages)

    gen = ScenarioGenerator(GLM_API_KEY, LLM_MODEL, rag, base_url=GLM_BASE_URL)
    gen.run(pages, SCENARIOS_PATH, FEATURES_PATH)
