# 4ga Boards 智能测试工具

基于国产大模型（GLM / DeepSeek / Qwen）的测试场景自动生成与智能执行平台。

## 项目结构

```
4ga_test_tool/
├── app.py                  # Streamlit 主界面（唯一入口）
├── config.py               # 全局配置
├── llm_client.py           # 统一 LLM 调用封装（OpenAI 兼容接口）
├── requirements.txt        # 依赖列表
├── .env.example            # 环境变量示例
├── task1_rag/
│   ├── crawler.py          # 文档爬取
│   ├── rag_engine.py       # 向量检索引擎
│   └── scenario_gen.py     # 功能点提取 + 场景生成
├── task2_agent/
│   ├── memory.py           # 执行记忆
│   ├── executor.py         # 浏览器执行器
│   ├── planner.py          # 规划器
│   ├── verifier.py         # 验证器
│   └── agent.py            # 智能体主控
├── data/                   # 运行时生成（文档缓存、场景 JSON）
└── reports/                # 运行时生成（测试报告、截图）
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置 API Key

方式一：复制 `.env.example` 为 `.env`，填入 Key：
```bash
cp .env.example .env
# 编辑 .env，填入 GLM_API_KEY=your-zhipu-api-key
```

方式二：直接在启动后的 Web 界面侧边栏填写。

> 智谱 GLM API Key 可在 https://bigmodel.cn 获取。
> 项目使用 OpenAI 兼容接口调用，如需切换 DeepSeek / Qwen 等其他国产模型，
> 只需修改侧边栏的 **API Base URL** 与 **模型** 即可，代码无需改动。

### 3. 启动界面

```bash
streamlit run app.py
```

浏览器会自动打开 `http://localhost:8501`

---

## 使用流程

### 任务一：生成测试场景

1. 在侧边栏填写 Anthropic API Key
2. 点击 **Tab 1「场景生成」**
3. 点击「🚀 开始生成测试场景」
4. 等待三个步骤完成（爬取文档 → 构建向量索引 → LLM 生成场景）
5. 在下方浏览功能点树和测试场景

### 任务二：执行测试

1. 完成任务一后切换到 **Tab 2「测试执行」**
2. 选择要执行的场景（或全量执行）
3. 点击「▶️ 开始执行测试」
4. 等待执行完成，查看报告

---

## 配置说明

`config.py` 中的主要参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `LLM_MODEL` | `glm-4.6` | 使用的大模型，可选 `glm-4-plus` / `glm-4-air` / `glm-4-flash` 等 |
| `GLM_BASE_URL` | 智谱 OpenAI 兼容接口 | 切换其他国产模型只需改这里 |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | 本地嵌入模型，首次运行自动下载 |
| `HEADLESS` | `True` | 改为 `False` 可在调试时看到浏览器窗口 |
| `MAX_STEPS_PER_SCENARIO` | `20` | 每个场景最多执行步数 |
| `CHUNK_SIZE` | `600` | 文档分块大小，影响 RAG 精度 |

---

## 注意事项

- 首次运行会自动下载嵌入模型（约 90MB），需要网络连接
- `data/` 和 `reports/` 目录由程序自动创建
- 截图保存在 `reports/screenshots/`，测试报告保存在 `reports/`
- demo.4gaboards.com 的演示账号：`demo@demo.demo` / `demo`
