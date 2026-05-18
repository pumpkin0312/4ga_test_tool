"""
task1_rag/scenario_gen.py
核心模块：RAG + Claude API → 提取功能点 → 生成结构化测试场景
"""

import json
import re
import sys
import os
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
    action:      str = Field(description="操作类型：navigate/click/input/select/hover/wait")
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
- 用户注册、登录、登出、修改密码

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
1. **粒度均衡**：每个分类建议 3-6 个功能点，**不要让某一类（尤其卡片管理）超过 8 个**
2. **富文本编辑器只算 1 个功能点**，不要把彩色文本/表格/列表/快捷键等单独拆开
3. 优先 **CRUD（创建/读取/更新/删除）核心操作**，次要细节合并或省略
4. 期望总数 **20-30 个**功能点
5. 只输出 JSON，不要任何解释
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

## 目标应用
URL: https://demo.4gaboards.com
界面语言：**英文**（按钮、输入框 placeholder、链接文本均为英文）
演示账号: demo@demo.demo / demo

## ⚠️ 关键要求：target 字段必须可被自动化工具识别
**禁止**用中文描述按钮（如"创建项目按钮"）。**必须**使用以下三种之一：
1. **CSS 选择器**（优先）：`button[type='submit']`, `input[name='name']`, `[data-testid='create-project']`
2. **英文按钮/链接文本**：`Create new project`, `Add Project`, `Save`, `Cancel`, `Submit`
3. **英文 placeholder/aria-label**：`Email or Username`, `Enter project name`

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
        "action": "navigate|click|input|select|hover|wait|press",
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
  "target": "Create new project",
  "value": "",
  "description": "点击仪表板上的『创建新项目』按钮"
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
    """从 LLM 返回文本中安全提取 JSON 数组"""
    if not text or not text.strip():
        console.print("[red]LLM 返回为空（可能是思考型模型 max_tokens 不足或网络异常）[/red]")
        return []

    raw = text
    # 优先提取 ```json ... ``` 代码块
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        # 退而求其次：找第一个 [ ... ] 区间
        start = text.find("[")
        end   = text.rfind("]") + 1
        if start >= 0 and end > 0:
            text = text[start:end]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        console.print(f"[red]JSON 解析失败: {e}[/red]")
        console.print(f"[dim]原始返回前 500 字: {raw[:500]}[/dim]")
        # 尝试修复被截断的 JSON：截到最后一个完整的 } 后补 ]
        last_obj_end = text.rfind("}")
        if last_obj_end > 0:
            patched = text[:last_obj_end + 1].rstrip().rstrip(",") + "\n]"
            try:
                fixed = json.loads(patched)
                console.print(f"[yellow]已自动修复截断的 JSON，恢复 {len(fixed)} 项[/yellow]")
                return fixed
            except Exception:
                pass
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

    # ── 内部：调用 LLM ────────────────────────────────────────────────────────

    def _llm(self, prompt: str, max_tokens: int = 4096) -> str:
        return self.llm.generate(prompt, max_tokens=max_tokens)

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
            seen = set()
            parts = []
            for q in queries:
                ctx = self.rag.get_context(q, top_k=3)
                if ctx and ctx not in seen:
                    parts.append(ctx)
                    seen.add(ctx)
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

        console.print(f"[green]提取到 {len(features)} 个功能点[/green]")
        return features

    # ── 步骤二：为每个功能点生成测试场景 ──────────────────────────────────────

    def generate_scenarios(self, feature: Feature) -> list[TestScenario]:
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

        return scenarios

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

        # 3. 保存
        with open(features_path, "w", encoding="utf-8") as f:
            json.dump([ft.model_dump() for ft in features], f, ensure_ascii=False, indent=2)

        with open(scenarios_path, "w", encoding="utf-8") as f:
            json.dump([s.model_dump() for s in all_scenarios], f, ensure_ascii=False, indent=2)

        console.print(f"\n[bold green]✅ 完成！"
                      f"{len(features)} 个功能点，{len(all_scenarios)} 个测试场景[/bold green]")
        console.print(f"  功能点 → {features_path}")
        console.print(f"  测试场景 → {scenarios_path}")

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
