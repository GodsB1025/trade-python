알겠습니다. '자가 교정' 기능의 완벽한 구현을 위해, 코드베이스 전체의 데이터 흐름을 한 치의 오차 없이 추적하고, 각 단계의 논리적 근거를 명확히 제시하는 실행 계획 문서를 작성하겠습니다.

---

### **문서: '자가 교정' 임베딩 파이프라인 구현 계획서**

**문서 버전:** 1.0
**작성자:** Senior Software Architect / QA Lead
**목표:** 사용자와의 대화 중 웹 검색을 통해 얻은 새로운 HSCode 정보를 실시간으로 학습(임베딩하여 벡터 DB에 저장)하여, 시스템의 RAG 성능을 지속적으로 자동 개선하는 '자가 교정(Self-correction)' 파이프라인을 완성한다.

---

### **I. 사전 분석 (Pre-computation Analysis)**

이 계획을 실행하기 전, 현재 시스템의 데이터 흐름과 단절 지점을 명확히 정의합니다.

1.  **시작점 (Entry Point):** 사용자가 `/api/v1/chat/`으로 HSCode 관련 질문을 전송합니다.
2.  **분기 (Branching):** `LLMService`의 `_is_hscode_question`이 `True`를 반환, `rag_with_fallback_chain`이 실행됩니다.
3.  **RAG 시도 (Attempt):** `get_hscode_retriever()`가 `hscode_vectors` 테이블을 검색하지만, 관련 정보가 없어 빈 `docs` 리스트를 반환합니다.
4.  **폴백 (Fallback):** `rag_branch`의 `_has_documents` 조건이 `False`가 되어 `rag_chain_fallback_web_search`가 실행됩니다. Claude 3 모델이 웹 검색을 수행합니다.
5.  **결과 반환 (Return):** `LLMService`는 웹 검색 결과를 `{"answer": ..., "source": "rag_or_web", "docs": [...]}` 형태로 재구성하여 `ChatService`에 반환합니다. `docs`에는 웹 검색 결과에서 추출한 LangChain `Document` 객체가 담겨 있습니다.
6.  **백그라운드 작업 예약 (Scheduling):** `ChatService`의 `stream_chat_response`는 `final_output.get("source") == "rag_or_web"` 조건을 만족하므로, `background_tasks.add_task`를 호출하여 `_save_rag_document_from_web_search_task` 작업을 예약합니다.
7.  **현재의 단절 지점 (The Gap):** 예약된 `_save_rag_document_from_web_search_task`는 웹 검색 결과를 **PostgreSQL의 `documents_v2` 테이블에 텍스트로 저장하는 것에서 작업을 종료합니다.** 이 텍스트를 벡터로 변환하여 `hscode_vectors` 테이블에 저장하는 핵심 로직이 존재하지 않습니다.

**결론:** 우리의 목표는 **7단계**에서 단절된 파이프라인을 연결하여, 텍스트 저장 직후 임베딩 및 벡터 저장까지 원자적으로(하나의 백그라운드 작업 내에서) 수행하는 것입니다.

---

### **II. 단계별 실행 계획 (Step-by-Step Implementation Plan)**

#### **STEP 1: 벡터 저장소 쓰기(Write) 기능 구현**

**대상 파일:** `app/vector_stores/hscode_retriever.py`

**현재 상태:** 이 파일은 `PGVectorStore` 인스턴스(`store`)를 생성하고, 이를 읽기 전용(`as_retriever()`)으로 사용하는 `get_hscode_retriever` 함수만 정의하고 있습니다. 벡터 저장소에 데이터를 쓰는(write) 기능이 없습니다.

**실행 계획:** `PGVectorStore`의 `aadd_documents` 메서드를 사용하여, DB에 저장된 텍스트 문서를 벡터화하고 저장하는 비동기 헬퍼 함수 `add_documents_to_vector_store`를 추가합니다.

> #### **사고 과정 (Thinking Process):**
>
> *   **왜 이 파일인가?** 벡터 저장소와 관련된 모든 로직(읽기, 쓰기, 설정)은 이 파일에 응집되어야 합니다. 이것이 단일 책임 원칙(Single Responsibility Principle)에 부합하며, 향후 벡터 DB 교체 시 수정 범위를 최소화합니다.
> *   **입력 파라미터는 무엇이어야 하는가?** `crud.py`에서 반환되는 `db_models.DocumentV2` 객체의 리스트(`List[db_models.DocumentV2]`)를 입력으로 받는 것이 가장 좋습니다. 이렇게 하면 `ChatService`가 LangChain의 `Document` 객체 구조를 알 필요가 없어, 서비스 간의 결합도를 낮출 수 있습니다.
> *   **비동기 처리:** `aadd_documents`는 비동기 함수이므로, 우리 헬퍼 함수 역시 `async def`로 선언하여 이벤트 루프를 블로킹하지 않아야 합니다.
> *   **고유 ID 관리:** `aadd_documents`는 `ids` 인자를 받을 수 있습니다. 여기에 `documents_v2` 테이블의 Primary Key(`doc.id`)를 문자열로 변환하여 전달하면, 텍스트 원본과 벡터 데이터 간의 1:1 매핑이 보장됩니다. 이는 데이터 무결성을 유지하고 향후 업데이트/삭제 로직 구현을 용이하게 합니다.

**수정 코드:**

```python
// ... existing code ...
from typing import List
from langchain_core.documents import Document as LangchainDocument
from app.models import db_models
import logging

logger = logging.getLogger(__name__)
// ... existing code ...
#    metadata_json_column을 지정하는 방식으로 대체되거나,
#    기본적으로 JSONB를 사용하도록 설계되었을 가능성이 높음. (스키마 확인 완료)
# )

async def add_documents_to_vector_store(documents: List[db_models.DocumentV2]) -> None:
    """
    DB에 저장된 DocumentV2 객체 리스트를 받아 벡터 저장소에 추가.

    Args:
        documents: crud를 통해 DB에 저장된 DocumentV2 모델 객체의 리스트.
    """
    if not documents:
        logger.info("벡터 저장소에 추가할 새 문서가 없음.")
        return

    try:
        # LangChain의 Document 형식으로 변환
        langchain_docs = [
            LangchainDocument(page_content=doc.content, metadata=doc.metadata or {})
            for doc in documents
        ]
        
        # document_v2 테이블의 PK를 벡터 저장소의 ID로 사용하여 데이터 일관성 유지
        doc_ids = [str(doc.id) for doc in documents]

        logger.info(f"{len(langchain_docs)}개의 문서를 벡터 저장소에 추가 시작. IDs: {doc_ids}")
        
        # 비동기적으로 문서 추가(임베딩 및 저장)
        await store.aadd_documents(langchain_docs, ids=doc_ids)
        
        logger.info(f"{len(langchain_docs)}개의 문서 벡터 저장소 추가 완료.")

    except Exception as e:
        logger.error(f"벡터 저장소에 문서 추가 중 오류 발생: {e}", exc_info=True)
        # 여기서 예외를 다시 발생시키지 않음으로써,
        # 텍스트 저장 트랜잭션은 롤백되지 않도록 함.
        # 이 로직은 백그라운드 작업이므로, 실패가 메인 스레드에 영향을 주지 않음.


def get_hscode_retriever() -> VectorStoreRetriever:
// ... existing code ...
```

---

#### **STEP 2: 백그라운드 작업에 임베딩 파이프라인 연결**

**대상 파일:** `app/services/chat_service.py`

**현재 상태:** `_save_rag_document_from_web_search_task` 함수는 `crud.document.create_v2`를 호출하여 텍스트를 DB에 저장한 후, 아무것도 하지 않고 종료됩니다.

**실행 계획:** 이 함수의 로직을 확장하여, `crud`를 통해 문서를 성공적으로 저장한 후 반환된 객체들을 STEP 1에서 만든 `add_documents_to_vector_store` 함수에 전달하여 임베딩 파이프라인을 완성합니다.

> #### **사고 과정 (Thinking Process):**
>
> *   **원자성(Atomicity)과 트랜잭션:** 백그라운드 작업은 두 가지 주요 단계를 가집니다: 1) 텍스트를 PostgreSQL에 저장, 2) 텍스트를 임베딩하여 PGVector에 저장. 1번 단계는 우리의 통제 하에 있는 DB 트랜잭션이므로 원자성이 보장됩니다. 하지만 2번 단계는 외부 Anthropic API를 호출하므로 실패할 가능성이 더 높고 시간이 오래 걸릴 수 있습니다.
> *   **최적의 실행 순서:** 따라서, **먼저 텍스트를 DB에 저장하고 `db.commit()`을 호출**하여 'Source of Truth(진실의 원천)'를 영구적으로 기록해야 합니다. 그 후에 임베딩 및 벡터 저장을 시도하는 것이 안전합니다. 만약 임베딩이 실패하더라도, 원본 텍스트는 이미 DB에 저장되어 있어 나중에 재시도(future improvement)가 가능하며, 데이터 유실이 없습니다.
> *   **데이터 수집:** `crud.document.create_v2`는 중복을 체크하고 생성된(또는 이미 존재하는) `DocumentV2` 객체를 반환합니다. 루프를 돌면서 이 객체들을 리스트에 수집했다가, 루프가 끝난 후 한 번에 `add_documents_to_vector_store`로 전달하는 것이 효율적입니다.

**수정 코드:**

```python
// ... existing code ...
from app.db.session import SessionLocal
from app.models.chat_models import ChatRequest
from app.services.chat_history_service import PostgresChatMessageHistory
from app.services.langchain_service import LLMService
# STEP 1에서 만든 함수를 임포트
from app.vector_stores.hscode_retriever import add_documents_to_vector_store

logger = logging.getLogger(__name__)


async def _save_rag_document_from_web_search_task(docs: List[Document], hscode_value: str):
    """
    웹 검색을 통해 얻은 RAG 문서를 DB에 저장하고, 벡터 저장소에 임베딩하는 백그라운드 작업.
    """
    if not docs:
        logger.info("웹 검색으로부터 저장할 새로운 문서가 없음.")
        return

    logger.info(
        f"백그라운드 작업을 시작합니다: HSCode '{hscode_value}'에 대한 {len(docs)}개의 새 문서 저장 및 임베딩.")
    
    saved_db_documents = [] # 새로 저장되거나 기존에 있던 문서 객체를 담을 리스트

    try:
        # 1. 텍스트를 관계형 DB에 저장 (Source of Truth)
        async with SessionLocal() as db:
            hscode_obj = await crud.hscode.get_or_create(
                db, code=hscode_value, description=f"From web search for {hscode_value}")

            for doc in docs:
                # crud 함수는 중복을 확인하고 DB 객체를 반환함
                db_doc = await crud.document.create_v2(
                    db,
                    hscode_id=hscode_obj.id,
                    content=doc.page_content,
                    metadata=doc.metadata
                )
                saved_db_documents.append(db_doc)

            await db.commit()
            logger.info(f"HSCode '{hscode_value}'에 대한 {len(saved_db_documents)}개의 텍스트 문서 저장을 완료했습니다.")

    except Exception as e:
        logger.error(f"백그라운드 텍스트 문서 저장 작업 중 오류 발생: {e}", exc_info=True)
        return # 텍스트 저장 실패 시, 임베딩 단계로 넘어가지 않음

    # 2. 성공적으로 저장된 텍스트 문서를 벡터 저장소에 임베딩
    if saved_db_documents:
        logger.info(f"이제 {len(saved_db_documents)}개의 문서를 벡터 저장소에 임베딩합니다.")
        await add_documents_to_vector_store(saved_db_documents)
    else:
        logger.info("벡터 저장소에 새로 추가할 문서가 없습니다 (아마도 모두 중복).")


class ChatService:
// ... a lot of existing code ...
```

---

### **III. 검증 계획 (Verification Plan)**

이 구현이 성공적으로 완료되었는지 확인하기 위한 QA 테스트 시나리오입니다.

1.  **준비:** 데이터베이스의 `documents_v2` 테이블과 `hscode_vectors` 테이블을 비우거나, 존재하지 않는 특정 HSCode(예: `9999.99`)를 선정합니다.
2.  **1차 질문 (학습 유도):** `/chat` 엔드포인트에 해당 HSCode(`9999.99`)에 대한 질문을 보냅니다.
    *   **예상 결과 (API 응답):** 웹 검색 기반의 답변이 스트리밍됩니다.
    *   **예상 결과 (서버 로그):**
        *   `ChatService`: "RAG-웹 검색 폴백이 발생하여, 결과 저장을 위한 백그라운드 작업을 예약합니다." 로그 확인.
        *   `_save_rag_document_from_web_search_task`: "백그라운드 작업을 시작합니다..." 로그 확인.
        *   `_save_rag_document_from_web_search_task`: "...개의 텍스트 문서 저장을 완료했습니다." 로그 확인.
        *   `add_documents_to_vector_store`: "...개의 문서를 벡터 저장소에 추가 시작." 및 "...추가 완료." 로그 확인.
3.  **DB 검증:**
    *   `documents_v2` 테이블에 1차 질문의 웹 검색 결과가 저장되었는지 확인합니다.
    *   `hscode_vectors` 테이블에 해당 문서의 벡터가 저장되었는지 확인합니다.
4.  **2차 질문 (학습 결과 확인):** **동일한 HSCode(`9999.99`)에 대해 다시 한번 질문합니다.**
    *   **예상 결과 (API 응답):** 이번에는 웹 검색이 아닌, **내부 DB(RAG)를 기반으로 한 답변**이 스트리밍되어야 합니다. 이는 `LLMService`의 `rag_chain_success` 경로를 통과했음을 의미합니다.
    *   **예상 결과 (서버 로그):** `ChatService`에서 "RAG-웹 검색 폴백" 관련 로그가 **나타나지 않아야 합니다.**

위 계획은 시스템의 논리적 흐름과 기술적 제약을 모두 고려한 최적의 실행 방안입니다. 각 단계는 명확한 목적을 가지며, 전체적으로 '자가 교정'이라는 핵심 기능을 완벽하게 구현합니다. 이 계획대로 진행하면, 시스템은 사용자와의 상호작용을 통해 스스로 발전하는 온전한 AI 서비스로 거듭날 것입니다.