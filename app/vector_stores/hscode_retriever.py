from langchain_core.vectorstores import VectorStoreRetriever
from langchain_postgres import PGVectorStore, PGEngine

from app.core.config import settings
from app.core.llm_provider import llm_provider

# PGVector 스토어 설정
# 1. langchain-postgres의 PGVectorStore는 SQLAlchemy의 연결 엔진을 사용
connection_string = settings.SYNC_DATABASE_URL
# 2. 연결 문자열로부터 PGEngine 인스턴스 생성
engine = PGEngine.from_connection_string(url=connection_string)

collection_name = "hscode_vectors"  # 실제로는 테이블 이름을 의미

# LLMProvider에서 임베딩 모델을 가져옴
embeddings = llm_provider.embedding_model


# 새로운 PGVectorStore 인스턴스 생성.
# __init__으로 직접 생성하는 대신 create_sync 팩토리 메서드를 사용.
store = PGVectorStore.create_sync(
    engine=engine,
    embedding_service=embeddings,
    table_name=collection_name,
    id_column="id",  # 실제 테이블의 PK 컬럼 이름 명시
    # content_column, metadata_columns 등을 명시하여 커스텀 테이블에 연결
    content_column="description",
    embedding_column="embedding",
    metadata_columns=[
        "hscode",
        "product_name",
        "classification_basis",
        "similar_hscodes",
        "keywords",
        "web_search_context",
        "hscode_differences",
        "confidence_score",
        "verified",
    ],
    # PGVectorStore.create_sync 에는 use_jsonb 인자가 없음.
    # metadata_json_column을 지정하는 방식으로 대체되거나,
    # 기본적으로 JSONB를 사용하도록 설계되었을 가능성이 높음. (스키마 확인 완료)
)


def get_hscode_retriever() -> VectorStoreRetriever:
    """
    HSCode 벡터 저장소에 대한 LangChain Retriever를 반환.

    Returns:
        VectorStoreRetriever: 설정된 검색 옵션(예: k=5)을 사용하는 retriever.
    """
    return store.as_retriever(
        search_type="similarity",
        search_kwargs={'k': 5}
    )
