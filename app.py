"""
app.py  —  Streamlit 主界面
运行方式: streamlit run app.py
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# Windows 上 Streamlit 捕获的 stdout 默认是 GBK，rich 输出 ✓ 之类字符会报 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import streamlit as st

# ── 页面基础配置 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="4ga Boards 智能测试工具",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* 优先级徽章 */
.badge-high   { background:#fde8e8; color:#c0392b; padding:2px 8px; border-radius:10px; font-size:12px; }
.badge-medium { background:#fef9e7; color:#d68910; padding:2px 8px; border-radius:10px; font-size:12px; }
.badge-low    { background:#eafaf1; color:#1e8449; padding:2px 8px; border-radius:10px; font-size:12px; }
/* 结果徽章 */
.badge-pass   { background:#eafaf1; color:#1e8449; padding:2px 10px; border-radius:10px; font-size:13px; }
.badge-fail   { background:#fde8e8; color:#c0392b; padding:2px 10px; border-radius:10px; font-size:13px; }
</style>
""", unsafe_allow_html=True)


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def load_json(path: str):
    p = Path(path)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None

def save_cfg(cfg: dict):
    os.makedirs("data", exist_ok=True)
    with open("data/.cfg.json", "w") as f:
        json.dump(cfg, f)

def load_cfg() -> dict:
    defaults = dict(
        api_key="",
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        model="glm-4-plus",
        app_url="https://demo.4gaboards.com",
        docs_url="https://docs.4gaboards.com",
        username="demo@demo.demo", password="demo",
        headless=True, max_steps=20,
        page_aware=True,
    )
    cached = load_json("data/.cfg.json")
    if cached:
        defaults.update(cached)
    return defaults


# ══════════════════════════════════════════════════════════════════════════════
# 侧边栏
# ══════════════════════════════════════════════════════════════════════════════

def render_sidebar() -> dict:
    with st.sidebar:
        st.title("⚙️ 配置")
        cfg = load_cfg()

        st.markdown("**🤖 大模型设置**")
        api_key  = st.text_input("GLM API Key", value=cfg["api_key"],
                                  type="password", help="智谱 AI API Key（在 bigmodel.cn 获取）")
        model_options = ["glm-4-plus", "glm-4-air", "glm-4-flash", "glm-4.6"]
        model    = st.selectbox(
            "模型",
            model_options,
            index=model_options.index(cfg["model"]) if cfg["model"] in model_options else 0,
            help="推荐 glm-4-plus（非思考型，输出 JSON 稳定）；glm-4.6 为思考型，速度慢",
        )
        base_url = st.text_input("API Base URL", value=cfg["base_url"],
                                  help="OpenAI 兼容接口；切换到 DeepSeek/Qwen 时改这里即可")

        st.divider()
        st.markdown("**🌐 测试目标**")
        app_url  = st.text_input("目标应用 URL",  value=cfg["app_url"])
        docs_url = st.text_input("文档 URL",      value=cfg["docs_url"])
        username = st.text_input("测试账号",       value=cfg["username"])
        password = st.text_input("测试密码",       value=cfg["password"], type="password")

        st.divider()
        st.markdown("**🔧 执行参数**")
        headless   = st.checkbox("无头浏览器（不弹窗）", value=cfg["headless"])
        page_aware = st.checkbox(
            "🔍 页面感知（Page-aware Resolver）",
            value=cfg.get("page_aware", True),
            help="每步执行前先读取页面、自动对齐 LLM 给的 target 与真实 DOM。"
                 "找不到时才调 LLM，可减少『按钮名猜错』导致的失败。",
        )
        max_steps  = st.slider("最大步骤数/场景", 5, 40, cfg["max_steps"])

        if st.button("💾 保存配置"):
            save_cfg(dict(api_key=api_key, base_url=base_url, model=model,
                          app_url=app_url, docs_url=docs_url,
                          username=username, password=password,
                          headless=headless, max_steps=max_steps,
                          page_aware=page_aware))
            st.success("已保存")

        st.divider()
        st.caption("📖 [文档](https://docs.4gaboards.com)  🎮 [Demo](https://demo.4gaboards.com)")

    return dict(api_key=api_key, base_url=base_url, model=model,
                app_url=app_url, docs_url=docs_url,
                username=username, password=password,
                headless=headless, max_steps=max_steps,
                page_aware=page_aware)


# ══════════════════════════════════════════════════════════════════════════════
# Tab 1：场景生成
# ══════════════════════════════════════════════════════════════════════════════

def tab_generate(cfg: dict):
    st.header("📋 任务一：测试场景自动生成（RAG）")

    features  = load_json("data/features.json")
    scenarios = load_json("data/test_scenarios.json")

    # 状态提示
    if features and scenarios:
        st.success(f"✅ 已有数据：**{len(features)}** 个功能点  |  **{len(scenarios)}** 个测试场景")
    else:
        st.info("尚未生成数据，填写 API Key 后点击下方按钮开始。")

    # 知识源选择 & 缓存控制
    col1, col2, col3 = st.columns(3)
    with col1:
        source_local = st.checkbox(
            "📁 使用本地完整文档（推荐）",
            value=True,
            help="读取 4gaboards_doc/ 下的官方 Markdown（约 34KB / 15 个文件）。"
                 "比网络爬取更可靠、内容更丰富。",
        )
    with col2:
        use_cache = st.checkbox(
            "🗃️ 使用已缓存索引",
            value=True,
            help="若数据源没换、文档没更新，可直接复用上次的向量索引。",
        )
    with col3:
        force_rebuild = st.checkbox(
            "🔄 强制重建索引",
            value=False,
            help="切换知识源、或修改了文档后勾选此项重新构建向量索引。",
        )

    if st.button("🚀 开始生成测试场景", type="primary", disabled=not cfg["api_key"]):
        if not cfg["api_key"]:
            st.error("请先在侧边栏填写 GLM API Key")
        else:
            _do_generate(cfg, use_cache and not force_rebuild, use_local=source_local)

    # 可视化展示
    if features and scenarios:
        st.divider()
        _render_feature_tree(features, scenarios)


def _do_generate(cfg: dict, use_cache: bool, use_local: bool = True):
    """执行场景生成流程，流式更新进度"""
    import sys, os
    sys.path.insert(0, os.getcwd())

    from config import (EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP,
                        VECTOR_DB_PATH, SCENARIOS_PATH, FEATURES_PATH,
                        LOCAL_DOCS_DIR)
    from task1_rag.crawler    import DocsCrawler
    from task1_rag.rag_engine import RAGEngine
    from task1_rag.scenario_gen import ScenarioGenerator

    bar    = st.progress(0, text="初始化...")
    status = st.empty()
    os.makedirs("data", exist_ok=True)

    try:
        # 步骤 1：加载文档（优先本地，其次缓存，再次网络爬取）
        status.info("📥 步骤 1/3：加载知识源...")
        bar.progress(10, text="加载文档...")
        crawler = DocsCrawler(cfg["docs_url"], "data")

        pages = []
        if use_local:
            pages = crawler.load_local_markdown(LOCAL_DOCS_DIR)
            if pages:
                status.success(f"✅ 已加载本地完整文档：{len(pages)} 个 Markdown 文件")

        if not pages and use_cache:
            pages = crawler.load_cached()
            if pages:
                status.success(f"已加载缓存文档：{len(pages)} 个块")

        if not pages:
            status.info("从网络爬取文档...")
            pages = crawler.crawl()
            status.success(f"文档就绪：{len(pages)} 个块")
        bar.progress(35, text="构建向量索引...")

        # 步骤 2：RAG 索引
        status.info("🔍 步骤 2/3：构建向量索引...")
        rag = RAGEngine(VECTOR_DB_PATH, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP)
        if use_cache and rag.load_index():
            status.success("向量索引已从缓存加载")
        else:
            rag.build_index(pages)
            status.success("向量索引构建完成")
        bar.progress(60, text="LLM 生成场景...")

        # 步骤 3：生成场景
        status.info(f"🤖 步骤 3/3：LLM 提取功能点并生成测试场景...（模型：{cfg['model']}）")
        gen = ScenarioGenerator(cfg["api_key"], cfg["model"], rag, base_url=cfg["base_url"])
        features, scenarios = gen.run(pages, SCENARIOS_PATH, FEATURES_PATH)

        bar.progress(100, text="完成！")
        status.success(f"✅ 生成完成：{len(features)} 个功能点，{len(scenarios)} 个测试场景")
        time.sleep(1)
        st.rerun()

    except Exception as e:
        bar.empty()
        status.error(f"生成失败：{e}")
        st.exception(e)


def _render_feature_tree(features: list, scenarios: list):
    """按分类展示功能点树与测试场景"""
    from collections import defaultdict

    # 建立 feature_id → scenarios 映射
    s_map: dict[str, list] = defaultdict(list)
    for s in scenarios:
        s_map[s.get("feature_id", "")].append(s)

    # 统计指标
    categories = list({f.get("category", "未分类") for f in features})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("功能点",   len(features))
    c2.metric("测试场景", len(scenarios))
    c3.metric("功能分类", len(categories))
    avg = len(scenarios) / len(features) if features else 0
    c4.metric("平均场景/功能", f"{avg:.1f}")

    # 过滤器
    st.subheader("功能点 & 场景浏览")
    col_a, col_b = st.columns(2)
    with col_a:
        sel_cat = st.selectbox("功能分类", ["全部"] + sorted(categories))
    with col_b:
        sel_pri = st.selectbox("优先级",   ["全部", "high", "medium", "low"])

    # 按分类分组展示
    cat_map: dict[str, list] = defaultdict(list)
    for f in features:
        cat_map[f.get("category", "未分类")].append(f)

    for cat in sorted(cat_map):
        if sel_cat != "全部" and cat != sel_cat:
            continue
        cat_features = cat_map[cat]
        with st.expander(f"📁 {cat}（{len(cat_features)} 个功能点）"):
            for feat in cat_features:
                fid       = feat.get("id", "")
                fname     = feat.get("name", "")
                fdesc     = feat.get("description", "")
                fscenarios = s_map.get(fid, [])

                if sel_pri != "全部":
                    fscenarios = [s for s in fscenarios if s.get("priority") == sel_pri]

                st.markdown(f"**🔧 {fname}** &nbsp; `{fid}`")
                st.caption(fdesc)

                if not fscenarios:
                    st.caption("_无匹配场景_")
                else:
                    for sc in fscenarios:
                        _render_scenario_card(sc)
                st.divider()


def _render_scenario_card(sc: dict):
    pri_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(sc.get("priority","medium"), "⚪")
    name  = sc.get("name", "")
    sid   = sc.get("id",   "")
    pre   = sc.get("precondition", "")
    steps = sc.get("steps", [])
    exps  = sc.get("expectations", [])
    tags  = sc.get("tags", [])

    col1, col2 = st.columns([5, 1])
    with col1:
        st.markdown(f"{pri_icon} **{name}** &nbsp; `{sid}`")
        if pre:
            st.caption(f"前置条件：{pre}")
        if tags:
            st.caption("标签：" + "  ".join(f"`{t}`" for t in tags))
    with col2:
        st.caption(f"{len(steps)} 步")

    # 用 HTML <details> 实现折叠（避免 Streamlit expander 嵌套限制）
    col_s, col_e = st.columns(2)
    with col_s:
        steps_html = [f"<details><summary>📌 操作步骤（{len(steps)}）</summary>"]
        steps_html.append("<ol style='margin-top:6px;'>")
        for s in steps:
            detail = f"<code>{s.get('action','')}</code> → {s.get('target','')}"
            if s.get("value"):
                detail += f" = <code>{s['value']}</code>"
            steps_html.append(
                f"<li>{s.get('description','')}<br/>"
                f"<span style='color:#888;font-size:12px;'>{detail}</span></li>"
            )
        steps_html.append("</ol></details>")
        st.markdown("\n".join(steps_html), unsafe_allow_html=True)

    with col_e:
        exp_html = [f"<details><summary>✅ 预期状态（{len(exps)}）</summary>"]
        exp_html.append("<ul style='margin-top:6px;'>")
        for e in exps:
            val = f" = <code>{e['value']}</code>" if e.get("value") else ""
            exp_html.append(
                f"<li><code>{e.get('condition','')}</code> "
                f"{e.get('description','')}{val}</li>"
            )
        exp_html.append("</ul></details>")
        st.markdown("\n".join(exp_html), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2：测试执行
# ══════════════════════════════════════════════════════════════════════════════

def tab_execute(cfg: dict):
    st.header("🤖 任务二：智能测试执行（Agent）")

    scenarios = load_json("data/test_scenarios.json")
    if not scenarios:
        st.warning("请先完成「任务一」生成测试场景")
        return

    st.info(f"共 **{len(scenarios)}** 个测试场景可执行")

    # 选择模式
    col1, col2 = st.columns(2)
    with col1:
        mode = st.radio("执行模式", ["选择指定场景", "全量执行"])
    with col2:
        if mode == "选择指定场景":
            opts = {f"[{s['id']}] {s['name']}": s for s in scenarios}
            chosen = st.multiselect("选择场景", list(opts.keys()),
                                     default=list(opts.keys())[:2])
            to_run = [opts[k] for k in chosen]
        else:
            to_run = scenarios
            st.caption(f"将执行全部 {len(scenarios)} 个场景")

    disabled = not cfg["api_key"] or not to_run
    btn_col1, btn_col2 = st.columns([3, 1])
    with btn_col1:
        if st.button("▶️ 开始执行测试", type="primary", disabled=disabled):
            _do_execute(cfg, to_run)
    with btn_col2:
        if st.button("🔄 重置 UI", help="若上一次执行被中断 UI 仍卡在『运行中』，点这里清理状态"):
            st.rerun()

    st.divider()
    _render_reports()


def _do_execute(cfg: dict, scenarios: list):
    """执行测试，实时更新进度"""
    import sys
    sys.path.insert(0, os.getcwd())
    from task2_agent.agent import TestAgent

    agent_cfg = dict(
        api_key       = cfg["api_key"],
        model         = cfg["model"],
        base_url      = cfg["base_url"],
        app_url       = cfg["app_url"],
        username      = cfg["username"],
        password      = cfg["password"],
        headless      = cfg["headless"],
        max_steps     = cfg["max_steps"],
        page_aware    = cfg.get("page_aware", True),
        screenshot    = True,
        screenshot_dir= "reports/screenshots",
        report_dir    = "reports",
    )
    agent   = TestAgent(agent_cfg)
    bar     = st.progress(0, text="准备中...")
    live    = st.empty()
    results = []

    def on_progress(done: int, total: int, result: dict):
        bar.progress(done / total, text=f"执行中 {done}/{total}...")
        results.append(result)
        with live.container():
            for r in results:
                icon = "✅" if r.get("result") == "PASS" else "❌"
                rate = r.get("step_success_rate", 0)
                st.markdown(
                    f"{icon} **{r.get('scenario_name','')}**  —  "
                    f"{r.get('summary','')}  "
                    f"（步骤成功率 {rate:.0%}）"
                )

    try:
        agent.run_scenarios(scenarios, progress_callback=on_progress)
        bar.progress(1.0, text="✅ 执行完成")
        time.sleep(0.5)
        st.rerun()
    except Exception as e:
        bar.empty()
        st.error(f"执行失败：{e}")
        st.exception(e)
        # 把已完成的部分结果写盘，避免被打断后什么都没留下
        if results:
            try:
                ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = Path("reports") / f"test_report_{ts}_partial.json"
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
                st.warning(f"已保存中断前的部分结果：{path.name}")
            except Exception:
                pass


def _render_reports():
    """展示历史测试报告"""
    st.subheader("📊 历史报告")
    report_dir = Path("reports")
    if not report_dir.exists():
        st.caption("暂无报告")
        return

    reports = sorted(report_dir.glob("test_report_*.json"), reverse=True)
    if not reports:
        st.caption("暂无报告，请先执行测试")
        return

    selected = st.selectbox("选择报告", [p.name for p in reports])
    data     = load_json(f"reports/{selected}")
    if not data:
        return

    # 摘要指标
    total  = len(data)
    passed = sum(1 for r in data if r.get("result") == "PASS")
    rate   = passed / total if total else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总场景", total)
    c2.metric("通过",   passed)
    c3.metric("失败",   total - passed)
    c4.metric("通过率", f"{rate:.0%}")

    # 图表
    try:
        import pandas as pd
        import plotly.express as px
        df  = pd.DataFrame([{
            "场景":      r.get("scenario_name","")[:18],
            "结果":      r.get("result",""),
            "步骤成功率": round(r.get("step_success_rate",0)*100, 1),
        } for r in data])
        fig = px.bar(
            df, x="场景", y="步骤成功率", color="结果",
            color_discrete_map={"PASS": "#27ae60", "FAIL": "#e74c3c", "ERROR": "#e67e22"},
            title="各场景步骤成功率", height=280,
        )
        fig.update_layout(margin=dict(l=0, r=0, t=36, b=0))
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        pass

    # 详细结果
    st.subheader("场景详情")
    for r in data:
        icon  = "✅" if r.get("result") == "PASS" else "❌"
        label = r.get("result","")
        with st.expander(
            f"{icon} {r.get('scenario_name','')}  [{label}]  "
            f"步骤 {r.get('steps_passed',0)}/{r.get('steps_total',0)}"
        ):
            st.markdown(f"**结论：** {r.get('summary','')}")

            if r.get("issues"):
                st.warning("**发现问题**\n" + "\n".join(f"- {i}" for i in r["issues"]))

            if r.get("suggestions"):
                st.info("**改进建议**\n" + "\n".join(f"- {s}" for s in r["suggestions"]))

            # 预期验证明细
            exp_res = r.get("expectation_results", [])
            if exp_res:
                st.markdown("**预期验证明细**")
                for er in exp_res:
                    ico = "✅" if er.get("verified") else "❌"
                    st.markdown(f"{ico} {er.get('expectation','')}  —  {er.get('comment','')}")

            # 执行日志（用 HTML <details> 避免 expander 嵌套）
            if r.get("logs"):
                logs_text = "\n".join(r["logs"])
                st.markdown(
                    f"<details><summary>📜 执行日志</summary>"
                    f"<pre style='font-size:12px;background:#f6f8fa;padding:8px;"
                    f"border-radius:4px;max-height:300px;overflow:auto;'>{logs_text}</pre>"
                    f"</details>",
                    unsafe_allow_html=True,
                )

            # 截图：直接展开显示，不再嵌套 expander
            shots = r.get("screenshots", [])
            if shots:
                st.markdown(f"**🖼️ 截图（{len(shots)} 张，最多显示 9 张）**")
                cols = st.columns(min(len(shots), 3))
                for j, path in enumerate(shots[:9]):
                    if Path(path).exists():
                        cols[j % 3].image(path, use_column_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════════════════

def tab_graph():
    """知识图谱可视化（Neo4j 优先 / networkx 兜底）"""
    st.header("🕸️ 知识图谱：功能点 → 场景 → 步骤")
    from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, GRAPH_PATH
    try:
        from task1_rag.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, GRAPH_PATH)
    except Exception as e:
        st.error(f"知识图谱不可用：{e}")
        return

    backend = kg.backend_name
    if backend == "neo4j":
        st.success(f"🟢 后端：Neo4j（{NEO4J_URI}）"
                   "  —  可在 [Neo4j Browser](http://localhost:7474) 直接查询")
    else:
        st.warning("🟡 Neo4j 不可用，使用 **networkx** 嵌入式实现。"
                   "如需启用 Neo4j 请运行 `docker-compose up -d neo4j`。")

    # 统计
    stats = kg.stats() or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("分类", stats.get("categories", 0))
    c2.metric("功能点", stats.get("features", 0))
    c3.metric("场景", stats.get("scenarios", 0))
    c4.metric("步骤", stats.get("steps", 0))

    if not stats.get("features"):
        st.info("尚无图谱数据，先到 Tab 1 生成测试场景。")
        kg.close()
        return

    # Plotly 网络图
    try:
        import plotly.graph_objects as go
        import networkx as nx
        data = kg.export_for_visualization()
        G = nx.DiGraph()
        for n in data["nodes"]:
            G.add_node(n["id"], label=n["label"], name=n["name"])
        for e in data["edges"]:
            G.add_edge(e["source"], e["target"], type=e["type"])

        # 限制规模，避免渲染卡顿
        if G.number_of_nodes() > 200:
            keep = [n for n, d in G.nodes(data=True) if d.get("label") != "Step"]
            G = G.subgraph(keep).copy()
            st.caption(f"⚠️ 节点过多（>200），可视化时隐藏 Step 层，仅展示 Category/Feature/Scenario")

        pos = nx.spring_layout(G, k=0.8, iterations=40, seed=7)

        color_map = {
            "Category": "#3498db",
            "Feature":  "#27ae60",
            "Scenario": "#e67e22",
            "Step":     "#95a5a6",
        }
        node_x, node_y, node_text, node_color = [], [], [], []
        for n, d in G.nodes(data=True):
            x, y = pos[n]
            node_x.append(x); node_y.append(y)
            node_text.append(f"{d.get('label','')}: {d.get('name','')}")
            node_color.append(color_map.get(d.get("label"), "#999"))

        edge_x, edge_y = [], []
        for u, v in G.edges():
            x0, y0 = pos[u]; x1, y1 = pos[v]
            edge_x += [x0, x1, None]; edge_y += [y0, y1, None]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
                                 line=dict(width=0.4, color="#999"),
                                 hoverinfo="none"))
        fig.add_trace(go.Scatter(x=node_x, y=node_y, mode="markers",
                                 marker=dict(size=10, color=node_color, line=dict(width=0.5, color="#fff")),
                                 text=node_text, hoverinfo="text"))
        fig.update_layout(
            showlegend=False, hovermode="closest", height=600,
            margin=dict(l=10, r=10, t=20, b=10),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            title="🕸️ Category → Feature → Scenario → Step",
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.warning(f"图谱可视化失败：{e}")

    # 浏览器
    st.divider()
    st.subheader("🔍 浏览图谱")
    features = kg.list_features()
    if features:
        f_opts = {f"[{f['id']}] {f['name']} ({f['category']})": f["id"] for f in features}
        chosen = st.selectbox("选择功能点", list(f_opts.keys()))
        fid = f_opts[chosen]
        scenarios = kg.list_scenarios_of(fid)
        st.markdown(f"**该功能下 {len(scenarios)} 个场景：**")
        for sc in scenarios:
            st.markdown(f"- `{sc['id']}` **{sc['name']}** "
                        f"<span style='color:#888;font-size:12px;'>"
                        f"priority={sc.get('priority','')} pre={sc.get('precondition','')[:30]}"
                        f"</span>", unsafe_allow_html=True)
            steps = kg.list_steps_of(sc["id"])
            if steps:
                steps_html = "<ol style='margin-top:4px;'>"
                for st_ in steps:
                    steps_html += (
                        f"<li><code>{st_['action']}</code> → {st_['target']}"
                        f"{' = ' + repr(st_['value']) if st_['value'] else ''}"
                        f" <span style='color:#aaa;'>— {st_['description']}</span></li>"
                    )
                steps_html += "</ol>"
                st.markdown(steps_html, unsafe_allow_html=True)
    kg.close()


def main():
    os.makedirs("data",    exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    cfg = render_sidebar()

    st.title("🧪 4ga Boards 智能测试工具")
    st.caption("基于大模型的测试场景自动生成与智能执行平台 | Qdrant + Neo4j 知识底座")

    tab1, tab2, tab3 = st.tabs([
        "📋 任务一：场景生成",
        "🤖 任务二：测试执行",
        "🕸️ 知识图谱",
    ])
    with tab1:
        tab_generate(cfg)
    with tab2:
        tab_execute(cfg)
    with tab3:
        tab_graph()


if __name__ == "__main__":
    main()
