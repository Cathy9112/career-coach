"""Chroma helpers used by the interview question bank."""

import os
from pathlib import Path
import threading
import uuid

import chromadb
from chromadb.api.types import Documents, Embeddings, EmbeddingFunction

from config import read_secret
from langchain_text_splitters import RecursiveCharacterTextSplitter


BASE_DIR = Path(__file__).resolve().parents[1]


def _resolve_path(value: str, default: Path) -> Path:
    path = Path(value).expanduser() if value else default
    return path if path.is_absolute() else BASE_DIR / path


# Both values can be overridden for deployments that keep models/data elsewhere.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "10"))
EMBEDDING_TIMEOUT_SECONDS = float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "60"))
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))
if not 1 <= EMBEDDING_BATCH_SIZE <= 10:
    raise RuntimeError("EMBEDDING_BATCH_SIZE must be between 1 and 10")
if EMBEDDING_DIMENSIONS <= 0:
    raise RuntimeError("EMBEDDING_DIMENSIONS must be positive")
KNOWLEDGE_COLLECTION_NAME = os.getenv(
    "KNOWLEDGE_COLLECTION_NAME", "interview_knowledge_base_dashscope_v1"
)
VECTOR_DB_PATH = _resolve_path(os.getenv("VECTOR_DB_PATH"), BASE_DIR / "chroma_career.db")
CHROMA_HOST = os.getenv("CHROMA_HOST")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

# 初始化文本递归分割器，用于把长面经文档切分为适合向量检索的小块
text_splitter = RecursiveCharacterTextSplitter(
    # 分割优先级：先按两段换行分割 → 单行换行 → 中文句号 → 英文句号
    separators=["\n\n", "\n", "。", "."],
    # 单个分块最大字符长度200，超过则强制拆分
    chunk_size=200,
    # 相邻两个分块重叠20个字符，保证上下文不被切断，提升检索连贯性
    chunk_overlap=20,
    # 使用字符长度作为文本长度计算标准
    length_function=len
)

# ===================== 全局懒加载缓存变量 =====================
# 向量数据库客户端全局缓存，懒加载：程序启动时不初始化，第一次调用向量接口才创建
_client = None
# DashScope嵌入模型实例全局缓存，只加载一次模型，避免重复加载占用内存
_embedding_function = None
_init_lock = threading.Lock()


class DashScopeEmbeddingFunction(EmbeddingFunction[Documents]):
    """Chroma embedding function backed by DashScope's OpenAI-compatible API."""

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            api_key = read_secret("DASHSCOPE_API_KEY")
            if not api_key:
                raise RuntimeError("DASHSCOPE_API_KEY is not configured")
            self._client = OpenAI(
                api_key=api_key,
                base_url=os.getenv(
                    "DASHSCOPE_BASE_URL",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                ),
                timeout=EMBEDDING_TIMEOUT_SECONDS,
                max_retries=2,
            )
        return self._client

    def __call__(self, input: Documents) -> Embeddings:
        if not input:
            return []

        embeddings: Embeddings = []
        for start in range(0, len(input), EMBEDDING_BATCH_SIZE):
            batch = input[start : start + EMBEDDING_BATCH_SIZE]
            response = self._get_client().embeddings.create(
                model=EMBEDDING_MODEL,
                input=batch,
                dimensions=EMBEDDING_DIMENSIONS,
                encoding_format="float",
            )
            data = sorted(response.data, key=lambda item: item.index)
            embeddings.extend(item.embedding for item in data)
        return embeddings


def _init_vector_db():
    """Initialize the Chroma client and DashScope embedding function lazily."""
    global _client, _embedding_function
    if _client is None:
        with _init_lock:
            if _client is None:
                _embedding_function = DashScopeEmbeddingFunction()
                if CHROMA_HOST:
                    _client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
                else:
                    VECTOR_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                    _client = chromadb.PersistentClient(path=str(VECTOR_DB_PATH))
    return _client


def get_or_create_collection(name):
    """
    获取/自动创建向量集合（一张向量数据表）
    :param name: 集合名称，项目中使用 "interview_knowledge_base" 存储面试题库
    :return: chromadb.Collection 向量集合对象，可执行新增、检索操作
    """
    if not name or not name.strip():
        raise ValueError("collection name must not be empty")

    # 先初始化客户端与模型
    client = _init_vector_db()
    # 存在对应集合直接获取，不存在则新建集合
    return client.get_or_create_collection(
        name=name,
        # 绑定全局DashScope嵌入函数，存入/查询文本时自动向量化
        embedding_function=_embedding_function,
        # 向量检索距离计算方式：cosine余弦相似度，适配中文语义匹配
        metadata={"hnsw:space": "cosine"}
    )


def add_documents(collection_name, documents, metadata):
    """
    批量上传原始文档到向量库：自动分块 → 生成唯一ID → 向量化持久存储
    :param collection_name: 目标向量集合名称
    :param documents: 原始文档文本列表，如 [完整面经文本1, 完整面经文本2]
    :param metadata: 写入每个分块的归属元数据
    :return: int 成功入库的文本分块总数量
    """
    if not documents:
        return 0

    # 获取目标向量集合
    collection = get_or_create_collection(collection_name)
    # 存储所有切割后的文本片段
    all_chunks = []

    # 遍历每一篇原始文档，执行分块
    for doc in documents:
        if not isinstance(doc, str) or not doc.strip():
            continue
        # 使用预定义分割器拆分长文本
        chunks = text_splitter.split_text(doc)
        # 将拆分后的小块追加到总列表
        all_chunks.extend(chunks)

    if not all_chunks:
        return 0

    # 为每一段分块生成唯一UUID字符串，作为向量库每条数据的主键
    ids = [str(uuid.uuid4()) for _ in all_chunks]
    # 批量插入向量库，Chroma会自动调用DashScope模型将文本转为向量并存入本地文件
    # 兼容新旧ChromaDB版本，仅传入id与文本，省略手动传向量
    collection.add(
        ids=ids,
        documents=all_chunks,
        metadatas=[metadata.copy() for _ in all_chunks],
    )
    # 返回分块总数，用于前端展示上传入库数量
    return len(all_chunks)


def query_documents(collection_name, query_text, n_results=3, where=None):
    """
    根据用户问题语义检索向量库，返回相似度最高的文本片段（RAG知识库检索核心函数）
    :param collection_name: 待检索的向量集合名称
    :param query_text: 用户输入的提问文本（面试问题/求职疑问）
    :param n_results: 最多返回几条匹配片段，默认3条
    :param where: Chroma 元数据过滤条件
    :return: list[str] 语义最相似的文档片段数组；无匹配则返回空列表
    """
    if not isinstance(query_text, str) or not query_text.strip():
        return []
    if not isinstance(n_results, int) or not 1 <= n_results <= 20:
        raise ValueError("n_results must be between 1 and 20")

    # 获取目标向量集合
    collection = get_or_create_collection(collection_name)
    if collection.count() == 0:
        return []
    # 执行语义检索：自动用DashScope把query_text转为向量，计算库内向量相似度
    res = collection.query(query_texts=[query_text], n_results=n_results, where=where)
    # 安全取值：存在匹配结果返回文档列表，无数据返回空数组，避免前端报错
    documents = res.get("documents") if res else None
    return documents[0] if documents and documents[0] else []


def delete_documents(collection_name, document_ids):
    if not document_ids:
        return
    collection = get_or_create_collection(collection_name)
    collection.delete(where={"document_id": {"$in": document_ids}})
