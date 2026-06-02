# 4ga Boards 智能测试工具

一个面向 4ga Boards 看板应用的自动化测试平台：从官方文档中提取功能点，使用 RAG + 大模型生成结构化测试场景，再由 Playwright 智能体在真实浏览器中执行、截图并生成报告。

项目默认使用 DeepSeek 的 OpenAI 兼容接口，也可以切换到其他兼容接口的大模型。

## 功能特性

- **RAG 场景生成**：读取本地 4ga Boards Markdown 文档，构建向量索引，自动生成可执行测试场景。
- **DOM 快照约束**：抓取真实页面 DOM，减少 LLM 编造 selector、URL 和按钮文案的问题。
- **知识图谱**：将 Category、Feature、Scenario、Step 写入 Neo4j；Neo4j 不可用时自动降级到 networkx。
- **智能执行 Agent**：基于 Planner、Memory、Executor、Verifier 的执行链路，自动处理登录、进入项目、打开看板等前置步骤。
- **页面感知 Resolver**：执行前读取真实页面元素，对齐 LLM 生成的 target 与当前 DOM。
- **测试报告与截图**：执行结果保存为 JSON，截图保存在 `reports/` 目录，Streamlit 页面可视化查看。

## 项目结构

```text
.
├── app.py                         # Streamlit 主界面
├── config.py                      # 全局配置
├── llm_client.py                  # OpenAI 兼容 LLM 调用封装
├── requirements.txt               # Python 依赖
├── docker-compose.yml             # 可选 Neo4j 服务
├── task1_rag/
│   ├── crawler.py                 # 文档加载与爬取
│   ├── rag_engine.py              # Qdrant / FAISS 向量检索
│   ├── knowledge_graph.py         # Neo4j / networkx 知识图谱
│   ├── dom_snapshot.py            # 真实 DOM 快照抓取
│   └── scenario_gen.py            # 功能点提取与测试场景生成
├── task2_agent/
│   ├── agent.py                   # 测试智能体主控
│   ├── planner.py                 # 前置步骤规划
│   ├── executor.py                # Playwright 浏览器执行器
│   ├── resolver.py                # 页面感知 target 修正
│   ├── verifier.py                # 规则验证 + LLM 综合判断
│   └── memory.py                  # 执行轨迹记忆
├── data/
│   ├── features.json              # 已生成的功能点
│   ├── test_scenarios.json        # 已生成的测试场景
│   └── dom_snapshots.json         # DOM 快照
├── test_data/
│   └── 4gaboards_export.tgz       # 导入看板测试夹具
└── reports/                       # 测试报告与截图，运行时生成
```

## 环境要求

- Python 3.10 或更高版本
- Chromium 浏览器依赖，由 Playwright 安装
- DeepSeek API Key 或其他 OpenAI 兼容接口 Key
- Docker 可选，仅用于启动 Neo4j 图数据库

## 快速开始

1. 克隆项目并进入目录：

```bash
git clone <your-repo-url>
cd 4ga_test_tool-main
```

2. 创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

3. 配置环境变量：

```bash
cp .env.example .env
```

然后编辑 `.env`：

```env
DEEPSEEK_API_KEY=your-deepseek-api-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

4. 启动 Web 界面：

```bash
streamlit run app.py
```

默认访问地址为 `http://localhost:8501`。

## 使用流程

### 1. 生成 DOM 快照

项目已经包含 `data/dom_snapshots.json`。如果页面结构变化，可以重新抓取：

```bash
python3 -m task1_rag.dom_snapshot
```

DOM 快照会被注入到场景生成 prompt 中，用于约束 selector、按钮文本和 URL 预期。

### 2. 生成测试场景

打开 Streamlit 后进入 **任务一：场景生成**：

1. 在侧边栏填写 API Key、模型和目标应用信息。
2. 勾选“使用本地完整文档”。
3. 点击“开始生成测试场景”。
4. 生成结果会写入：

```text
data/features.json
data/test_scenarios.json
data/knowledge_graph.json
```

当前版本已准备好一份生成结果：25 个功能点、54 个测试场景。

### 3. 执行测试

进入 **任务二：测试执行**：

1. 选择少量场景先进行冒烟测试。
2. 建议保持“页面感知 Resolver”开启。
3. 点击“开始执行测试”。
4. 执行报告会保存到：

```text
reports/test_report_*.json
reports/screenshots*/
```

### 4. 查看知识图谱

进入 **知识图谱** 标签页，可以查看：

- 功能分类
- 功能点
- 测试场景
- 操作步骤

默认使用 networkx 兜底图谱。若要使用 Neo4j：

```bash
docker-compose up -d neo4j
```

Neo4j Browser 地址：

```text
http://localhost:7474
账号：neo4j
密码：test1234
```

## 命令行运行

除 Streamlit 外，也可以直接运行核心模块。

构建或加载文档索引并生成场景：

```bash
python3 -m task1_rag.scenario_gen
```

重新抓取 DOM 快照：

```bash
python3 -m task1_rag.dom_snapshot
```

## 配置说明

主要配置位于 `config.py` 和 `.env`：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | `your-deepseek-api-key` | 大模型 API Key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容接口地址 |
| `LLM_MODEL` | `deepseek-chat` | 默认模型 |
| `TARGET_APP_URL` | `https://demo.4gaboards.com` | 被测应用 |
| `DEMO_USERNAME` | `demo@demo.demo` | 4ga Boards demo 账号 |
| `DEMO_PASSWORD` | `demo` | 4ga Boards demo 密码 |
| `LOCAL_DOCS_DIR` | `4gaboards_doc/4gaboards` | 本地 Markdown 文档目录 |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | 本地 embedding 模型 |
| `HEADLESS` | `True` | 是否使用无头浏览器 |

## 测试数据说明

`test_data/` 目录存放浏览器上传测试所需夹具：

- `4gaboards_export.tgz`：用于 4ga Boards 导入看板场景，已准备。
- `trello_export.json`：用于 Trello 导入场景，当前未包含，需要从真实 Trello 看板导出。

如果缺少 `trello_export.json`，对应 Trello 导入场景不建议作为最终验收场景。

## GitHub 上传注意事项

上传前请确认不要提交敏感信息和运行时大文件：

- 不要提交 `.env`，里面可能包含真实 API Key。
- 不要提交 `data/.cfg.json`，Streamlit 会把界面配置缓存到这里。
- 不要提交 `data/vector_store/`、`data/neo4j_data/`、大量截图和运行报告。
- 当前 `.gitignore` 已经包含上述规则，提交前仍建议运行：

```bash
git status
```

如果已经误提交过 API Key，需要立即在平台上作废该 Key 并重新生成。

## 常见问题

### 1. Playwright 找不到浏览器

运行：

```bash
playwright install chromium
```

### 2. 首次构建 RAG 很慢

首次运行会下载 embedding 模型并构建 Qdrant 向量索引。完成后索引会缓存在 `data/vector_store/`，下次可直接复用。

### 3. Neo4j 没启动会不会影响主流程

不会。Neo4j 不可用时会自动使用 networkx 兜底，场景生成和测试执行仍可运行。

### 4. Demo 站点语言变了导致按钮找不到

项目会尽量把 demo 账号语言固定为英文，并使用 DOM 快照和页面感知 Resolver 降低影响。若仍失败，可以重新运行：

```bash
python3 -m task1_rag.dom_snapshot
```

再重新生成场景。

## 当前状态

- 已完成成员 A 的场景生成质量修复。
- 当前基线：25 个功能点、54 个测试场景。
- 已验证 4ga Boards 导入场景 `f012_s02` 可执行通过。
- Trello 导入场景依赖 `test_data/trello_export.json`，需额外准备真实导出文件。

## License

本项目用于课程大作业和学习研究。若要公开发布或二次使用，请根据课程要求和依赖库协议补充许可证说明。
