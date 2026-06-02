"""
config.py - 全局配置
修改 DEEPSEEK_API_KEY 后即可运行
"""
import os
from dotenv import load_dotenv

load_dotenv()  # 支持从 .env 文件读取

# ── DeepSeek API（通过 OpenAI 兼容接口调用）─────────────
# 兼容旧版 GLM_* 环境变量，避免其他模块导入名大范围改动。
DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", os.getenv("GLM_API_KEY", "your-deepseek-api-key"))
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", os.getenv("GLM_BASE_URL", "https://api.deepseek.com"))
LLM_MODEL         = os.getenv("LLM_MODEL", "deepseek-chat")  # 可选: deepseek-chat / deepseek-reasoner / deepseek-v4-flash

# 旧模块仍从 config 导入 GLM_*，这里作为兼容别名保留。
GLM_API_KEY  = DEEPSEEK_API_KEY
GLM_BASE_URL = DEEPSEEK_BASE_URL

# ── 目标应用 ───────────────────────────────────────────────
TARGET_APP_URL = "https://demo.4gaboards.com"
DOCS_BASE_URL  = "https://docs.4gaboards.com"

# 本地完整文档目录（推荐使用）。网络爬取作为 fallback。
LOCAL_DOCS_DIR = "4gaboards_doc/4gaboards"

# 演示账号（4ga Boards demo 站点默认账号）
DEMO_USERNAME = "demo@demo.demo"
DEMO_PASSWORD = "demo"

# 浏览器与目标应用语言。demo 账号是共享账号，语言偏好可能被别人改动；
# 测试时强制英文，避免 selector 文本和文档语言不一致。
BROWSER_LOCALE      = os.getenv("BROWSER_LOCALE", "en-US")
TARGET_APP_LANGUAGE = os.getenv("TARGET_APP_LANGUAGE", "en")

# ── RAG 设置 ───────────────────────────────────────────────
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # 本地嵌入模型，无需额外 API
CHUNK_SIZE      = 600                    # 每个文本块字符数
CHUNK_OVERLAP   = 80                     # 相邻块重叠字符数
TOP_K_RETRIEVAL = 5                      # RAG 检索返回的块数量

# ── 文件路径 ───────────────────────────────────────────────
DATA_DIR         = "data"
REPORTS_DIR      = "reports"
VECTOR_DB_PATH   = f"{DATA_DIR}/vector_store"   # Qdrant 嵌入式持久化目录
SCENARIOS_PATH   = f"{DATA_DIR}/test_scenarios.json"
FEATURES_PATH    = f"{DATA_DIR}/features.json"
GRAPH_PATH       = f"{DATA_DIR}/knowledge_graph.json"  # networkx 兜底持久化

# ── 知识图谱（Neo4j 优先；连不上自动 networkx 兜底）─────────
NEO4J_URI      = os.getenv("NEO4J_URI",  "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "test1234")

# ── 智能体设置 ─────────────────────────────────────────────
MAX_STEPS_PER_SCENARIO = 20    # 每个场景最多执行步数
SCREENSHOT_ON_STEP     = True  # 每步截图（用于报告）
AGENT_TIMEOUT          = 10000 # 单个操作超时（毫秒）
HEADLESS               = True  # True=不弹出浏览器窗口
