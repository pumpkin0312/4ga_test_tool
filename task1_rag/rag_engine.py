"""
task1_rag/rag_engine.py
文档分块 → 嵌入 → 存入 Qdrant 向量库 → 提供相似度检索。

后端默认走 Qdrant（嵌入式持久化模式，无需 Docker）。
若 Qdrant 不可用，自动回退到 FAISS（保留原有实现作为兜底）。
"""

import pickle
import numpy as np
from pathlib import Path
from rich.console import Console

console = Console(legacy_windows=False)


# ── 文档分块工具 ──────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    """将长文本切分成带重叠的小块"""
    if not text or not text.strip():
        return []
    if len(text) <= chunk_size:
        return [text]

    # 防御：确保 overlap < chunk_size，否则死循环（Bug-8）
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


def chunk_by_sections(text: str, max_chunk_size: int = 800, overlap: int = 80) -> list[str]:
    """按 markdown 标题分块，保留语义完整性；超长 section 回退到 chunk_text()（Bug-7）"""
    import re
    sections = re.split(r'\n(?=#{1,3}\s)', text)
    chunks: list[str] = []
    current = ""
    for section in sections:
        if len(current) + len(section) > max_chunk_size and current:
            chunks.append(current.strip())
            current = section
        else:
            current += "\n" + section
    if current.strip():
        chunks.append(current.strip())

    final_chunks: list[str] = []
    for chunk in chunks:
        if len(chunk) > max_chunk_size:
            final_chunks.extend(chunk_text(chunk, max_chunk_size, overlap))
        else:
            final_chunks.append(chunk)
    return final_chunks


# ══════════════════════════════════════════════════════════════════════════════
# RAGEngine：Qdrant 优先 + FAISS fallback
# ══════════════════════════════════════════════════════════════════════════════

class RAGEngine:
    """
    向量检索引擎。
    - 默认使用 Qdrant 嵌入式持久化（QdrantClient(path=...)）
    - 若 qdrant-client 未安装或初始化失败，自动回退到 FAISS
    """

    COLLECTION = "docs"

    def __init__(self,
                 store_path: str = "data/vector_store",
                 model_name: str = "all-MiniLM-L6-v2",
                 chunk_size: int = 600,
                 chunk_overlap: int = 80,
                 backend: str = "qdrant"):
        self.store_path    = Path(store_path)
        self.model_name    = model_name
        self.chunk_size    = chunk_size
        self.chunk_overlap = chunk_overlap
        self.store_path.mkdir(parents=True, exist_ok=True)

        self._model    = None          # 懒加载
        self._chunks: list[dict] = []  # 元数据 [{text, source_title, source_url, category}]
        self._dim      = 0

        # 后端选择
        self.backend = backend.lower()
        self._qdrant = None
        self._faiss  = None

    # ── 模型懒加载 ────────────────────────────────────────────────────────────

    @property
    def model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                console.print(f"[cyan]加载嵌入模型: {self.model_name}（首次运行会自动下载）[/cyan]")
                self._model = SentenceTransformer(self.model_name)
                console.print("[green]嵌入模型加载完成[/green]")
            except ImportError:
                raise ImportError("请执行: pip install sentence-transformers")
        return self._model

    # ── 后端初始化 ────────────────────────────────────────────────────────────

    def _init_qdrant(self):
        """嵌入式持久化模式：data/vector_store/qdrant/"""
        try:
            from qdrant_client import QdrantClient
            qdrant_path = self.store_path / "qdrant"
            qdrant_path.mkdir(parents=True, exist_ok=True)
            self._qdrant = QdrantClient(path=str(qdrant_path))
            return True
        except Exception as e:
            console.print(f"[yellow]Qdrant 初始化失败：{e}，回退到 FAISS[/yellow]")
            self.backend = "faiss"
            return False

    # ── 索引构建 ──────────────────────────────────────────────────────────────

    def build_index(self, pages: list[dict]) -> None:
        """从文档页面列表构建向量索引"""
        console.print("[cyan]开始构建向量索引...[/cyan]")

        # 1. 分块（Bug-7: 优先按 markdown 标题分块，保留语义完整性）
        self._chunks = []
        for page in pages:
            full_text = f"{page.get('title', '')}\n{page.get('content', '')}"
            for chunk in chunk_by_sections(full_text, self.chunk_size, self.chunk_overlap):
                if len(chunk.strip()) > 30:
                    self._chunks.append({
                        "text":         chunk.strip(),
                        "source_title": page.get("title", ""),
                        "source_url":   page.get("url", ""),
                        "category":     page.get("category", ""),
                    })
        console.print(f"  共 {len(self._chunks)} 个文本块，开始向量化...")

        # 2. 向量化（归一化后用内积 = 余弦相似度）
        texts = [c["text"] for c in self._chunks]
        embeddings = self.model.encode(
            texts,
            batch_size=32,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        embeddings = np.array(embeddings, dtype=np.float32)
        self._dim = embeddings.shape[1]

        # 3. 入库（按 backend 选择）
        if self.backend == "qdrant" and self._init_qdrant():
            self._build_qdrant(embeddings)
        else:
            self._build_faiss(embeddings)
            self.backend = "faiss"

        # 4. 持久化元数据（chunks 文本）
        with open(self.store_path / "chunks.pkl", "wb") as f:
            pickle.dump({"chunks": self._chunks, "dim": self._dim, "backend": self.backend}, f)
        console.print(
            f"[green]向量索引构建完成 | backend={self.backend} | "
            f"维度={self._dim} | 向量数={len(self._chunks)}[/green]"
        )

    def _build_qdrant(self, embeddings: np.ndarray):
        """Qdrant 入库"""
        from qdrant_client.http.models import Distance, VectorParams, PointStruct

        # 重建 collection
        try:
            self._qdrant.delete_collection(self.COLLECTION)
        except Exception:
            pass
        self._qdrant.create_collection(
            collection_name=self.COLLECTION,
            vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
        )
        # 批量 upsert
        points = [
            PointStruct(
                id=i,
                vector=vec.tolist(),
                payload={
                    "text":         self._chunks[i]["text"],
                    "source_title": self._chunks[i]["source_title"],
                    "source_url":   self._chunks[i]["source_url"],
                    "category":     self._chunks[i]["category"],
                },
            )
            for i, vec in enumerate(embeddings)
        ]
        # 分批避免单批过大
        BATCH = 256
        for i in range(0, len(points), BATCH):
            self._qdrant.upsert(collection_name=self.COLLECTION, points=points[i:i + BATCH])
        console.print(f"[dim]Qdrant 已写入 {len(points)} 个向量[/dim]")

    def _build_faiss(self, embeddings: np.ndarray):
        """FAISS 兜底实现"""
        import faiss
        self._faiss = faiss.IndexFlatIP(self._dim)
        self._faiss.add(embeddings)
        faiss.write_index(self._faiss, str(self.store_path / "index.faiss"))
        console.print("[dim]FAISS 索引已保存[/dim]")

    # ── 索引加载 ──────────────────────────────────────────────────────────────

    def load_index(self) -> bool:
        """尝试加载已构建的索引，成功返回 True"""
        meta_path = self.store_path / "chunks.pkl"
        if not meta_path.exists():
            return False
        try:
            with open(meta_path, "rb") as f:
                data = pickle.load(f)
            self._chunks = data["chunks"]
            self._dim    = data["dim"]
            saved_backend = data.get("backend", "faiss")

            if saved_backend == "qdrant" and self.backend == "qdrant":
                if not self._init_qdrant():
                    return False
                # 校验 collection 存在
                cols = [c.name for c in self._qdrant.get_collections().collections]
                if self.COLLECTION not in cols:
                    return False
            else:
                # FAISS 加载
                import faiss
                idx_path = self.store_path / "index.faiss"
                if not idx_path.exists():
                    return False
                self._faiss = faiss.read_index(str(idx_path))
                self.backend = "faiss"

            console.print(
                f"[green]向量索引加载完成 | backend={self.backend} | "
                f"共 {len(self._chunks)} 个块[/green]"
            )
            return True
        except Exception as e:
            console.print(f"[yellow]索引加载失败：{e}[/yellow]")
            return False

    # ── 检索接口 ──────────────────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """检索 top_k 个相关块"""
        query_vec = self.model.encode([query], normalize_embeddings=True)
        query_vec = np.array(query_vec, dtype=np.float32)[0]

        if self.backend == "qdrant" and self._qdrant is not None:
            hits = self._qdrant.query_points(
                collection_name=self.COLLECTION,
                query=query_vec.tolist(),
                limit=top_k,
            ).points
            return [{
                "text":         h.payload.get("text", ""),
                "source_title": h.payload.get("source_title", ""),
                "source_url":   h.payload.get("source_url", ""),
                "category":     h.payload.get("category", ""),
                "score":        float(h.score),
            } for h in hits]

        # FAISS 路径
        if self._faiss is None:
            raise RuntimeError("索引未就绪，请先调用 build_index() 或 load_index()")
        scores, indices = self._faiss.search(np.array([query_vec], dtype=np.float32), top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if 0 <= idx < len(self._chunks):
                chunk = self._chunks[idx].copy()
                chunk["score"] = float(score)
                results.append(chunk)
        return results

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float, dict]]:
        """返回原始 (text, score, meta) 元组，供上层做 chunk 级去重（Bug-11）"""
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

    def get_context(self, query: str, top_k: int = 5) -> str:
        """检索结果拼接成上下文字符串供 LLM 使用；中英双语查询扩展 + 去重排序（Bug-7）"""
        # 中文查询 + 英文翻译查询，合并结果
        EN_MAP = {
            "创建": "create", "项目": "project", "看板": "board",
            "卡片": "card", "删除": "delete", "列表": "list",
            "编辑": "edit", "移动": "move", "导入": "import",
            "管理": "manage", "设置": "settings", "通知": "notification",
            "用户": "user", "登录": "login", "登出": "logout",
            "注册": "register", "密码": "password", "附件": "attachment",
            "评论": "comment", "标签": "label", "成员": "member",
        }
        en_query = query
        for cn, en in EN_MAP.items():
            en_query = en_query.replace(cn, en)

        cn_results = self.search(query, top_k=top_k)
        en_results = self.search(en_query, top_k=top_k) if en_query != query else []

        # 合并去重（按 chunk 文本 hash），按 score 降序
        seen: set[int] = set()
        merged: list[tuple[str, float, dict]] = []
        for text, score, meta in cn_results + en_results:
            h = hash(text.strip())
            if h not in seen:
                seen.add(h)
                merged.append((text, score, meta))
        merged.sort(key=lambda x: x[1], reverse=True)

        if not merged:
            return ""
        return "\n\n---\n\n".join(
            f"[参考片段 {i + 1} | 来源: {meta['source_title']}]\n{text}"
            for i, (text, _score, meta) in enumerate(merged[:top_k])
        )


# ── 单独运行测试 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from config import (DATA_DIR, VECTOR_DB_PATH, EMBEDDING_MODEL,
                        CHUNK_SIZE, CHUNK_OVERLAP, DOCS_BASE_URL, LOCAL_DOCS_DIR)
    from task1_rag.crawler import DocsCrawler

    engine = RAGEngine(VECTOR_DB_PATH, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP)
    if not engine.load_index():
        crawler = DocsCrawler(DOCS_BASE_URL, DATA_DIR)
        pages = crawler.load_local_markdown(LOCAL_DOCS_DIR) or crawler.crawl()
        engine.build_index(pages)

    for query in ["如何创建卡片", "登录注册", "列表管理"]:
        print(f"\n查询: {query}")
        for r in engine.retrieve(query, top_k=2):
            print(f"  [{r['score']:.3f}] {r['source_title']}: {r['text'][:80]}...")
