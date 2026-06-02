```python
# 4GA Boards 测试工具 — Bug 报告与分工方案
```

## 一、Bug 总览

共发现 29 个 Bug + 4 个架构不足，按严重程度分为 P0（阻塞）、P1（严重）、P2（中等）、P3（轻微）。

| 编号 | 严重度 | 模块 | 简述 |
| --- | --- | --- | --- |
| Bug-1 | P0 | scenario_gen | 测试预期不贴合真实应用（如 login 期望 /dashboard，实际为 /） |
| Bug-2 | P0 | scenario_gen | DeepSeek 偶尔输出破损 JSON（未闭合字符串） |
| Bug-3 | P1 | scenario_gen | 新生成结果少于原样例（25/54 vs 23/61） |
| Bug-4 | P1 | infra | Neo4j 没真正启用（无 Docker），仅用 networkx 兜底 |
| Bug-5 | P2 | knowledge_graph | networkx 图谱缓存丢字段（已修复） |
| Bug-6 | P1 | scenario_gen | 部分生成步骤不可执行（注册页 selector 不存在） |
| Bug-7 | P1 | rag_engine | RAG 检索质量一般（top1 命中错误文档） |
| Bug-8 | P2 | rag_engine | chunk_text() 当 overlap >= chunk_size 时死循环 |
| Bug-9 | P0 | scenario_gen | ~70% CSS selector 为 LLM 虚构（data-testid/class 不存在于真实 DOM） |
| Bug-10 | P1 | scenario_gen | 场景生成返回 0 结果时无重试（如 f023 富文本功能点 0 场景） |
| Bug-11 | P1 | rag_engine | RAG 去重用完整格式化字符串比对，未做 chunk 级去重 |
| Bug-12 | P2 | rag_engine | embedding 模型 all-MiniLM-L6-v2 对中文支持差 |
| Bug-13 | P1 | scenario_gen | SCENARIO_PROMPT 缺少真实 DOM 结构参考，LLM 靠猜 |
| Bug-14 | P2 | scenario_gen | FEATURE_PROMPT 功能点数量不稳定（20-30 范围太宽） |
| Bug-15 | P1 | scenario_gen | parse_json 截断修复对嵌套 JSON 失效 |
| Bug-16 | P1 | scenario_gen | 生成的 expectations 使用不存在的 CSS selector 做验证目标 |
| Bug-17 | P2 | agent | 备选步骤成功时直接覆盖原 action 记录，丢失备选步骤信息 |
| Bug-18 | P0 | executor | _find() 有 ~15 种策略，最坏情况单步耗时 22 秒 |
| Bug-19 | P1 | executor | 每次 click 后 wait_for_load_state('networkidle') 耗时 3 秒 |
| Bug-20 | P2 | memory | login_state 跨场景持久化，但浏览器每场景重启 |
| Bug-21 | P2 | executor | execute_step 异常时截图可能因浏览器已关闭而二次报错 |
| Bug-22 | P2 | verifier | LLM 不可用时降级阈值硬编码 0.7，不可配置 |
| Bug-23 | P2 | agent | 仅当所有 inline_results 为 false 时才强制 FAIL，部分失败不处理 |
| Bug-24 | P2 | executor | Control+A 在 macOS 上无效，应使用 Meta+A |
| Bug-25 | P2 | planner | 备选方案的 target 未经 DOM 验证 |
| Bug-26 | P2 | scenario_gen | 不同功能点可能生成重复/高度相似场景 |
| Bug-27 | P3 | app | Streamlit use_column_width=True 已弃用 |
| Bug-28 | P3 | app | 测试执行可被 Streamlit rerun 中断 |
| Bug-29 | P3 | config | .env 中含真实 API Key，项目非 git 仓库无 .gitignore 保护 |
| 不足-A | 架构 | 全局 | 无变异测试能力（作业要求的加分项） |
| 不足-B | 架构 | 全局 | 报告仅 JSON，无可视化 HTML 报告 |
| 不足-C | 架构 | 全局 | 无并发执行能力，全量场景串行 |
| 不足-D | 架构 | executor | 无自动重试/自愈机制（区别于 planner 备选） |

---
## 二、四人分工方案

### 成员 A —— 场景生成质量（Prompt 工程 + DOM 快照注入）

负责 Bug： 9、13、16、1、14、26、6

#### Bug-9 / Bug-13：~70% CSS selector 虚构 + Prompt 缺真实 DOM 参考

**根因：** SCENARIO_PROMPT 中没有提供任何真实页面 DOM 信息，LLM 完全靠猜测生成 CSS selector（如
[data-testid='create-project']），但 4ga Boards 实际不使用 data-testid。

**详细解决步骤：**

1. 抓取真实 DOM 快照并缓存

在 task1_rag/ 下新建 dom_snapshot.py：

```python
"""抓取 4ga Boards 关键页面的真实 DOM 元素快照"""
import json
from playwright.sync_api import sync_playwright

PAGES_TO_SNAPSHOT = [
    {"name": "login", "url": "https://demo.4gaboards.com", "need_login": False},
    {"name": "dashboard", "url": "https://demo.4gaboards.com", "need_login": True},
    # 登录后进入第一个项目的看板页
    {"name": "board", "url": "__first_project__", "need_login": True},
]

def snapshot_page(page) -> dict:
    """提取页面中所有可交互元素的关键属性"""
    elements = page.evaluate("""() => {
```
        const els = document.querySelectorAll(
```python
            'button, a, input, textarea, select, [role="button"], [role="menuitem"], [role="tab"]'
        );
        return Array.from(els).slice(0, 80).map(el => ({
```
            tag: el.tagName.toLowerCase(),
            type: el.type || '',
            name: el.name || '',
            placeholder: el.placeholder || '',
            text: el.textContent?.trim().slice(0, 50) || '',
            aria_label: el.getAttribute('aria-label') || '',
            classes: Array.from(el.classList).join(' '),
            id: el.id || '',
        }));
    }""")
```python
    return {
        "url": page.url,
        "title": page.title(),
        "elements": elements,
    }

def build_snapshot_cache(output_path="data/dom_snapshots.json"):
    """启动浏览器，遍历关键页面，保存快照"""
    snapshots = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        for item in PAGES_TO_SNAPSHOT:
            if item["need_login"]:
                # 先登录
                page.goto("https://demo.4gaboards.com")
                page.fill('input[name="emailOrUsername"]', "demo@demo.demo")
                page.fill('input[type="password"]', "demo")
                page.click('button[type="submit"]')
                page.wait_for_timeout(3000)

            url = item["url"]
            if url == "__first_project__":
                # 点第一个项目进入看板
                page.locator(".project-wrapper >> nth=0").click()
                page.wait_for_timeout(2000)
            else:
                page.goto(url)
                page.wait_for_timeout(2000)
```

            snapshots[item["name"]] = snapshot_page(page)

```python
        browser.close()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)
    return snapshots
```

2. 将 DOM 快照注入 SCENARIO_PROMPT

```python
修改 task1_rag/scenario_gen.py，在 SCENARIO_PROMPT 中增加一个 {dom_reference} 占位符：

# 在 SCENARIO_PROMPT 中添加：
"""
```
## 真实页面 DOM 参考（以下元素已通过自动化抓取确认存在）
{dom_reference}

## ⚠️  严格要求
- target 字段**只能**使用上方 DOM 参考中**确实存在**的元素属性
- 禁止编造 data-testid、class 名或不存在的 id
"""

在 generate_scenarios() 方法中加载并注入：

```python
def generate_scenarios(self, feature: Feature) -> list[TestScenario]:
    # 加载 DOM 快照
    dom_ref = self._get_dom_reference(feature.category)

    # ... 原有 context 构造 ...

    raw = parse_json(self._llm(
        SCENARIO_PROMPT.format(
            # ... 原有字段 ...
            dom_reference=dom_ref,
```
        ),
```python
        max_tokens=4096,
```
    ))

3. 根据功能分类选择对应的 DOM 快照

```python
def _get_dom_reference(self, category: str) -> str:
    """根据功能分类返回相关页面的 DOM 元素摘要"""
    try:
        with open("data/dom_snapshots.json", "r") as f:
            snapshots = json.load(f)
    except FileNotFoundError:
        return "（DOM 快照未生成，请先运行 dom_snapshot.py）"

    # 分类 → 页面映射
    category_page_map = {
        "用户管理": ["login"],
        "项目管理": ["dashboard"],
        "看板操作": ["dashboard", "board"],
        "列表管理": ["board"],
        "卡片管理": ["board"],
        "设置": ["dashboard", "board"],
    }
    pages = category_page_map.get(category, ["dashboard", "board"])
    lines = []
    for page_name in pages:
        snap = snapshots.get(page_name, {})
        lines.append(f"### {page_name} 页面 (URL: {snap.get('url', '?')})")
        for el in snap.get("elements", [])[:30]:
            attrs = []
            if el.get("name"): attrs.append(f'name="{el["name"]}"')
            if el.get("placeholder"): attrs.append(f'placeholder="{el["placeholder"]}"')
            if el.get("text"): attrs.append(f'text="{el["text"]}"')
            if el.get("aria_label"): attrs.append(f'aria-label="{el["aria_label"]}"')
            if el.get("id"): attrs.append(f'id="{el["id"]}"')
            lines.append(f"  - <{el['tag']}> {' '.join(attrs)}")
    return "\n".join(lines)
```

#### Bug-1：测试预期不贴合真实应用

**根因：** LLM 猜测登录后跳转到 /dashboard，实际 4ga Boards 登录后 URL 为 /。

**详细解决步骤：**

1. 在 SCENARIO_PROMPT 中增加「已知页面 URL 映射」：

```python
# 在 SCENARIO_PROMPT 中添加：
"""
```
## 已知 URL 映射（登录后实际跳转路径）
- 登录成功后：URL 为 `/`（不是 /dashboard）
- 项目详情页：`/projects/{slug}`
- 看板页：`/boards/{id}`
- 设置页：无独立 URL，通过弹窗打开
"""

2. 后处理校验：在 generate_scenarios() 返回前检查 expectations：

```python
def _fix_expectations(self, scenarios: list[TestScenario]) -> list[TestScenario]:
    KNOWN_FIXES = {
        "/dashboard": "/",
        "/home": "/",
```
        "/register": "/",  # 4ga 注册通过登录页切换
```python
    }
    for s in scenarios:
        for exp in s.expectations:
            if exp.condition == "url_contains":
                for wrong, right in KNOWN_FIXES.items():
                    if exp.value == wrong:
                        exp.value = right
    return scenarios
```

#### Bug-16：expectations 使用不存在的 CSS selector

**解决方案：** 同 Bug-9，DOM 快照注入后，在 SCENARIO_PROMPT 中明确要求 expectations 的 target 也必须基于真实
DOM。同时在后处理中校验：

```python
def _validate_expectations(self, scenario: TestScenario, snapshots: dict) -> TestScenario:
    """校验 expectations 中的 target 是否在 DOM 快照中存在"""
    all_texts = set()
    for snap in snapshots.values():
        for el in snap.get("elements", []):
            if el.get("text"): all_texts.add(el["text"].lower())

    for exp in scenario.expectations:
        if exp.condition == "visible" and exp.target:
            # 如果 target 像纯文本且不在快照中，标记警告
            if not any(c in exp.target for c in "[].#>:"):
                if exp.target.lower() not in all_texts:
```
                    exp.description += "（⚠️  该文本未在 DOM 快照中找到）"
    return scenario

#### Bug-14：功能点数量不稳定

**解决方案：** 收紧 FEATURE_PROMPT 约束：

```python
# 修改 FEATURE_PROMPT 中的约束：
"""
```
## 关键约束
1. 功能点总数必须在 **23-28 个**之间（不是 20-30）
2. 每个分类 3-6 个，卡片管理不超过 7 个
3. 富文本编辑器只算 1 个功能点
"""

#### Bug-26：跨功能点的重复场景

**解决方案：** 在 run() 方法的最后增加去重步骤：

```python
def _dedup_scenarios(self, scenarios: list[TestScenario]) -> list[TestScenario]:
    """基于场景名称相似度去重"""
    seen_names = set()
    result = []
    for s in scenarios:
        # 简单去重：名称完全相同则跳过
        if s.name in seen_names:
```
            continue
```python
        seen_names.add(s.name)
        result.append(s)
    return result
```

#### Bug-6：部分步骤不可执行（如注册页不存在）

**解决方案：** 在 SCENARIO_PROMPT 中明确声明应用的限制：

"""
## 应用限制（必须遵守）
- 4ga Boards 演示站**没有公开注册页**，不要生成注册相关场景
- 修改密码功能在用户设置弹窗中，不是独立页面
- 删除项目需要在项目设置中操作，不能直接在 dashboard 删除
"""

---
### 成员 B —— RAG 引擎 + JSON 鲁棒性（基于成员 A 完成版的补强）

负责 Bug： 2、15、8、11、7、12、3  
状态说明：Bug-10「场景生成返回 0 结果时无重试」已在成员 A 版本中基本完成，B 不再重复实现，只做验收和数量兜底。当前 B 的重点是让 RAG 和 JSON 解析更稳，避免 A 已经修好的 DOM 约束因为破损 JSON 或错误召回被拖垮。

**基于 A 完成版的新增验收基线：**

- `data/test_scenarios.json` 当前为 25 个功能点、54 个场景，已达到原样例规模。
- 生成结果中不应再出现 `data-testid`、`/dashboard`、`/register`、中文 target、空 `url_contains` 等旧问题。
- B 的修复不能破坏 A 已完成的 DOM 快照注入、URL 修正、场景去重和上传场景修正。
- 依赖变更需要同步写入 `requirements.txt`，不能只写 `pip install`。

#### Bug-8：chunk_text() 死循环

**根因：** 当 overlap >= chunk_size 时，步长 chunk_size - overlap <= 0，start 永远不前进。

**详细解决步骤：**

修改 task1_rag/rag_engine.py 中的 chunk_text 函数：

```python
def chunk_text(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    if not text or not text.strip():
        return []
    if len(text) <= chunk_size:
        return [text]

    # 防御：确保 overlap < chunk_size，否则死循环
    overlap = min(overlap, chunk_size - 1)
    step = chunk_size - overlap
    assert step > 0, f"step must be positive, got chunk_size={chunk_size}, overlap={overlap}"

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += step
    return chunks
```

**验证：** 运行以下测试确认修复：

```python
# 之前会死循环的用例
result = chunk_text('a' * 1000, chunk_size=100, overlap=100)
assert len(result) > 0 and len(result) < 100

result = chunk_text('a' * 1000, chunk_size=100, overlap=200)
assert len(result) > 0
```

#### Bug-2 / Bug-15：DeepSeek 输出破损 JSON + parse_json 截断修复不可靠

**根因：**
- DeepSeek 在生成长 JSON 时经常输出未闭合的字符串
- parse_json 的截断修复只找最后一个 }，对嵌套结构失效

**详细解决步骤：**

1. 增加 JSON 修复库 `json-repair`，并同步写入依赖文件

```python
# requirements.txt 增加：
json-repair>=0.30.0
```

2. 重写 parse_json 函数：

```python
def parse_json(text: str) -> list:
    """从 LLM 返回文本中安全提取 JSON 数组，带多级修复"""
    if not text or not text.strip():
        console.print("[red]LLM 返回为空[/red]")
        return []

    raw = text

    # 第 1 级：提取 markdown json 代码块
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > 0:
            text = text[start:end]

    # 第 2 级：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 第 3 级：用 json_repair 库修复
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

    # 第 4 级：手动截断修复（逐级尝试去掉尾部不完整对象）
    # 从后往前找每个 }，尝试截断并补 ]
    for i in range(len(text) - 1, 0, -1):
        if text[i] == '}':
            candidate = text[:i+1].rstrip().rstrip(",") + "\n]"
            try:
                result = json.loads(candidate)
                console.print(f"[yellow]截断修复成功，恢复 {len(result)} 项[/yellow]")
                return result
            except json.JSONDecodeError:
                continue

    console.print(f"[red]JSON 解析彻底失败[/red]")
    console.print(f"[dim]原始返回前 500 字: {raw[:500]}[/dim]")
    return []
```

3. 增加回归测试用例，覆盖 A 版本最容易受影响的场景生成链路：

```python
def test_parse_json_repairs_truncated_array():
    raw = '[{"id":"f001","name":"登录"},{"id":"f002","name":"创建项目"'
    result = parse_json(raw)
    assert isinstance(result, list)
    assert result

def test_parse_json_extracts_markdown_block():
    fence = "`" * 3
    raw = "说明文字\n" + fence + 'json\n[{"id":"f001","name":"登录"}]\n' + fence
    assert parse_json(raw)[0]["id"] == "f001"
```

#### Bug-10：场景生成返回 0 结果时无重试（A 已基本完成，B 做验收）

**当前状态：** 成员 A 版本中的 `generate_scenarios(feature, max_retries=2)` 已经包含空结果重试逻辑，因此 B 不再重复改同一段代码。

**B 的验收与补充步骤：**

1. 确认 `task1_rag/scenario_gen.py` 中 `generate_scenarios()` 仍保留 `max_retries` 参数。
2. 用一个 mock LLM 测试「第一次返回空数组、第二次返回有效场景」时能正常恢复。
3. 保留总量兜底：如果最终场景数低于 45，输出明确告警并重新生成空场景功能点；不要覆盖 A 已生成的有效场景。

```python
if len(all_scenarios) < 45:
    console.print(f"[yellow]场景总数仅 {len(all_scenarios)}，低于 A 版本基线 54，开始补充空场景功能点[/yellow]")
    for feature in features:
        if not feature.scenarios:
            retried = self.generate_scenarios(feature, max_retries=3)
            feature.scenarios = retried
            all_scenarios.extend(retried)
```

#### Bug-11：RAG 去重逻辑问题

**根因：** extract_features 中的去重用的是完整格式化字符串（含标题等），相同 chunk
在不同查询中会因为拼接方式不同被认为是"不同"的。

**详细解决步骤：**

1. 在 `task1_rag/rag_engine.py` 中暴露原始检索接口，复用现有 `retrieve()`，不要新增旧版 `self.index/self.chunks` 写法：

```python
def search(self, query: str, top_k: int = 5) -> list[tuple[str, float, dict]]:
    """返回原始 chunk，供上层做 chunk 级去重。"""
    results = self.retrieve(query, top_k=top_k)
    return [
        (
            item.get("text", ""),
            float(item.get("score", 0.0)),
            {
                "source_title": item.get("source_title", ""),
                "source_url": item.get("source_url", ""),
                "category": item.get("category", ""),
            },
        )
        for item in results
    ]
```

2. 修改 `task1_rag/scenario_gen.py` 的 `extract_features()`，用 chunk 文本 hash 去重，而不是用 `get_context()` 拼接后的完整字符串去重：

```python
queries = [
    "create project board list card",
    "delete remove board list card project",
    "import board trello 4ga",
    "member label due date checklist attachment comment",
    "settings password notification theme sidebar",
]
seen_chunks = set()
parts = []
for q in queries:
    for chunk_text, score, meta in self.rag.search(q, top_k=4):
        normalized = " ".join(chunk_text.split())
        chunk_hash = hash(normalized)
        if chunk_hash in seen_chunks:
            continue
        seen_chunks.add(chunk_hash)
        title = meta.get("source_title", "")
        parts.append(f"[来源: {title}]\n{chunk_text}")

context = "\n\n---\n\n".join(parts)
```

3. 验收标准：

- 同一个文档片段在多条 query 中命中时，`context` 中只出现一次。
- `extract_features()` 仍能稳定生成 23-28 个功能点。
- 生成后的 `data/test_scenarios.json` 仍保持 A 版本基线：不少于 25 个功能点、50 个场景。

#### Bug-7：RAG 检索质量差

**详细解决步骤：**

1. 提高 chunk 质量：优先按 Markdown 标题分块，超长 section 再回退到 `chunk_text()`，保证语义完整且不会丢失 overlap 防护：

```python
def chunk_by_sections(text: str, max_chunk_size: int = 800, overlap: int = 80) -> list[str]:
    """按 markdown 标题分块，保留语义完整性"""
    import re
    sections = re.split(r'\n(?=#{1,3}\s)', text)
    chunks = []
    current = ""
    for section in sections:
        if len(current) + len(section) > max_chunk_size and current:
            chunks.append(current.strip())
            current = section
        else:
            current += "\n" + section
    if current.strip():
        chunks.append(current.strip())

    final_chunks = []
    for chunk in chunks:
        if len(chunk) > max_chunk_size:
            final_chunks.extend(chunk_text(chunk, max_chunk_size, overlap))
        else:
            final_chunks.append(chunk)
    return final_chunks
```

2. 在 `build_index()` 中替换分块入口：

```python
for chunk in chunk_by_sections(full_text, self.chunk_size, self.chunk_overlap):
    if len(chunk.strip()) > 30:
        self._chunks.append({...})
```

3. 查询扩展：中英文双语检索，并按 Qdrant/FAISS 的余弦分数从高到低排序（当前索引使用 normalize embeddings + cosine/IP，分数越高越相关）：

```python
def get_context(self, query: str, top_k: int = 5) -> str:
    # 中文查询 + 英文翻译查询，合并结果
    cn_results = self.search(query, top_k=top_k)
    # 简单关键词映射
    EN_MAP = {"创建": "create", "项目": "project", "看板": "board",
              "卡片": "card", "删除": "delete", "列表": "list"}
    en_query = query
    for cn, en in EN_MAP.items():
        en_query = en_query.replace(cn, en)
    en_results = self.search(en_query, top_k=top_k)

    # 合并去重
    seen = set()
    merged = []
    for text, score in cn_results + en_results:
        h = hash(text.strip())
        if h not in seen:
            seen.add(h)
            merged.append((text, score))
    merged.sort(key=lambda x: x[1], reverse=True)
    return "\n\n".join(text for text, _ in merged[:top_k])
```

4. 加一个小型检索验收脚本：

```python
checks = {
    "如何创建卡片": ["card", "卡片", "Add card"],
    "导入 Trello 看板": ["Trello", "import", "board"],
    "修改通知偏好": ["notification", "通知", "settings"],
}
for query, keywords in checks.items():
    ctx = rag.get_context(query, top_k=3).lower()
    assert any(k.lower() in ctx for k in keywords), query
```

#### Bug-12：embedding 模型对中文支持差

**解决方案：** 不建议直接切到纯中文模型，因为 4ga Boards 的页面 DOM、按钮文案和文档关键词大量是英文。更稳妥的方案是使用中英双语模型，并保留现有模型作为低成本 fallback：

```python
# config.py 中修改
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
# 如果本机下载较慢或内存不足，可临时退回：
# EMBEDDING_MODEL = "all-MiniLM-L6-v2"
```

**注意：** 更换 embedding 模型后必须删除或重建 `data/vector_store`，否则旧向量维度和新模型维度不一致。

#### Bug-3：生成结果数量不稳定

**解决方案：** A 版本已经达到 25 个功能点、54 个场景；B 这里改为「数量守护」而不是继续盲目扩张。标准是：功能点 23-28 个、场景不少于 50 个，低于阈值才触发补充生成。

```python
# 在 run() 最后、保存之前
if len(features) < 23 or len(all_scenarios) < 50:
    console.print(f"[yellow]功能点/场景数量低于 A 版本验收线："
                  f"{len(features)} features, {len(all_scenarios)} scenarios，"
                  f"尝试对空场景功能点重新生成...[/yellow]")
    for feature in features:
        if not feature.scenarios:
            retried = self.generate_scenarios(feature, max_retries=3)
            feature.scenarios = retried
            all_scenarios.extend(retried)
```

**验收命令：**

```python
import json
features = json.load(open("data/features.json", encoding="utf-8"))
scenarios = json.load(open("data/test_scenarios.json", encoding="utf-8"))
assert 23 <= len(features) <= 28
assert len(scenarios) >= 50
assert not any("data-testid" in json.dumps(s, ensure_ascii=False) for s in scenarios)
```

---
### 成员 C —— 执行引擎性能与可靠性（含备选步骤审计）

负责 Bug： 18、19、24、21、17、25、20、不足-D

**基于 A 完成版的新增观察：**

- A 验收报告 `reports/test_report_20260528_194815.json` 中，5 个冒烟场景最终全部 PASS，但 `f013_s02` 曾出现原始步骤失败，随后由 planner 备选方案恢复。
- 当前 `agent.py` 在备选方案成功后会把 `mem.actions[-1].success = True`，导致原始失败步骤被抹平，报告看起来像从未失败过。这个问题会影响验收可信度，因此 C 组优先处理 Bug-17 和 Bug-25。
- A 已经修过上传动作：`executor.set_input_files()` 支持 file input 和 file chooser，`resolver.py` 对上传步骤会跳过解析。C 不再重复处理上传执行问题，只负责通用执行可靠性。

#### Bug-17：备选步骤成功时覆盖原 action 记录（优先处理）

**根因：** `agent.py` 备选方案成功后执行 `mem.actions[-1].success = True`，把原始失败记录改成成功，丢失原始失败原因、原始 target 和真实恢复路径。

**详细解决步骤：**

1. 修改 `task2_agent/memory.py`，允许备选步骤使用 `"6b"` 这样的编号：

```python
@dataclass
class ActionRecord:
    step_index: int | str
    action: str
    target: str
    value: str
    description: str
    success: bool
    screenshot_path: str = ""
    page_url: str = ""
    page_title: str = ""
    error_msg: str = ""
```

2. 修改 `task2_agent/agent.py`，备选方案成功时追加一条新记录，不再改写上一条失败记录：

```python
if alt_ok:
    mem.log(f"备选方案成功: {alt.get('description', '')}")
    alt_record = ActionRecord(
        step_index=f"{i + 1}b",
        action=alt.get("action", ""),
        target=alt.get("target", ""),
        value=alt.get("value", ""),
        description=f"[备选] {alt.get('description', '')}",
        success=True,
        screenshot_path=alt_ss,
        page_url=self.executor.get_url(),
        page_title=self.executor.get_title(),
        error_msg="",
    )
    mem.add_action(alt_record)
    executed_steps.append({**alt, "_alternative_for": i + 1})
    success = True
```

3. 结果报告中保留恢复痕迹：

```python
result["recovered_steps"] = [
    a for a in mem.to_dict()["actions"]
    if str(a.get("step_index", "")).endswith("b") and a.get("success")
]
```

**验收标准：**

- `f013_s02` 这类场景如果发生备选恢复，报告中应同时看到原始失败步骤和 `6b` 成功步骤。
- 场景最终可以 PASS，但不能把原始失败改写为成功。

#### Bug-18：_find() 最坏 22 秒

**根因：** _find() 依次尝试约 15 种定位策略，每种设置 800-1500ms 超时，全部失败则累计超过 20 秒。

**详细解决步骤：**

1. 保留现有「弹窗优先」逻辑，但改成分层策略：快速层（150-250ms）+ 慢速层（500-800ms）+ 总 deadline。不要为了提速删掉 dialog scope，否则 `Add Project` 这类同名按钮容易点错。

```python
def _find(self, selector: str, timeout: int | None = None):
    """
    分层定位策略：
    - 有弹窗时优先在弹窗内找
    - 精确 CSS / role / text 先快速尝试
    - 模糊文本和兜底 selector 放到慢速层
    - 全函数受 deadline 控制
    """
    import time
    t = timeout or min(self.timeout, 3000)
    deadline = time.time() + t / 1000
    page = self._page

    looks_like_css = any(c in selector for c in "[].#>:") or selector.startswith(
        ("input", "button", "div", "span", "a[", "form")
    )
    scope = self._visible_dialog_or_page()

    fast_strategies = []
    if looks_like_css:
        fast_strategies.append(lambda: scope.wait_for_selector(selector, timeout=250))
    fast_strategies.extend([
        lambda: scope.get_by_role("button", name=selector, exact=True).first.element_handle(timeout=250),
        lambda: scope.get_by_role("link", name=selector, exact=True).first.element_handle(timeout=250),
        lambda: scope.get_by_placeholder(selector, exact=True).first.element_handle(timeout=250),
    ])

    slow_strategies = [
        lambda: scope.get_by_role("button", name=selector).first.element_handle(timeout=600),
        lambda: scope.get_by_role("link", name=selector).first.element_handle(timeout=600),
        lambda: scope.locator(f"button:has-text('{selector}')").first.element_handle(timeout=600),
        lambda: scope.locator(f"a:has-text('{selector}')").first.element_handle(timeout=600),
        lambda: scope.get_by_text(selector, exact=False).first.element_handle(timeout=800),
    ]

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

def _visible_dialog_or_page(self):
    dialog_sel = "[role='dialog'], [role='alertdialog'], dialog, [class*='Modal' i], [class*='Dialog' i]"
    try:
        dialogs = self._page.locator(dialog_sel)
        for i in range(min(dialogs.count(), 5)):
            dialog = dialogs.nth(i)
            if dialog.is_visible(timeout=150):
                return dialog
    except Exception:
        pass
    return self._page
```

2. 增加性能验收，防止失败 target 拖垮全量执行：

```python
import time
start = time.perf_counter()
assert executor._find("definitely_not_exists_xyz", timeout=3000) is None
assert time.perf_counter() - start < 4.0
```

#### Bug-19：每次 click 后 networkidle 等待 3 秒

**详细解决步骤：**

```python
# 修改 executor.py 中的 click 处理
def _click_and_wait(self, element, timeout=1500):
    """点击后智能等待：优先用 domcontentloaded，只在必要时等 networkidle"""
    element.scroll_into_view_if_needed()
    element.click()
    try:
        # 先等 DOM 就绪（通常 <500ms）
        self._page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass
    # 额外等 300ms 让 JS 渲染完成（比 networkidle 的 3s 快很多）
    self._page.wait_for_timeout(300)
```

将普通 `click()` 中的 `networkidle` 替换为 `_click_and_wait()`；`_wait_dashboard_ready()` 可以保留一个较短的兜底等待，但不应每次点击都等 `networkidle`。

#### Bug-24：macOS 上 Control+A 无效

**详细解决步骤：**

```python
import platform

def _shortcut(self, key: str) -> str:
    """返回当前平台快捷键，例如 Meta+a / Control+a。"""
    normalized = key.lower()
    if platform.system() == "Darwin":
        return f"Meta+{normalized}"
    return f"Control+{normalized}"

# 使用处（executor.py 中所有 Control+A 出现的地方）
# 原代码：
#   page.keyboard.press("Control+A")
# 改为：
#   page.keyboard.press(self._shortcut("a"))
```

全局搜索并替换所有 Control+A、Control+a：

```python
grep -rn "Control+[aA]" task2_agent/executor.py
# 将每处替换为 self._shortcut("a")
```

同理处理 Control+C、Control+V 等快捷键。

#### Bug-21：异常时截图可能二次报错

**详细解决步骤：**

```python
def screenshot(self, name: str) -> str:
    """安全截图：浏览器已关闭时不抛异常"""
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
```

#### Bug-25：备选方案 target 未经 DOM 验证

**详细解决步骤：**

在 `agent.py` 中，对 planner 返回的备选方案也走 resolver。注意上传动作已经由 A 处理为 resolver 跳过，不需要 C 额外改：

```python
# 在 agent.py 的备选方案处理中
if actionable:
    alt = actionable[0]
    if self.resolver and alt.get("action", "").lower() not in {"setinputfiles", "set_input_files", "upload", "upload_file"}:
        try:
            alt = self.resolver.resolve(self.executor, alt)
        except Exception:
            console.print("[yellow]备选方案 Resolver 调用失败，使用原始备选步骤[/yellow]")
            pass
    alt_ok, alt_ss, alt_err = self._run_one_step(alt, f"{i+1}b")
else:
    mem.log("Planner 未返回可执行备选方案")
```

**验收标准：**

- planner 返回的按钮文本如果和当前 DOM 不一致，应先经 resolver 修正再执行。
- 如果 resolver 异常，保留原始备选方案继续尝试，但日志中要记录。

#### Bug-20：login_state 跨场景持久化但浏览器重启

**详细解决步骤：**

在 agent.py 的 run_scenario() 开头重置登录状态：

```python
def run_scenario(self, scenario: dict) -> dict:
    # 每个场景开始时重置登录状态（因为浏览器会重启）
    self.memory.set_login_state(logged_in=False, username="", current_project="", current_board="")

    sid = scenario.get("id", "unknown")
    # ... 其余不变
```

**补充说明：** 这里重置的是跨场景记忆，不影响 `Planner.prepare_steps()` 给每个场景自动补登录步骤。浏览器每个场景都会重新启动，所以不能沿用上一个场景的 `logged_in=True`。

#### 不足-D：无自动重试/自愈机制

**详细解决步骤：**

在 `executor.py` 中为关键操作增加轻量重试。重试只包裹易受短暂渲染影响的动作（click/input/upload），不要包裹整个场景，避免把真实失败拖成超长等待：

```python
import functools
import time

def retry(max_attempts=2, delay=0.5):
    """执行步骤重试装饰器"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        time.sleep(delay)
                        console.print(f"[yellow]第 {attempt+1} 次尝试失败，重试...[/yellow]")
            raise last_error
        return wrapper
    return decorator

@retry(max_attempts=2, delay=0.5)
def _do_click(self, selector: str) -> bool:
    el = self._find(selector)
    if not el:
        return False
    self._click_and_wait(el)
    return True
```

**验收标准：**

- 单步失败时最多重试 1 次，总耗时仍受 `_find()` deadline 控制。
- 重试日志要写明第几次重试，方便报告定位不稳定步骤。
- 对断言类步骤不要重试太多，否则会掩盖真实产品缺陷。

---
### 成员 D —— 验证系统 + 报告展示 + 加分能力

负责 Bug： 22、23、27、28、不足-A、不足-B、不足-C

**基于 A 完成版的新增定位：**

- 当前已经有可用的 JSON 执行报告，例如 `reports/test_report_20260528_194815.json` 和 `reports/test_report_20260528_195236.json`。
- D 的重点不再是“有没有报告”，而是让报告更容易验收：明确展示规则验证、LLM 验证、备选步骤恢复、截图和失败原因。
- C 会保留备选步骤恢复记录；D 的报告需要把 `recovered_steps` 展示出来，不能只显示最终 PASS/FAIL。
- `f012_s01` Trello 导入未复测的原因是缺少 `test_data/trello_export.json`，D 的报告里应能标记为“测试数据缺失/未执行”，而不是混成产品失败。

#### Bug-22：LLM 不可用时降级阈值硬编码 0.7

**详细解决步骤：**

```python
# verifier.py 修改
class Verifier:
    def __init__(
        self,
        api_key,
        model,
        base_url=DEFAULT_BASE_URL,
        fallback_threshold: float = 0.7,
    ):
        self.llm = LLMClient(api_key=api_key, model=model, base_url=base_url)
        self.model = model
        self.fallback_threshold = fallback_threshold

    def verify_with_llm(self, scenario, memory, inline_results=None):
        # ... 原有 LLM 调用逻辑 ...

        except Exception as e:
            rate = success / total if total > 0 else 0
            return {
                "result": "PASS" if rate >= self.fallback_threshold else "FAIL",
                "confidence": rate,
                "summary": f"LLM 验证不可用，按规则验证通过率 {rate:.0%} 降级判断",
                # ...
            }
```

在 config.py 中增加配置项：

```python
VERIFY_FALLBACK_THRESHOLD = float(os.getenv("VERIFY_FALLBACK_THRESHOLD", "0.7"))
```

在 `agent.py` 初始化 Verifier 时传入配置：

```python
from config import VERIFY_FALLBACK_THRESHOLD

self.verifier = Verifier(
    api_key,
    model,
    base_url=base_url,
    fallback_threshold=config.get("verify_fallback_threshold", VERIFY_FALLBACK_THRESHOLD),
)
```

#### Bug-23：仅当所有 inline_results 为 false 时才强制 FAIL

**详细解决步骤：**

修改 `agent.py` 中的强制降级逻辑：只要核心预期通过率过低，就不能让 LLM 单独把结果判成 PASS。

```python
if inline_results:
    total_exp = len(inline_results)
    passed_exp = sum(1 for r in inline_results if r.get("inline_pass"))
    pass_rate = passed_exp / total_exp if total_exp > 0 else 0

    if pass_rate == 0 and verify_result.get("result") == "PASS":
        verify_result["result"] = "FAIL"
        verify_result["summary"] = f"（强制降级）所有预期均未通过：" + verify_result.get("summary", "")
    elif pass_rate < 0.5 and verify_result.get("result") == "PASS":
        verify_result["result"] = "FAIL"
        verify_result["summary"] = (
            f"（强制降级）仅 {passed_exp}/{total_exp} 条规则预期通过："
            + verify_result.get("summary", "")
        )

    verify_result["inline_pass_rate"] = pass_rate
```

**补充要求：**

- 如果 C 组提供了 `recovered_steps`，最终 PASS 仍然可以成立，但报告必须展示“存在恢复步骤”。
- 如果失败原因是 fixture 缺失（例如 Trello 导入文件不存在），结果建议标为 `ERROR` 或 `BLOCKED`，不要记成产品功能 FAIL。

#### Bug-27：Streamlit 弃用 API

**详细解决步骤：**

全局搜索并替换：

```python
# app.py 中所有出现的地方
# 原：
st.image(img, use_column_width=True)
# 改为：
st.image(img, use_container_width=True)
```

#### Bug-28：执行可被 Streamlit rerun 中断

**详细解决步骤：**

使用 `st.session_state` 保存任务状态，把真正的测试执行放到后台线程里。注意：后台线程不要直接频繁调用 Streamlit UI API，只更新状态对象，由主线程负责渲染。

```python
import threading

def start_tests_in_background(agent, scenarios):
    """在子线程中运行测试，避免被 Streamlit rerun 中断"""
    if st.session_state.get("test_running"):
        return

    st.session_state["test_running"] = True
    st.session_state["test_cancelled"] = False
    st.session_state["test_results"] = []
    st.session_state["test_progress"] = 0.0

    def _run():
        try:
            for i, scenario in enumerate(scenarios):
                if st.session_state.get("test_cancelled"):
                    break
                result = agent.run_scenario(scenario)
                st.session_state["test_results"].append(result)
                st.session_state["test_progress"] = (i + 1) / len(scenarios)
        finally:
            st.session_state["test_running"] = False

    thread = threading.Thread(target=_run, daemon=True)
    st.session_state["test_thread"] = thread
    thread.start()
```

**界面侧配套：**

```python
if st.session_state.get("test_running"):
    st.progress(st.session_state.get("test_progress", 0.0))
    if st.button("停止执行"):
        st.session_state["test_cancelled"] = True
else:
    if st.button("开始执行"):
        start_tests_in_background(agent, selected_scenarios)
```

#### 不足-A：变异测试能力（加分项）

**设计方案：** 对已生成且原始结果 PASS 的测试场景施加变异，验证测试是否能捕获错误流程。变异体不应污染原始 `data/test_scenarios.json`，统一输出到 `data/mutants.json` 或内存执行。

新建 task2_agent/mutator.py：

```python
"""
变异测试模块：对测试场景施加变异操作，验证测试覆盖充分性
变异类型：
  1. 步骤删除：删除非前置步骤，预期应 FAIL
  2. 值变异：修改 input 的 value（如空值、超长值、特殊字符）
  3. 顺序变异：交换两个相邻步骤的顺序
  4. 目标变异：将 click target 替换为页面上其他按钮
"""
import copy
import random

class ScenarioMutator:
    # 变异类型
    MUTATION_TYPES = ["delete_step", "mutate_value", "swap_steps", "mutate_target"]

    def generate_mutants(self, scenario: dict, count: int = 3) -> list[dict]:
        """为一个场景生成 count 个变异体"""
        mutants = []
        tried = set()
        for _ in range(count):
            mutation_type = random.choice(self.MUTATION_TYPES)
            if mutation_type in tried:
                continue
            tried.add(mutation_type)
            mutant = self._apply_mutation(scenario, mutation_type)
            if mutant:
                mutant["_mutation_type"] = mutation_type
                mutant["_original_id"] = scenario.get("id", "")
                mutants.append(mutant)
        return mutants

    def _apply_mutation(self, scenario: dict, mutation_type: str) -> dict | None:
        mutant = copy.deepcopy(scenario)
        mutant["id"] = f"{scenario.get('id', '')}_mut_{mutation_type}"
        mutant["name"] = f"[变异-{mutation_type}] {scenario.get('name', '')}"
        steps = mutant.get("steps", [])

        if mutation_type == "delete_step" and len(steps) > 2:
            # 删除中间的一个非登录步骤
            candidates = [i for i, s in enumerate(steps)
                         if s.get("action") not in ("login", "navigate")]
            if candidates:
                idx = random.choice(candidates)
                steps.pop(idx)

        elif mutation_type == "mutate_value":
            # 找到一个 input 步骤，修改其 value
            input_steps = [s for s in steps if s.get("action") == "input"]
            if input_steps:
                step = random.choice(input_steps)
                original = step.get("value", "")
                mutations = ["", "x" * 200, "<script>alert(1)</script>",
                             "'; DROP TABLE users; --", "Invalid Value"]
                step["value"] = random.choice(mutations)
                step["_original_value"] = original

        elif mutation_type == "swap_steps" and len(steps) > 3:
            # 交换两个相邻的非前置步骤
            candidates = list(range(1, len(steps) - 1))
            if candidates:
                idx = random.choice(candidates)
                steps[idx], steps[idx+1] = steps[idx+1], steps[idx]

        elif mutation_type == "mutate_target":
            click_steps = [s for s in steps if s.get("action") == "click"]
            if click_steps:
                step = random.choice(click_steps)
                step["_original_target"] = step["target"]
                step["target"] = "nonexistent_button_xyz"

        else:
            return None

        return mutant

    def evaluate_mutation_score(self, original_result: dict,
                                 mutant_results: list[dict]) -> dict:
        """
        计算变异得分：
        如果原始 PASS 而变异体也 PASS → 测试不够充分（变异存活）
        如果原始 PASS 而变异体 FAIL → 变异被杀死（好）
        """
        killed = sum(1 for r in mutant_results
                    if r.get("result") == "FAIL")
        total = len(mutant_results)
        score = killed / total if total > 0 else 0

        return {
            "original_id": original_result.get("scenario_id", ""),
            "total_mutants": total,
            "killed": killed,
            "survived": total - killed,
            "mutation_score": score,
            "details": [
                {
                    "mutant_id": r.get("scenario_id", ""),
                    "mutation_type": r.get("_mutation_type", ""),
                    "result": r.get("result", ""),
                    "killed": r.get("result") == "FAIL",
                }
                for r in mutant_results
            ],
        }
```

**执行入口建议：**

```python
def run_mutation_tests(agent, scenarios, mutants_per_scenario=2):
    mutator = ScenarioMutator()
    mutation_reports = []
    for scenario in scenarios:
        original = agent.run_scenario(scenario)
        if original.get("result") != "PASS":
            continue
        mutants = mutator.generate_mutants(scenario, count=mutants_per_scenario)
        mutant_results = []
        for mutant in mutants:
            result = agent.run_scenario(mutant)
            result["_mutation_type"] = mutant.get("_mutation_type")
            mutant_results.append(result)
        mutation_reports.append(mutator.evaluate_mutation_score(original, mutant_results))
    return mutation_reports
```

**验收标准：**

- 只对原始 PASS 场景计算 mutation score。
- 变异体 PASS 要标为 survived，用于提示测试预期不够强。
- HTML 报告中增加 mutation score 汇总。

#### 不足-B：HTML 可视化报告

新建 `reports/report_generator.py`。报告必须对 HTML 内容做转义，否则变异测试里的 `<script>`、错误日志里的尖括号等内容会污染报告页面。

```python
"""生成 HTML 格式的测试报告"""
from datetime import datetime
from html import escape
from pathlib import Path

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>4GA Boards 测试报告</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; background: #f6f7f9; color: #202124; }}
  .header {{ background: #174ea6; color: white; padding: 20px; border-radius: 8px; }}
  .summary {{ display: grid; grid-template-columns: repeat(5, minmax(110px, 1fr)); gap: 12px; margin: 18px 0; }}
  .stat-card {{ background: white; padding: 16px; border-radius: 8px; border: 1px solid #e0e3e7; text-align: center; }}
  .stat-card .number {{ font-size: 30px; font-weight: 700; }}
  .pass {{ color: #34a853; }}
  .fail {{ color: #ea4335; }}
  .error {{ color: #f29900; }}
  .scenario {{ background: white; margin: 12px 0; padding: 14px; border-radius: 8px; border-left: 4px solid #9aa0a6; }}
  .scenario.pass {{ border-left-color: #34a853; }}
  .scenario.fail {{ border-left-color: #ea4335; }}
  .scenario.error {{ border-left-color: #f29900; }}
  .steps {{ margin: 10px 0; font-size: 13px; line-height: 1.55; }}
  .step.ok {{ color: #34a853; }}
  .step.err {{ color: #ea4335; }}
  .recovered {{ background: #fff8e1; border: 1px solid #f6d365; padding: 8px; border-radius: 6px; margin: 8px 0; }}
  .screenshot {{ max-width: 360px; margin: 6px; border: 1px solid #ddd; border-radius: 4px; }}
</style>
</head>
<body>
<div class="header">
  <h1>4GA Boards 自动化测试报告</h1>
  <p>生成时间: {timestamp}</p>
</div>
<div class="summary">
  <div class="stat-card"><div class="number">{total}</div>总场景</div>
  <div class="stat-card"><div class="number pass">{passed}</div>通过</div>
  <div class="stat-card"><div class="number fail">{failed}</div>失败</div>
  <div class="stat-card"><div class="number error">{errors}</div>异常/阻塞</div>
  <div class="stat-card"><div class="number">{pass_rate}</div>通过率</div>
</div>
<h2>场景详情</h2>
{scenario_details}
</body>
</html>"""

def _status(result: str) -> str:
    if result == "PASS":
        return "pass"
    if result in {"ERROR", "BLOCKED"}:
        return "error"
    return "fail"

def generate_html_report(
    results: list[dict],
    output_path: str = "reports/report.html",
    mutation_reports: list[dict] | None = None,
):
    total = len(results)
    passed = sum(1 for r in results if r.get("result") == "PASS")
    errors = sum(1 for r in results if r.get("result") in {"ERROR", "BLOCKED"})
    failed = total - passed - errors
    rate = f"{passed / total * 100:.1f}%" if total else "0%"

    details = []
    for r in results:
        status = _status(r.get("result", ""))
        steps_html = ""
        for log in r.get("logs", []):
            cls = "ok" if "✓" in log else ("err" if "✗" in log or "失败" in log else "")
            steps_html += f'<div class="step {cls}">{escape(str(log))}</div>'

        recovered_html = ""
        recovered = r.get("recovered_steps", [])
        if recovered:
            labels = ", ".join(str(x.get("step_index", "")) for x in recovered)
            recovered_html = f"<div class='recovered'>备选恢复步骤：{escape(labels)}</div>"

        screenshots = r.get("screenshots", []) or [
            a.get("screenshot_path") for a in r.get("actions", []) if a.get("screenshot_path")
        ]
        screenshots_html = ""
        for ss in screenshots[:3]:
            if ss and Path(ss).exists():
                screenshots_html += f'<img class="screenshot" src="{escape(str(ss))}">'

        details.append(f"""
        <div class="scenario {status}">
            <h3>{escape(r.get('scenario_name', ''))} - <span class="{status}">{escape(r.get('result', '?'))}</span></h3>
            <p>{escape(r.get('summary', ''))}</p>
            {recovered_html}
            <div class="steps">{steps_html}</div>
            {screenshots_html}
        </div>""")

    html = HTML_TEMPLATE.format(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total=total,
        passed=passed,
        failed=failed,
        errors=errors,
        pass_rate=rate,
        scenario_details="\n".join(details),
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path
```

**接入位置：**

- `TestAgent.run_scenarios()` 生成 JSON 后调用 `generate_html_report(results)`。
- Streamlit 页面增加 HTML 报告下载按钮。
- 报告中至少显示：总数、PASS/FAIL/ERROR、规则预期通过率、备选恢复步骤、截图、mutation score。

#### 不足-C：无并发执行能力

**设计方案：** 使用 `ThreadPoolExecutor` 并发执行场景，但每个 worker 必须创建完整独立的 `TestAgent` 实例。不要在线程中临时替换 `self.executor`，因为 `executor/memory/planner/resolver` 都不是线程安全对象。

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def run_scenarios_parallel(
    base_config: dict,
    scenarios: list[dict],
    max_workers: int = 3,
    progress_callback=None,
) -> list[dict]:
    """并发执行测试场景；每个 worker 创建独立 TestAgent。"""
    results = [None] * len(scenarios)

    def run_one(index, scenario):
        from task2_agent.agent import TestAgent

        cfg = dict(base_config)
        cfg["screenshot_dir"] = f"{base_config.get('screenshot_dir', 'reports/screenshots')}/worker_{index}"
        agent = TestAgent(cfg)
        result = agent.run_scenario(scenario)
        return index, result

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run_one, i, s): i for i, s in enumerate(scenarios)}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result
            if progress_callback:
                done = sum(1 for r in results if r is not None)
                progress_callback(done, len(scenarios), result)

    return results
```

**并发限制建议：**

- 默认 `max_workers=2` 或 `3`，避免 demo 站点和本机浏览器资源被打满。
- 每个 worker 使用独立截图目录，避免文件名冲突。
- 并发执行默认用于回归批量跑；调试单个场景仍用串行模式，日志更清楚。
- 如果遇到 demo 账号共享数据互相污染，优先按功能分类串行、分类之间并发。

---
## 三、分工时间建议

| 成员 | 核心任务 | 预计工时 | 优先级 |
| --- | --- | --- | --- |
| A | Prompt 工程 + DOM 快照 | 已完成 | 已验收，后续只做回归保护 |
| B | JSON 修复 + RAG chunk/search 优化 + 数量守护 | 1-2 天 | 高 |
| C | 备选步骤审计 + 执行器性能/可靠性优化 | 2 天 | 最高 |
| D | 验证口径 + HTML 报告 + Streamlit 后台执行 + 变异/并发 | 2-3 天 | 高 |

建议执行顺序： C（先修备选步骤记录和执行性能）→ B（补 JSON/RAG 基础稳健性）→ D（把验证、报告和前端执行体验收口）。其中 B 和 C 可以并行；D 中的 HTML 报告可以先做，因为它能直接展示 A/C 的验收结果。

---
