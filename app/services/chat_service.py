import logging
import json
import re
from typing import AsyncGenerator, Dict, Any, List, Tuple, cast
from uuid import UUID

from fastapi import BackgroundTasks
from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.runnables import ConfigurableFieldSpec

from app.db import crud
from app.db.session import SessionLocal, get_db
from app.models.chat_models import ChatRequest
from app.services.chat_history_service import PostgresChatMessageHistory
from app.services.langchain_service import LLMService

logger = logging.getLogger(__name__)


async def _save_rag_document_from_web_search_task(
    docs: List[Document], hscode_value: str
):
    """
    웹 검색을 통해 얻은 RAG 문서를 DB에 저장하는 백그라운드 작업.
    이 함수는 자체 DB 세션을 생성하여 사용함.
    """
    if not docs:
        logger.info("웹 검색으로부터 저장할 새로운 문서가 없습니다.")
        return

    logger.info(
        f"백그라운드 작업을 시작합니다: HSCode '{hscode_value}'에 대한 {len(docs)}개의 새 문서 저장."
    )
    try:
        async with SessionLocal() as db:
            hscode_obj = await crud.hscode.get_or_create(
                db, code=hscode_value, description="From web search"
            )

            # SQLAlchemy 객체를 refresh하여 실제 ID 값을 가져옴
            await db.refresh(hscode_obj)

            # refresh 후에는 ID가 항상 존재해야 함을 타입 체커에게 알림
            assert (
                hscode_obj.id is not None
            ), "HSCode ID should be available after refresh"

            for doc in docs:
                await crud.document.create_v2(
                    db,
                    hscode_id=cast(
                        int, hscode_obj.id
                    ),  # Column[int]를 int로 타입 캐스팅
                    content=doc.page_content,
                    metadata=doc.metadata,
                )
            await db.commit()
            logger.info(f"HSCode '{hscode_value}'에 대한 새 문서 저장을 완료했습니다.")
    except Exception as e:
        logger.error(f"백그라운드 RAG 문서 저장 작업 중 오류 발생: {e}", exc_info=True)


class ChatService:
    """
    채팅 관련 비즈니스 로직을 처리하는 서비스.
    LLM 서비스와 DB 기록 서비스를 결합하여 엔드포인트에 응답을 제공함.
    """

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service

    async def stream_chat_response(
        self,
        chat_request: ChatRequest,
        db: AsyncSession,
        background_tasks: BackgroundTasks,
    ) -> AsyncGenerator[str, None]:
        """
        사용자 요청에 대한 AI 채팅 응답을 SSE 스트림으로 생성함.
        사용자 로그인 상태에 따라 대화 기록 관리 여부를 결정함.
        """
        user_id = chat_request.user_id
        session_uuid_str = chat_request.session_uuid

        chain = self.llm_service.chat_chain
        config: Dict[str, Any] = {}
        history = None
        session_obj = None
        current_session_uuid = None
        previous_messages = []  # 기본값으로 빈 리스트 설정

        try:
            # 세션 및 히스토리 초기화
            if user_id:
                # 1. 비동기 CRUD 함수를 사용하여 세션을 먼저 가져오거나 생성
                session_obj = await crud.chat.get_or_create_session(
                    db=db, user_id=user_id, session_uuid_str=session_uuid_str
                )

                # 세션 생성 후 즉시 커밋하여 DB에 저장
                await db.commit()

                # 2. History 객체를 직접 생성
                history = PostgresChatMessageHistory(
                    db=db,
                    user_id=user_id,
                    session=session_obj,
                )

                # 새로 생성되었거나 기존의 세션 UUID를 가져옴
                current_session_uuid = str(session_obj.session_uuid)

                # 첫 요청(기존 session_uuid가 없었음)이었다면, 클라이언트에게 알려줌
                if not session_uuid_str:
                    sse_event = {
                        "type": "session_id",
                        "data": {"session_uuid": current_session_uuid},
                    }
                    yield f"data: {json.dumps(sse_event)}\n\n"

                # 이전 대화 내역을 가져와서 체인의 입력에 포함
                previous_messages = await history.aget_messages()

                # 수동으로 사용자 메시지 저장
                from langchain_core.messages import HumanMessage

                human_message = HumanMessage(content=chat_request.message)
                await history.aadd_message(human_message)
                await db.commit()

            # 체인 실행 및 스트리밍
            final_output = None
            ai_response = ""
            chunk_buffer = []
            buffer_size = 10  # 버퍼 크기 설정

            # 1. 체인 스트리밍 실행
            input_data: Dict[str, Any] = {"question": chat_request.message}

            # 이전 대화 내역이 있으면 추가 (BaseMessage 객체들을 그대로 전달)
            if history and previous_messages:
                # BaseMessage 객체들을 리스트로 그대로 전달
                input_data["chat_history"] = previous_messages
            else:
                # 대화 내역이 없으면 빈 리스트 전달
                input_data["chat_history"] = []

            try:
                async for chunk in chain.astream(input_data):
                    final_output = chunk
                    answer_chunk = chunk.get("answer", "")

                    if answer_chunk:
                        ai_response += answer_chunk
                        chunk_buffer.append(answer_chunk)

                        # 버퍼가 일정 크기에 도달하면 전송
                        if len(chunk_buffer) >= buffer_size or len(answer_chunk) > 50:
                            buffered_content = "".join(chunk_buffer)
                            sse_event = {
                                "type": "token",
                                "data": {"content": buffered_content},
                            }
                            yield f"data: {json.dumps(sse_event)}\n\n"
                            chunk_buffer.clear()

                # 남은 버퍼 내용 전송
                if chunk_buffer:
                    buffered_content = "".join(chunk_buffer)
                    sse_event = {"type": "token", "data": {"content": buffered_content}}
                    yield f"data: {json.dumps(sse_event)}\n\n"

            except Exception as stream_error:
                logger.error(
                    f"체인 스트리밍 중 오류 발생: {stream_error}", exc_info=True
                )
                error_event = {
                    "type": "error",
                    "data": {
                        "message": "AI 응답 생성 중 오류가 발생했습니다.",
                        "error_code": "CHAIN_STREAMING_ERROR",
                    },
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                return

            # 2. AI 응답 메시지 저장
            if user_id and history and ai_response:
                try:
                    from langchain_core.messages import AIMessage

                    ai_message = AIMessage(content=ai_response)
                    await history.aadd_message(ai_message)
                    await db.commit()
                except Exception as save_error:
                    logger.error(
                        f"AI 응답 저장 중 오류 발생: {save_error}", exc_info=True
                    )
                    # 저장 실패해도 응답은 계속 진행

            # 3. RAG-웹 검색 폴백 시 백그라운드 작업 추가
            if final_output and final_output.get("source") == "rag_or_web":
                source_docs = final_output.get("docs", [])
                if source_docs and not any(
                    doc.metadata.get("source") == "db" for doc in source_docs
                ):
                    hscode_match = re.search(
                        r"\b(\d{4}\.\d{2}|\d{6}|\d{10})\b", chat_request.message
                    )
                    hscode_value = hscode_match.group(0) if hscode_match else "N/A"
                    logger.info(
                        "RAG-웹 검색 폴백이 발생하여, 결과 저장을 위한 백그라운드 작업을 예약합니다."
                    )
                    background_tasks.add_task(
                        _save_rag_document_from_web_search_task,
                        source_docs,
                        hscode_value,
                    )

            # 완료 이벤트 전송
            success_event = {
                "type": "complete",
                "data": {
                    "message": "응답 생성이 완료되었습니다.",
                    "token_count": len(ai_response),
                    "source": (
                        final_output.get("source", "unknown")
                        if final_output
                        else "unknown"
                    ),
                },
            }
            yield f"data: {json.dumps(success_event)}\n\n"

        except Exception as e:
            logger.error(f"채팅 스트림 처리 중 치명적 오류 발생: {e}", exc_info=True)
            error_event = {
                "type": "error",
                "data": {
                    "message": "채팅 서비스에서 예기치 않은 오류가 발생했습니다.",
                    "error_code": "CHAT_SERVICE_ERROR",
                },
            }
            yield f"data: {json.dumps(error_event)}\n\n"
