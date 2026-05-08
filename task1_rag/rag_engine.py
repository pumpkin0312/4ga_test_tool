"""
task1_rag/rag_engine.py
文档分块 → 向量化 → 构建 FAISS 索引 → 提供相似度检索接口
"""

import pickle
import numpy as np
from pathlib import Path
from rich.console import Console

console = Console(legacy_windows=False)


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    """将长文本切分成带重叠的小块"""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


class RAGEngine:
    """
    基于 sentence-transformers + FAISS 的本地 RAG 引擎。
    首次运行时构建索引并缓存，之后直接加载缓存。
    """

    def __init__(self,
                 store_path: str = "data/vector_store",
                 model_name: str = "all-MiniLM-L6-v2",
                 chunk_size: int = 600,
                 chunk_overlap: int = 80):
        self.store_path   = Path(store_path)
        self.model_name   = model_name
        self.chunk_size   = chunk_size
        self.chunk_overlap = chunk_overlap
        self.store_path.mkdir(parents=True, exist_ok=True)

        self._model  = None          # 懒加载，首次检索时才初始化
        self._index  = None          # FAISS 索引
        self._chunks: list[dict] = []  # [{text, source_title, source_url}]

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
                raise ImportError("请执行: pip install sentence-transformers faiss-cpu")
        return self._model

    # ── 索引构建 ──────────────────────────────────────────────────────────────

    def build_index(self, pages: list[dict]) -> None:
        """从文档页面列表构建向量索引"""
        import faiss

        console.print("[cyan]开始构建向量索引...[/cyan]")

        # 1. 分块
        self._chunks = []
        for page in pages:
            full_text = f"{page.get('title', '')}\n{page.get('content', '')}"
            for chunk in chunk_text(full_text, self.chunk_size, self.chunk_overlap):
                if len(chunk.strip()) > 30:
                    self._chunks.append({
                        "text":         chunk.strip(),
                        "source_title": page.get("title", ""),
                        "source_url":   page.get("url", ""),
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

        # 3. 构建 FAISS 索引
        dim = embeddings.shape[1]
        self._index = faiss.IndexFlatIP(dim)   # 内积索引
        self._index.add(embeddings)

        # 4. 持久化
        self._save(embeddings)
        console.print(f"[green]向量索引构建完成 | 维度={dim} | 向量数={len(self._chunks)}[/green]")

    def _save(self, embeddings: np.ndarray) -> None:
        import faiss
        faiss.write_index(self._index, str(self.store_path / "index.faiss"))
        with open(self.store_path / "chunks.pkl", "wb") as f:
            pickle.dump(self._chunks, f)
        console.print(f"[dim]索引已保存至 {self.store_path}[/dim]")

    # ── 索引加载 ──────────────────────────────────────────────────────────────

    def load_index(self) -> bool:
        """尝试从磁盘加载已有索引，成功返回 True"""
        import faiss
        idx_path    = self.store_path / "index.faiss"
        chunks_path = self.store_path / "chunks.pkl"
        if idx_path.exists() and chunks_path.exists():
            self._index = faiss.read_index(str(idx_path))
            with open(chunks_path, "rb") as f:
                self._chunks = pickle.load(f)
            console.print(f"[green]向量索引加载完成，共 {len(self._chunks)} 个块[/green]")
            return True
        return False

    # ── 检索接口 ──────────────────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """
        输入查询文本，返回最相关的 top_k 个文本块。
        每个块包含：text / source_title / source_url / score
        """
        if self._index is None:
            raise RuntimeError("索引未就绪，请先调用 build_index() 或 load_index()")

        query_vec = self.model.encode([query], normalize_embeddings=True)
        query_vec = np.array(query_vec, dtype=np.float32)
        scores, indices = self._index.search(query_vec, top_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if 0 <= idx < len(self._chunks):
                chunk = self._chunks[idx].copy()
                chunk["score"] = float(score)
                results.append(chunk)
        return results

    def get_context(self, query: str, top_k: int = 5) -> str:
        """
        检索后将结果拼接成供 LLM 使用的上下文字符串
        """
        chunks = self.retrieve(query, top_k)
        if not chunks:
            return ""
        parts = []
        for i, c in enumerate(chunks, 1):
            parts.append(
                f"[参考片段 {i} | 来源: {c['source_title']}]\n{c['text']}"
            )
        return "\n\n---\n\n".join(parts)


# ── 单独运行测试 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from config import DATA_DIR, VECTOR_DB_PATH, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP, DOCS_BASE_URL
    from task1_rag.crawler import DocsCrawler

    engine = RAGEngine(VECTOR_DB_PATH, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP)

    if not engine.load_index():
        crawler = DocsCrawler(DOCS_BASE_URL, DATA_DIR)
        pages   = crawler.load_cached() or crawler.crawl()
        engine.build_index(pages)

    # 测试检索
    for query in ["如何创建卡片", "登录注册", "列表管理"]:
        print(f"\n查询: {query}")
        for r in engine.retrieve(query, top_k=2):
            print(f"  [{r['score']:.3f}] {r['source_title']}: {r['text'][:80]}...")
