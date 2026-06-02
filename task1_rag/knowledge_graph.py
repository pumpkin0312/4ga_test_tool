"""
task1_rag/knowledge_graph.py
功能点 / 测试场景 / 操作步骤 的关系图存储。

模型（Cypher 语义）：
    (:Category {name})
        ↑ BELONGS_TO
    (:Feature {id, name, description})
        ↓ HAS_SCENARIO
    (:Scenario {id, name, priority})
        ↓ HAS_STEP
    (:Step {idx, action, target, value, description})

后端：
- 默认 Neo4j（bolt://localhost:7687），需 Docker 启动服务
- 连不上时自动降级为 networkx（嵌入式，无外部依赖）

用途：
- 任务一：完成场景生成后调 ingest()，把关系写入图
- 任务二：可被规划/验证模块查询：某场景的所有步骤、某功能的所有场景、跨场景的共享前置等
- 答辩：UI 提供图谱可视化，展示"功能点—场景—步骤"层级关系
"""

import json
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console(legacy_windows=False)


# ══════════════════════════════════════════════════════════════════════════════
# 接口基类
# ══════════════════════════════════════════════════════════════════════════════

class _GraphBackend:
    name = "none"

    def ingest(self, features: list[dict], scenarios: list[dict]) -> None: ...
    def list_features(self) -> list[dict]: ...
    def list_scenarios_of(self, feature_id: str) -> list[dict]: ...
    def list_steps_of(self, scenario_id: str) -> list[dict]: ...
    def stats(self) -> dict: ...
    def export_for_visualization(self) -> dict: ...
    def close(self) -> None: ...


# ══════════════════════════════════════════════════════════════════════════════
# Neo4j 后端（首选）
# ══════════════════════════════════════════════════════════════════════════════

class _Neo4jBackend(_GraphBackend):
    name = "neo4j"

    def __init__(self, uri: str, user: str, password: str):
        from neo4j import GraphDatabase   # 在 try/except 外层 import 失败由调用方处理
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._driver.verify_connectivity()
        console.print(f"[green]✓ Neo4j 已连接: {uri}[/green]")

    def ingest(self, features, scenarios):
        with self._driver.session() as s:
            # 清空旧数据
            s.run("MATCH (n) DETACH DELETE n")

            # Feature + Category
            for f in features:
                s.run("""
                    MERGE (c:Category {name: $cat})
                    MERGE (f:Feature {id: $id})
                      SET f.name = $name, f.description = $desc
                    MERGE (f)-[:BELONGS_TO]->(c)
                """, id=f["id"], name=f.get("name", ""),
                     desc=f.get("description", ""),
                     cat=f.get("category", "Misc"))

            # Scenario + Step
            for sc in scenarios:
                s.run("""
                    MATCH (f:Feature {id: $fid})
                    MERGE (sc:Scenario {id: $sid})
                      SET sc.name = $sname, sc.priority = $prio, sc.precondition = $pre
                    MERGE (f)-[:HAS_SCENARIO]->(sc)
                """, fid=sc.get("feature_id", ""),
                     sid=sc["id"], sname=sc.get("name", ""),
                     prio=sc.get("priority", "medium"),
                     pre=sc.get("precondition", ""))

                for i, step in enumerate(sc.get("steps", []), 1):
                    s.run("""
                        MATCH (sc:Scenario {id: $sid})
                        MERGE (st:Step {scenario_id: $sid, idx: $idx})
                          SET st.action = $action, st.target = $target,
                              st.value = $value, st.description = $desc
                        MERGE (sc)-[:HAS_STEP {order: $idx}]->(st)
                    """, sid=sc["id"], idx=i,
                         action=step.get("action", ""),
                         target=step.get("target", ""),
                         value=step.get("value", ""),
                         desc=step.get("description", ""))
        console.print(f"[green]Neo4j 已写入：{len(features)} 个功能点 + {len(scenarios)} 个场景[/green]")

    def list_features(self):
        with self._driver.session() as s:
            res = s.run("""
                MATCH (f:Feature)-[:BELONGS_TO]->(c:Category)
                RETURN f.id AS id, f.name AS name, f.description AS description,
                       c.name AS category
                ORDER BY f.id
            """)
            return [r.data() for r in res]

    def list_scenarios_of(self, feature_id: str):
        with self._driver.session() as s:
            res = s.run("""
                MATCH (f:Feature {id: $fid})-[:HAS_SCENARIO]->(sc:Scenario)
                RETURN sc.id AS id, sc.name AS name, sc.priority AS priority,
                       sc.precondition AS precondition
            """, fid=feature_id)
            return [r.data() for r in res]

    def list_steps_of(self, scenario_id: str):
        with self._driver.session() as s:
            res = s.run("""
                MATCH (sc:Scenario {id: $sid})-[r:HAS_STEP]->(st:Step)
                RETURN st.idx AS idx, st.action AS action, st.target AS target,
                       st.value AS value, st.description AS description
                ORDER BY r.order
            """, sid=scenario_id)
            return [r.data() for r in res]

    def stats(self):
        # 拆成独立 COUNT 查询，空库时也能返回 0 而不是 None
        with self._driver.session() as s:
            def _count(label: str) -> int:
                rec = s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
                return int(rec["c"]) if rec else 0
            return {
                "categories": _count("Category"),
                "features":   _count("Feature"),
                "scenarios":  _count("Scenario"),
                "steps":      _count("Step"),
            }

    def export_for_visualization(self):
        nodes, edges = [], []
        with self._driver.session() as s:
            res = s.run("""
                MATCH (a)-[r]->(b)
                RETURN id(a) AS sid, labels(a) AS sl, properties(a) AS sp,
                       type(r) AS rel,
                       id(b) AS tid, labels(b) AS tl, properties(b) AS tp
            """)
            seen = set()
            for row in res:
                for nid, labels, props in [(row["sid"], row["sl"], row["sp"]),
                                            (row["tid"], row["tl"], row["tp"])]:
                    if nid in seen:
                        continue
                    seen.add(nid)
                    nodes.append({
                        "id":    str(nid),
                        "label": labels[0] if labels else "Node",
                        "name":  props.get("name") or props.get("id") or "?",
                    })
                edges.append({"source": str(row["sid"]),
                              "target": str(row["tid"]),
                              "type":   row["rel"]})
        return {"nodes": nodes, "edges": edges}

    def close(self):
        try:
            self._driver.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# networkx 兜底后端（无外部依赖，纯本地内存 + 文件持久化）
# ══════════════════════════════════════════════════════════════════════════════

class _NetworkXBackend(_GraphBackend):
    name = "networkx"
    DEFAULT_PATH = "data/knowledge_graph.json"

    def __init__(self, persist_path: str = DEFAULT_PATH):
        import networkx as nx
        self._nx   = nx
        self._g    = nx.MultiDiGraph()
        self._path = Path(persist_path)
        if self._path.exists():
            self._load()
        console.print(f"[yellow]Neo4j 不可用，使用 networkx 嵌入式图谱（持久化：{self._path}）[/yellow]")

    def ingest(self, features, scenarios):
        self._g.clear()

        for f in features:
            cat = f.get("category", "Misc")
            self._g.add_node(("Category", cat), label="Category", name=cat)
            self._g.add_node(
                ("Feature", f["id"]),
                label="Feature", name=f.get("name", ""),
                description=f.get("description", ""),
                category=cat,
            )
            self._g.add_edge(("Feature", f["id"]), ("Category", cat), type="BELONGS_TO")

        for sc in scenarios:
            fid = sc.get("feature_id", "")
            self._g.add_node(
                ("Scenario", sc["id"]),
                label="Scenario", name=sc.get("name", ""),
                priority=sc.get("priority", "medium"),
                precondition=sc.get("precondition", ""),
            )
            if ("Feature", fid) in self._g:
                self._g.add_edge(("Feature", fid), ("Scenario", sc["id"]), type="HAS_SCENARIO")

            for i, step in enumerate(sc.get("steps", []), 1):
                key = ("Step", f"{sc['id']}#{i}")
                self._g.add_node(key, label="Step", idx=i,
                                 action=step.get("action", ""),
                                 target=step.get("target", ""),
                                 value=step.get("value", ""),
                                 description=step.get("description", ""))
                self._g.add_edge(("Scenario", sc["id"]), key, type="HAS_STEP", order=i)

        self._persist()
        console.print(f"[green]networkx 已写入：{len(features)} 功能点 + {len(scenarios)} 场景[/green]")

    def list_features(self):
        out = []
        for n, data in self._g.nodes(data=True):
            if data.get("label") == "Feature":
                out.append({
                    "id":          n[1],
                    "name":        data.get("name", ""),
                    "description": data.get("description", ""),
                    "category":    data.get("category", ""),
                })
        return sorted(out, key=lambda x: x["id"])

    def list_scenarios_of(self, feature_id):
        out = []
        src = ("Feature", feature_id)
        if src not in self._g:
            return out
        for _, t, d in self._g.out_edges(src, data=True):
            if d.get("type") == "HAS_SCENARIO" and t[0] == "Scenario":
                data = self._g.nodes[t]
                out.append({
                    "id":           t[1],
                    "name":         data.get("name", ""),
                    "priority":     data.get("priority", ""),
                    "precondition": data.get("precondition", ""),
                })
        return out

    def list_steps_of(self, scenario_id):
        out = []
        src = ("Scenario", scenario_id)
        if src not in self._g:
            return out
        for _, t, d in self._g.out_edges(src, data=True):
            if d.get("type") == "HAS_STEP":
                data = self._g.nodes[t]
                out.append({
                    "idx":         data.get("idx", 0),
                    "action":      data.get("action", ""),
                    "target":      data.get("target", ""),
                    "value":       data.get("value", ""),
                    "description": data.get("description", ""),
                })
        return sorted(out, key=lambda x: x["idx"])

    def stats(self):
        counts = {"Category": 0, "Feature": 0, "Scenario": 0, "Step": 0}
        for _, data in self._g.nodes(data=True):
            lbl = data.get("label")
            if lbl in counts:
                counts[lbl] += 1
        return {
            "categories": counts["Category"],
            "features":   counts["Feature"],
            "scenarios":  counts["Scenario"],
            "steps":      counts["Step"],
        }

    def export_for_visualization(self):
        nodes = [{
            "id":    f"{n[0]}::{n[1]}",
            "label": data.get("label", "Node"),
            "name":  data.get("name") or n[1],
        } for n, data in self._g.nodes(data=True)]

        edges = [{
            "source": f"{u[0]}::{u[1]}",
            "target": f"{v[0]}::{v[1]}",
            "type":   d.get("type", "REL"),
        } for u, v, d in self._g.edges(data=True)]

        return {"nodes": nodes, "edges": edges}

    # ── 持久化（JSON）─────────────────────────────────────────────────────────

    def _persist(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "nodes": [
                {"id": f"{n[0]}::{n[1]}", **attrs}
                for n, attrs in self._g.nodes(data=True)
            ],
            "edges": [
                {"source": f"{u[0]}::{u[1]}", "target": f"{v[0]}::{v[1]}", **attrs}
                for u, v, attrs in self._g.edges(data=True)
            ],
        }
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            # 重建图节点边
            for n in data.get("nodes", []):
                # n["id"] 形如 "Feature::f001"，拆回 tuple key
                kind, _, key = n["id"].partition("::")
                attrs = {k: v for k, v in n.items() if k != "id"}
                self._g.add_node((kind, key), **attrs)
            for e in data.get("edges", []):
                sk, _, sv = e["source"].partition("::")
                tk, _, tv = e["target"].partition("::")
                attrs = {k: v for k, v in e.items() if k not in ("source", "target")}
                self._g.add_edge((sk, sv), (tk, tv), **attrs)
        except Exception as e:
            console.print(f"[yellow]networkx 缓存加载失败：{e}[/yellow]")

    def close(self):
        pass


# ══════════════════════════════════════════════════════════════════════════════
# 工厂：选 Neo4j，失败则 networkx
# ══════════════════════════════════════════════════════════════════════════════

class KnowledgeGraph:
    """统一入口，封装"Neo4j 优先 + networkx 兜底"逻辑"""

    def __init__(self,
                 neo4j_uri:  str = "bolt://localhost:7687",
                 neo4j_user: str = "neo4j",
                 neo4j_pass: str = "test1234",
                 persist_path: str = "data/knowledge_graph.json"):
        self.backend: _GraphBackend
        try:
            self.backend = _Neo4jBackend(neo4j_uri, neo4j_user, neo4j_pass)
        except Exception as e:
            console.print(f"[yellow]Neo4j 连接失败：{e}[/yellow]")
            self.backend = _NetworkXBackend(persist_path)

    # 直接代理给具体 backend
    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)

    @property
    def backend_name(self) -> str:
        return self.backend.name
