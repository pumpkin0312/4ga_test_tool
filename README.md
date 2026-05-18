# 4ga Boards 智能测试工具

基于国产大模型（GLM / DeepSeek / Qwen）的测试场景自动生成与智能执行平台。

针对 4ga Boards 看板应用，从**本地用户手册（Markdown）** 提取功能知识，自动生成结构化测试场景，
并由「规划-记忆-执行-验证」智能体在真实浏览器中执行验证。

## 项目结构

```
4ga_test_tool/
├── app.py                  # Streamlit 主界面（唯一入口）
├── config.py               # 全局配置（含本地文档路径 LOCAL_DOCS_DIR）
├── llm_client.py           # 统一 LLM 调用封装（OpenAI 兼容接口）
├── requirements.txt        # 依赖列表
├── .env.example            # 环境变量示例
├── task1_rag/
│   ├── crawler.py          # 知识源加载（本地 Markdown 优先 / 网络爬取兜底）
│   ├── rag_engine.py       # FAISS 向量检索引擎
│   └── scenario_gen.py     # 功能点提取 + 测试场景生成
├── task2_agent/
│   ├── memory.py           # 执行记忆
│   ├── executor.py         # Playwright 浏览器执行器
│   ├── planner.py          # 规划器（智能注入前置：登录/进项目/打开看板）
│   ├── resolver.py         # 页面感知 Resolver（执行前对齐 target 与真实 DOM）
│   ├── verifier.py         # 规则 + LLM 综合验证
│   └── agent.py            # 智能体主控
├── data/                   # 运行时生成（功能点 / 场景 JSON / 向量索引）
└── reports/                # 运行时生成（测试报告、截图）

# 项目同级目录还需放置：
../4gaboards_doc/4gaboards/  # 4ga Boards 官方 Markdown 文档（解压自 4gaboards_doc.zip）
```

## 知识源说明（重要）

本项目**优先读取本地完整 Markdown 文档**，比网络爬取更可靠且内容更完整：

| 知识源 | 推荐度 | 说明 |
|---|---|---|
| 📁 本地 Markdown（默认） | ⭐⭐⭐⭐⭐ | 读取 `../4gaboards_doc/4gaboards/**/*.md`，共 ~34KB / 15 个文件 |
| 🗃️ 缓存索引 | ⭐⭐⭐⭐ | 复用上次构建的向量索引，省 30 秒重新嵌入时间 |
| 🌐 网络爬取 | ⭐⭐ | 仅作 fallback：当本地文档缺失时尝试 `docs.4gaboards.com` |

`config.LOCAL_DOCS_DIR` 默认指向 `../4gaboards_doc/4gaboards`。
若你的 markdown 放在其他位置，修改此配置或调整目录结构即可。

## 快速开始

### 1. 准备文档（首次必做）

把 `4gaboards_doc.zip` 解压到项目**上一级**目录：

```bash
# 在项目同级目录下
unzip 4gaboards_doc.zip -d ./
# 解压后应当有：4gaboards_doc/4gaboards/For_Users/*.md 等
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. 配置 API Key

方式一：复制 `.env.example` 为 `.env`，填入 Key：
```bash
cp .env.example .env
# 编辑 .env，填入 GLM_API_KEY=your-zhipu-api-key
```

方式二：直接在启动后的 Web 界面侧边栏填写。

> 智谱 GLM API Key 可在 https://bigmodel.cn 获取。
> 项目使用 OpenAI 兼容接口调用，如需切换 DeepSeek / Qwen 等其他国产模型，
> 只需修改侧边栏的 **API Base URL** 与 **模型** 即可，代码无需改动。

### 4. 启动界面

```bash
streamlit run app.py
```

浏览器会自动打开 `http://localhost:8501`

---

## 使用流程

### 任务一：生成测试场景

1. 在侧边栏填写 GLM API Key，点击「💾 保存配置」
2. 切换到 **Tab 1「场景生成」**
3. 勾选「📁 使用本地完整文档（推荐）」（默认已勾选）
4. 点击「🚀 开始生成测试场景」
5. 等待三个步骤完成：**加载本地文档** → 构建 FAISS 向量索引 → LLM 生成功能点与场景
6. 在下方按分类树形浏览功能点和测试场景

预期：约 20-30 个功能点，60-80 个测试场景，覆盖用户/项目/看板/列表/卡片/设置 6 大分类。

### 任务二：执行测试

1. 完成任务一后切换到 **Tab 2「测试执行」**
2. 在侧边栏可勾选「🔍 页面感知（Page-aware Resolver）」开启幻觉防护（默认开启）
3. 选择要执行的场景（建议先选 5 个简单场景验证环境）
4. 点击「▶️ 开始执行测试」
5. 执行完成后查看报告：步骤通过率、预期验证、失败截图、LLM 综合诊断

中断后可点击「🔄 重置 UI」恢复，已完成的场景结果会写入 `reports/test_report_*_running.json`。

---

## 智能体特性（任务二）

- **「规划-记忆-执行-验证」四要素架构**
- **页面感知 Resolver**：执行前快速校验 target 是否存在于当前页面，找不到时调用 LLM 从页面真实元素中重定向，**降低 LLM 幻觉造成的执行失败**
- **智能前置注入**：planner 根据场景 `precondition` 自动注入「登录 → 进项目 → 开看板」前置步骤
- **对话框作用域优先查找**：解决 4ga Boards 中「侧边栏 + Add Project」与「对话框内 + Add Project」按钮同名歧义
- **严格文本可见性验证**：排除 input/textarea 的 value 残留，避免假阳性 PASS
- **失败原因联动**：规则验证全部未通过时强制将 LLM 综合结果降级为 FAIL
- **连续失败提前跳出**：单场景连续 3 步失败自动终止，避免拖死全量执行

---

## 配置说明

`config.py` 中的主要参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `LLM_MODEL` | `glm-4-plus` | 使用的大模型，可选 `glm-4-plus` / `glm-4-air` / `glm-4-flash` / `glm-4.6` |
| `GLM_BASE_URL` | 智谱 OpenAI 兼容接口 | 切换其他国产模型只需改这里 |
| `LOCAL_DOCS_DIR` | `../4gaboards_doc/4gaboards` | 本地 Markdown 文档根目录 |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | 本地嵌入模型，首次运行自动下载 |
| `HEADLESS` | `True` | 改为 `False` 可在调试时看到浏览器窗口 |
| `MAX_STEPS_PER_SCENARIO` | `20` | 每个场景最多执行步数 |
| `CHUNK_SIZE` | `600` | 文档分块大小，影响 RAG 精度 |

---

## 注意事项

- 首次运行会自动下载嵌入模型（约 90MB），需要网络连接
- 必须先准备好本地 `4gaboards_doc/` 文档目录，否则只能用网络爬取（内容残缺）
- `data/` 和 `reports/` 目录由程序自动创建
- 截图保存在 `reports/screenshots/`，测试报告保存在 `reports/`
- demo.4gaboards.com 的演示账号：`demo@demo.demo` / `demo`
- demo 站点是公开共享的，执行测试会产生项目/看板，不影响他人
