import logging
import json
import re
from typing import AsyncGenerator, Dict, Any, List, Tuple
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


async def _save_rag_document_from_web_search_task(docs: List[Document], hscode_value: str):
    """
    웹 검색을 통해 얻은 RAG 문서를 DB에 저장하는 백그라운드 작업.
    이 함수는 자체 DB 세션을 생성하여 사용.
    """
    if not docs:
        logger.info("웹 검색으로부터 저장할 새로운 문서가 없습니다.")
        return

    logger.info(
        f"백그라운드 작업을 시작합니다: HSCode '{hscode_value}'에 대한 {len(docs)}개의 새 문서 저장.")
    try:
        async with SessionLocal() as db:
            hscode_obj = await crud.hscode.get_or_create(
                db, code=hscode_value, description="From web search")

            for doc in docs:
                await crud.document.create_v2(
                    db,
                    hscode_id=hscode_obj.id,
                    content=doc.page_content,
                    metadata=doc.metadata
                )
            await db.commit()
            logger.info(f"HSCode '{hscode_value}'에 대한 새 문서 저장을 완료했습니다.")
    except Exception as e:
        logger.error(f"백그라운드 RAG 문서 저장 작업 중 오류 발생: {e}", exc_info=True)


class ChatService:
    """
    채팅 관련 비즈니스 로직을 처리하는 서비스.
    LLM 서비스와 DB 기록 서비스를 결합하여 엔드포인트에 응답을 제공.
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
        사용자 요청에 대한 AI 채팅 응답을 SSE 스트림으로 생성.
        사용자 로그인 상태에 따라 대화 기록 관리 여부를 결정.
        """
        user_id = chat_request.user_id
        session_uuid_str = chat_request.session_uuid

        chain = self.llm_service.chat_chain
        config: Dict[str, Any] = {}
        history = None
        session_obj = None
        current_session_uuid = None
        previous_messages = []  # 기본값으로 빈 리스트 설정

        if user_id:
            # 1. 비동기 CRUD 함수를 사용하여 세션을 먼저 가져오거나 생성
            session_obj = await crud.chat.get_or_create_session(
                db=db, user_id=user_id, session_uuid_str=session_uuid_str
            )

            # 세션 생성 후 즉시 커밋하여 DB에 저장
            await db.commit()

            # 2. History 객체를 직접 생성.
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
                    "data": {"session_uuid": current_session_uuid}
                }
                yield f"data: {json.dumps(sse_event)}\n\n"

            # 이전 대화 내역을 가져와서 체인의 입력에 포함
            previous_messages = await history.aget_messages()

            # 수동으로 사용자 메시지 저장
            from langchain_core.messages import HumanMessage
            human_message = HumanMessage(content=chat_request.message)
            await history.aadd_message(human_message)
            await db.commit()

        final_output = None
        ai_response = ""
        try:
            # 1. 체인 스트리밍 실행
            input_data = {"question": chat_request.message}

            # 이전 대화 내역이 있으면 추가
            if history and previous_messages:
                input_data["chat_history"] = previous_messages

            async for chunk in chain.astream(input_data):
                final_output = chunk
                answer_chunk = chunk.get("answer", "")
                if answer_chunk:
                    ai_response += answer_chunk
                    sse_event = {"type": "token",
                                 "data": {"content": answer_chunk}}
                    yield f"data: {json.dumps(sse_event)}\n\n"

            # 2. AI 응답 메시지 저장
            if user_id and history and ai_response:
                from langchain_core.messages import AIMessage
                ai_message = AIMessage(content=ai_response)
                await history.aadd_message(ai_message)
                await db.commit()

            # 3. RAG-웹 검색 폴백 시 백그라운드 작업 추가
            if final_output and final_output.get("source") == "rag_or_web":
                source_docs = final_output.get("docs", [])
                if source_docs and not any(doc.metadata.get("source") == "db" for doc in source_docs):
                    hscode_match = re.search(
                        r"\b(\d{4}\.\d{2}|\d{6}|\d{10})\b", chat_request.message)
                    hscode_value = hscode_match.group(
                        0) if hscode_match else "N/A"
                    logger.info(
                        "RAG-웹 검색 폴백이 발생하여, 결과 저장을 위한 백그라운드 작업을 예약합니다.")
                    background_tasks.add_task(
                        _save_rag_document_from_web_search_task,
                        source_docs,
                        hscode_value
                    )

        except Exception as e:
            logger.error(f"채팅 스트림 처리 중 오류 발생: {e}", exc_info=True)
            error_event = {"type": "error", "data": {
                "message": "스트리밍 중 서버 오류가 발생했습니다."}}
            yield f"data: {json.dumps(error_event)}\n\n"
        finally:
            finish_event = {"type": "finish", "data": {
                "message": "Stream finished."}}
            yield f"data: {json.dumps(finish_event)}\n\n"
