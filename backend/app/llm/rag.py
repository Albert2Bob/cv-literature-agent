"""
RAG 检索管道 —— LangChain + Chroma + BM25 + Cross-Encoder 重排序
==============================================================
检索架构：

    用户查询
      → [向量检索 (Chroma + BGE) + BM25 关键词检索]   双路召回
      → 动态加权 RRF 融合
      → Cross-Encoder 重排序
      → 输出 Top-K 参考片段

本文件（阶段 4 已有）在「前端 RAG 文件管理」需求下做了三点改造：

  1. **新增 per-document 增删能力**：`sync_document()` / `remove_document()`，
     只动某个文档的切片，不需要全量重建（全量重建要重算全部 embedding，
     在管理页面上每传一个文件就重建一次是不可接受的）。
  2. **collection 名固定**：`Chroma(persist_directory=..., collection_name=...)`
     才绑定到稳定的持久化目录，这样进程重启后能直接命中已有集合继续增量更新。
  3. **切分函数支持内存文本**：`split_text()` 可直接切分上传内容，
     不必先落盘成文件。

向量库与 MySQL 的关系（由 app/rag_manager.py 统一编排）：
    MySQL 存权威记录与切片原文；Chroma 存向量。一次解析 → 两次保存。

本文件不做 MySQL 操作（避免分层混乱），只负责「文本 → 切片 → 向量」。
"""
import json
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

# HuggingFace 镜像加速（模型已缓存在本地时不会触发下载）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from langchain.tools import tool
from langchain.text_splitter import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document as LCDocument
from langchain_huggingface import HuggingFaceEmbeddings

from app.logging_conf import get_logger, shorten

log = get_logger("llm.rag")

# ==============================
#  路径与常量配置
# ==============================
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCUMENTS_DIR = os.path.join(BACKEND_DIR, "documents")   # 兜底用的 Markdown 目录
CHROMA_DIR = os.path.join(BACKEND_DIR, "chroma_db")      # Chroma 向量库持久化目录

# 固定的 collection 名。必须固定，否则增量更新拿不到已有集合。
COLLECTION_NAME = "lsb_rag_documents"

EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
RERANKER_MODEL = "BAAI/bge-reranker-base"

CHUNK_SIZE = 600        # 二次切分的块大小
CHUNK_OVERLAP = 50      # 块间重叠
LONG_CHUNK_THRESHOLD = 600   # 超过此长度才做二次切分

VECTOR_TOP_K = 10       # 向量检索召回数量
BM25_TOP_K = 10         # BM25 召回数量
FUSION_TOP_K = 5        # RRF 融合后候选数量
RERANK_TOP_K = 3        # 最终重排序后返回数量
RRF_K = 60              # RRF 平滑常数


# ==============================
#  中文友好分词（BM25 用）
# ==============================

def tokenize(text: str) -> List[str]:
    """
    中英混合分词：
      - 连续的英文字母/数字作为一个词（保持术语与缩写完整：ResNet、mAP50）
      - 连续的 CJK 汉字切成 bigram（"感受野" → ["感受", "受野"]），
        因为中文没有空格，直接 split() 会让整句变成单个 token，BM25 失效
    """
    tokens: List[str] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            tokens.append(buf.lower())
            buf = ""

    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":   # CJK 统一汉字
            flush()
            tokens.append(ch)
        elif ch.isalnum():
            buf += ch
        else:
            flush()

    flush()

    cjk = [t for t in tokens if len(t) == 1 and "\u4e00" <= t <= "\u9fff"]
    bigrams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    word_tokens = [t for t in tokens if not (len(t) == 1 and "\u4e00" <= t <= "\u9fff")]

    return cjk + bigrams + word_tokens


# ==============================
#  文档切分
# ==============================

_MARKDOWN_SPLITTER = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "文档标题"), ("##", "问题标题")],
    strip_headers=False,
)
_CHAR_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", "。", "，", " ", ""],
)


def split_text(text: str, source: str = "") -> List[LCDocument]:
    """
    把一段文本切成带元数据的 LangChain Document 列表。

    策略：先按 Markdown 标题（# / ##）切，过长的块再用递归字符切分。
    对 .txt / .pdf / .docx 提取出来的纯文本同样适用（没有标题时自然退化为整段切分）。
    """
    if not (text or "").strip():
        return []

    try:
        header_chunks = _MARKDOWN_SPLITTER.split_text(text)
    except Exception:  # noqa: BLE001 - 文本不规范时退化为纯字符切分
        header_chunks = [LCDocument(page_content=text)]

    docs: List[LCDocument] = []
    for chunk in header_chunks:
        meta = {"source": source}
        if getattr(chunk, "metadata", None):
            meta.update({k: v for k, v in chunk.metadata.items() if v})

        if len(chunk.page_content) < LONG_CHUNK_THRESHOLD:
            docs.append(LCDocument(page_content=chunk.page_content, metadata=meta))
        else:
            for sub in _CHAR_SPLITTER.split_documents([chunk]):
                sub_meta = dict(meta)
                if getattr(sub, "metadata", None):
                    sub_meta.update({k: v for k, v in sub.metadata.items() if v})
                docs.append(LCDocument(page_content=sub.page_content, metadata=sub_meta))

    # 丢掉纯空白切片
    return [d for d in docs if d.page_content.strip()]


def list_disk_documents() -> List[dict]:
    """
    读取 documents/ 目录下的 Markdown 文件（兜底数据源）。

    仅用于「向量库为空且 MySQL 也没有记录」时的首次初始化。
    """
    from pathlib import Path

    result = []
    for path in sorted(Path(DOCUMENTS_DIR).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = ""
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        result.append({
            "name": path.name,
            "title": title or path.stem,
            "extension": "md",
            "size": path.stat().st_size,
            "content": text,
        })
    return result


# ── 兼容旧接口（早期版本用「文档目录指纹」判断是否重建索引） ──────────

LEGACY_COLLECTION_NAME = "cv_research_rag"

# 索引元信息标记：在集合里存一条特殊「文档」，用来判断集合是否已经建好、
# 以及是用哪个 embedding 模型建的。有了它，进程重启时就不必重算全部向量。
INDEX_MARKER_SOURCE = "__index_meta__"
INDEX_MARKER_ID = "__index_meta__::0"


def compute_documents_fingerprint(doc_dir: str = DOCUMENTS_DIR) -> str:
    """
    计算 documents/ 目录的指纹（文件名+大小+修改时间）。

    保留此函数仅为兼容早期验证脚本；现行方案以 MySQL 记录为准，
    不再依赖目录指纹判断是否重建。
    """
    from pathlib import Path

    parts = []
    for md_path in sorted(Path(doc_dir).glob("*.md")):
        stat = md_path.stat()
        parts.append(f"{md_path.name}:{stat.st_size}:{int(stat.st_mtime)}")
    return "|".join(parts)


def load_and_split_documents(doc_dir: str = DOCUMENTS_DIR, verbose: bool = True) -> List[LCDocument]:
    """
    读取并切分 documents/ 目录下的全部 Markdown（兼容旧接口）。

    Returns:
        LangChain Document 列表（已带 source 元数据）
    """
    from pathlib import Path

    docs: List[LCDocument] = []
    paths = sorted(Path(doc_dir).glob("*.md"))
    for path in paths:
        docs.extend(split_text(path.read_text(encoding="utf-8"), source=path.name))

    if verbose:
        log.info("已加载 %d 个 Markdown 文件，切分为 %d 个片段", len(paths), len(docs))
    return docs


# ==============================
#  RAG 引擎
# ==============================

class RAGEngine:
    """
    RAG 引擎（单例）：
      - Chroma 向量检索（BGE 中文小模型）
      - BM25 关键词检索（中文友好分词）
      - 加权 RRF 融合
      - Cross-Encoder 重排序（懒加载）
      - 支持按文档增量新增 / 删除

    线程安全：所有会改动向量库或索引的操作都在 _write_lock 内串行执行。
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self, verbose: bool = True):
        os.makedirs(CHROMA_DIR, exist_ok=True)
        self.verbose = verbose
        self._write_lock = threading.RLock()

        # 文件名 → 该文档的切片（自己维护，删除时才能精确摘除）
        self._docs_by_source: Dict[str, List[LCDocument]] = {}
        self._bm25_retriever = None
        self._vector_store = None
        self._embed_model = None
        self._reranker = None

        if verbose:
            log.info("初始化 RAG 引擎: collection=%s dir=%s 嵌入模型=%s",
                     COLLECTION_NAME, CHROMA_DIR, EMBEDDING_MODEL)

    # ---------- 懒加载 ----------

    def _get_embed_model(self):
        if self._embed_model is None:
            log.info("加载 Embedding 模型 %s（首次较慢，之后走本地缓存）...", EMBEDDING_MODEL)
            started = time.perf_counter()
            self._embed_model = HuggingFaceEmbeddings(
                model_name=EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},   # 有 GPU 时可改为 "cuda"
                encode_kwargs={"normalize_embeddings": True},
            )
            log.success("Embedding 模型就绪，耗时 %.1fs", time.perf_counter() - started)
        return self._embed_model

    def get_vector_store(self) -> Chroma:
        """获取（必要时创建）绑定了固定 collection 的向量库句柄。"""
        if self._vector_store is None:
            log.info("绑定向量库 collection=%s dir=%s", COLLECTION_NAME, CHROMA_DIR)
            self._vector_store = Chroma(
                collection_name=COLLECTION_NAME,
                embedding_function=self._get_embed_model(),
                persist_directory=CHROMA_DIR,
            )
        return self._vector_store

    def _get_reranker(self):
        """懒加载 Cross-Encoder 重排序模型。"""
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
                log.info("加载重排序模型 %s ...", RERANKER_MODEL)
                started = time.perf_counter()
                self._reranker = CrossEncoder(RERANKER_MODEL, device="cpu")
                log.success("重排序模型就绪，耗时 %.1fs", time.perf_counter() - started)
            except Exception as exc:  # noqa: BLE001
                log.warning("重排序不可用（%s），本次检索将跳过精排（精度可能下降）", exc)
                self._reranker = False   # False = 已尝试且失败，避免反复重试
        return self._reranker or None

    # ---------- 索引维护 ----------

    def _rebuild_bm25(self):
        """用当前全部切片重建 BM25 索引。"""
        all_docs = self.all_documents()
        # 索引元信息标记不是真实文档，不进 BM25 语料
        all_docs = [d for d in all_docs if d.metadata.get("source") != INDEX_MARKER_SOURCE]
        if all_docs:
            self._bm25_retriever = BM25Retriever.from_documents(all_docs, preprocess_func=tokenize)
            self._bm25_retriever.k = BM25_TOP_K
        else:
            self._bm25_retriever = None

    def index_document(self, name: str, text: str) -> List[LCDocument]:
        """
        把一个文档的切片写入向量库（若该文档已存在则先摘除旧切片）。

        Args:
            name: 文件名，作为 source 与删除依据
            text: 提取后的纯文本
        Returns:
            该文档新生成的切片列表
        """
        with self._write_lock:
            store = self.get_vector_store()

            # 先摘除该文档已有切片，避免重复入库
            self._delete_from_store(store, name)

            chunks = split_text(text, source=name)
            if chunks:
                ids = [f"{name}::{i}" for i in range(len(chunks))]
                store.add_documents(documents=chunks, ids=ids)

            self._docs_by_source[name] = chunks
            self._rebuild_bm25()

            log.success("文档已向量化: %s -> %d 个切片（BM25 语料 %d 条）",
                        name, len(chunks), self.chunk_count())
            return chunks

    def _delete_from_store(self, store: Chroma, name: str) -> int:
        """从向量库里删除某个文档的全部切片。返回删除条数。"""
        try:
            existing = store.get(where={"source": name})
            ids = (existing or {}).get("ids") or []
            if ids:
                store.delete(ids=ids)
            return len(ids)
        except Exception as exc:  # noqa: BLE001
            log.error("删除文档的向量失败: %s -> %s", name, exc, exc_info=True)
            return 0

    def remove_document(self, name: str) -> int:
        """从向量库与内存索引中移除某个文档。返回移除的切片数。"""
        with self._write_lock:
            removed = self._delete_from_store(self.get_vector_store(), name)
            self._docs_by_source.pop(name, None)
            self._rebuild_bm25()
            if removed:
                log.success("文档向量已移除: %s -> %d 个切片", name, removed)
            else:
                log.warning("文档在向量库中无切片可移除（可能本就没建索引）: %s", name)
            return removed

    def clear_all(self) -> None:
        """清空整个向量集合（全量重建用）。"""
        with self._write_lock:
            try:
                self.get_vector_store().delete_collection()
            except Exception:  # noqa: BLE001 - 集合不存在时忽略
                pass
            self._vector_store = None
            self._docs_by_source = {}
            self._bm25_retriever = None

    # ---------- 索引元信息标记 ----------

    def read_marker(self) -> Optional[dict]:
        """
        读取集合里的索引元信息标记。

        Returns:
            {"embedding_model":..., "chunks":...}；集合不存在或没有标记时返回 None
        """
        from langchain_core.documents import Document as _Doc

        try:
            got = self.get_vector_store().get(ids=[INDEX_MARKER_ID])
        except Exception:  # noqa: BLE001 - 集合不存在时 get 会抛错
            return None

        docs = (got or {}).get("documents") or []
        if not docs:
            return None
        try:
            return json.loads(docs[0])
        except (json.JSONDecodeError, TypeError):
            return None

    def write_marker(self, chunk_count: int) -> None:
        """写入/更新索引元信息标记。"""
        from langchain_core.documents import Document as _Doc

        store = self.get_vector_store()
        try:
            store.delete(ids=[INDEX_MARKER_ID])
        except Exception:  # noqa: BLE001
            pass
        store.add_documents(
            documents=[_Doc(
                page_content=json.dumps({
                    "embedding_model": EMBEDDING_MODEL,
                    "chunk_count": chunk_count,
                    "collection": COLLECTION_NAME,
                }, ensure_ascii=False),
                metadata={"source": INDEX_MARKER_SOURCE, "marker": True},
            )],
            ids=[INDEX_MARKER_ID],
        )

    def is_ready(self) -> bool:
        """集合是否已建好且用的就是当前 embedding 模型（→ 无需重建）。"""
        marker = self.read_marker()
        return bool(marker) and marker.get("embedding_model") == EMBEDDING_MODEL

    def load_from_pairs(self, pairs) -> int:
        """
        直接用「文档名 + 切片原文」填充内存索引与 BM25，**不重算 embedding**。

        用途：进程重启时，向量已经在磁盘上，只需把 BM25 与文件→切片映射
        恢复到内存即可。避免每次重启都重新向量化整个知识库。

        Args:
            pairs: [(name, [chunk_text, ...]), ...]
        Returns:
            载入的切片总数
        """
        with self._write_lock:
            self._docs_by_source = {}
            total = 0
            for name, texts in pairs:
                docs = [LCDocument(page_content=t, metadata={"source": name}) for t in texts]
                self._docs_by_source[name] = docs
                total += len(docs)
            self._rebuild_bm25()
            if self.verbose:
                log.info("从已有向量库载入内存索引: %d 个文档 / %d 个切片",
                         len(self._docs_by_source), total)
            return total

    def replace_from_documents(self, payload: List[dict]) -> int:
        """
        用给定文档集合**全量重建**向量库。

        Args:
            payload: [{"name":..., "content":...}, ...]
        Returns:
            入库的切片总数
        """
        with self._write_lock:
            self.clear_all()
            store = self.get_vector_store()
            total = 0
            for item in payload:
                chunks = split_text(item["content"], source=item["name"])
                if chunks:
                    ids = [f"{item['name']}::{i}" for i in range(len(chunks))]
                    store.add_documents(documents=chunks, ids=ids)
                self._docs_by_source[item["name"]] = chunks
                total += len(chunks)
            self._rebuild_bm25()
            self.write_marker(total)
            log.success("向量库全量重建完成: %d 个文档 / %d 个切片", len(payload), total)
            return total

    # ---------- 查询 ----------

    def all_documents(self) -> List[LCDocument]:
        """当前全部切片（扁平列表）。"""
        result = []
        for chunks in self._docs_by_source.values():
            result.extend(chunks)
        return result

    def source_names(self) -> List[str]:
        return sorted(self._docs_by_source.keys())

    def chunk_count(self, name: str = None) -> int:
        if name is None:
            return len(self.all_documents())
        return len(self._docs_by_source.get(name, []))

    @staticmethod
    def _compute_weights(query: str) -> Tuple[float, float]:
        """
        按查询长度动态调整权重：
          短查询更依赖 BM25 关键词匹配，长查询更依赖向量语义匹配。
        返回 (向量权重, BM25 权重)
        """
        if len(query) < 20:
            return 0.4, 0.6
        return 0.7, 0.3

    def query(self, query_text: str, top_k: int = RERANK_TOP_K,
              sources: Optional[List[str]] = None) -> str:
        """
        多路召回 → 加权 RRF 融合 → Cross-Encoder 重排 → 格式化输出。

        Args:
            query_text: 用户查询
            top_k:      最终返回条数
            sources:    限定只在这些文档内检索（None 表示全部）
        """
        log.debug("RAG 检索开始: %r (限定文档=%s)", shorten(query_text, 60),
                  sources if sources else "全部")

        # ---- 1. 向量检索 ----
        try:
            search_kwargs = {"k": VECTOR_TOP_K}
            if sources:
                search_kwargs["filter"] = {"source": {"$in": list(sources)}}
            vector_docs = self.get_vector_store().similarity_search(query_text, **search_kwargs)
        except Exception as exc:  # noqa: BLE001
            log.error("向量检索失败，本次将仅依赖 BM25: %s", exc, exc_info=True)
            vector_docs = []

        # ---- 2. BM25 检索 ----
        bm25_docs: List[LCDocument] = []
        if self._bm25_retriever is not None:
            try:
                bm25_docs = self._bm25_retriever.invoke(query_text)
                if sources:
                    bm25_docs = [d for d in bm25_docs if d.metadata.get("source") in sources]
            except Exception as exc:  # noqa: BLE001
                log.error("BM25 检索失败，本次将仅依赖向量检索: %s", exc, exc_info=True)
        else:
            log.warning("BM25 索引为空（知识库可能还没有文档），仅使用向量检索")

        # ---- 3. 加权 RRF 融合 ----
        w_vec, w_bm25 = self._compute_weights(query_text)
        score_map: Dict[str, float] = {}
        doc_map: Dict[str, LCDocument] = {}

        for rank, doc in enumerate(vector_docs):
            key = doc.page_content[:200]
            score_map[key] = score_map.get(key, 0.0) + w_vec / (RRF_K + rank + 1)
            doc_map.setdefault(key, doc)

        for rank, doc in enumerate(bm25_docs):
            key = doc.page_content[:200]
            score_map[key] = score_map.get(key, 0.0) + w_bm25 / (RRF_K + rank + 1)
            doc_map.setdefault(key, doc)

        fused_keys = sorted(score_map, key=score_map.get, reverse=True)[:FUSION_TOP_K]
        candidates = [doc_map[k] for k in fused_keys if k in doc_map]

        if not candidates:
            log.info("RAG 检索无结果: %r（向量 %d 条 / BM25 %d 条召回，均未命中）",
                     shorten(query_text, 50), len(vector_docs), len(bm25_docs))
            return "未在 CV/DL 知识库中找到相关信息。"

        log.debug("双路召回: 向量 %d 条 | BM25 %d 条 | 融合权重 向量=%.1f BM25=%.1f | 候选 %d 条",
                  len(vector_docs), len(bm25_docs), w_vec, w_bm25, len(candidates))

        # ---- 4. Cross-Encoder 重排 ----
        reranker = self._get_reranker()
        if reranker is not None:
            pairs = [[query_text, c.page_content] for c in candidates]
            scores = reranker.predict(pairs)
            ranked = sorted(zip(candidates, scores), key=lambda x: -float(x[1]))
        else:
            log.warning("跳过 Cross-Encoder 精排，使用融合顺序（结果相关性可能偏低）")
            ranked = [(c, 1.0 - i * 0.05) for i, c in enumerate(candidates)]

        # ---- 5. 格式化输出 ----
        parts = []
        hits = []
        for i, (doc, score) in enumerate(ranked[:top_k], 1):
            source = doc.metadata.get("source", "未知来源")
            section = doc.metadata.get("问题标题") or doc.metadata.get("文档标题") or ""
            header = f"[参考 {i}] 相关度 {float(score):.3f} | 来源 {source}"
            if section:
                header += f" | {section.strip()}"
            parts.append(f"{header}\n{doc.page_content}")
            hits.append(f"{source}({float(score):.3f})")

        log.success("RAG 检索命中 %d 条: %s <- %r",
                    len(hits), " ".join(hits), shorten(query_text, 40))
        return "\n\n".join(parts)


# ==============================
#  全局单例
# ==============================

_engine: Optional[RAGEngine] = None


def get_engine(verbose: bool = True) -> RAGEngine:
    """获取或创建全局 RAG 引擎（线程安全，双检锁）。"""
    global _engine
    if _engine is None:
        with RAGEngine._lock:
            if _engine is None:
                _engine = RAGEngine(verbose=verbose)
    return _engine


# ==============================
#  LangChain 工具包装
# ==============================

@tool
def cv_rag_search(query: str) -> str:
    """
    检索计算机视觉与深度学习知识库。

    适用于：CNN 与卷积原理、Transformer/ViT/Swin、目标检测（Faster R-CNN/YOLO/DETR/NMS/mAP）、
    图像分割（U-Net/Mask R-CNN/SAM/mIoU/Dice）、训练技巧（优化器/学习率/数据增强/显存优化/消融实验设计）。

    输入：用户的问题或关键词。
    """
    # 延迟触发「首次启动同步」，避免仅导入模块就做重活
    try:
        from app.rag_manager import ensure_knowledge_base
        ensure_knowledge_base()
    except Exception:  # noqa: BLE001 - 同步失败不应让检索直接不可用
        pass
    return get_engine().query(query)


RAG_TOOLS = [cv_rag_search]

__all__ = [
    "cv_rag_search", "RAG_TOOLS", "get_engine", "RAGEngine",
    "tokenize", "split_text", "list_disk_documents",
    "load_and_split_documents", "compute_documents_fingerprint",
    "COLLECTION_NAME", "LEGACY_COLLECTION_NAME", "DOCUMENTS_DIR", "CHROMA_DIR",
]


# ==============================
#  命令行入口
# ==============================

if __name__ == "__main__":
    import sys

    from app.logging_conf import setup_logging
    from app.utils.console import use_utf8_console

    use_utf8_console()
    setup_logging(level="DEBUG")   # 命令行自检时把检索细节打全

    queries = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not queries:
        queries = ["YOLO 和 Faster R-CNN 的区别", "训练不收敛怎么办", "Swin 的移动窗口是怎么工作的"]

    from app.rag_manager import ensure_knowledge_base
    ensure_knowledge_base(verbose=True)

    engine = get_engine(verbose=True)
    print(f"\n当前知识库文档: {engine.source_names()}")
    print(f"切片总数: {engine.chunk_count()}")

    for q in queries:
        print("\n" + "=" * 70)
        print(f"查询: {q}")
        print("=" * 70)
        print(engine.query(q))
