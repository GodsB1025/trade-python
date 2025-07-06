import logging
import json
import re
from typing import AsyncGenerator, Dict, Any, List, cast
import uuid
from datetime import datetime

from fastapi import BackgroundTasks
from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from pydantic import SecretStr

from app.db import crud
from app.db.session import SessionLocal, get_db
from app.models.chat_models import ChatRequest
from app.services.chat_history_service import PostgresChatMessageHistory
from app.services.langchain_service import LLMService
from app.core.config import settings
from app.core.llm_provider import llm_provider

logger = logging.getLogger(__name__)


async def generate_session_title(user_message: str, ai_response: str) -> str:
    """
    사용자의 첫 번째 메시지와 AI 응답을 바탕으로 세션 제목을 자동 생성

    Args:
        user_message: 사용자의 첫 번째 메시지
        ai_response: AI의 응답

    Returns:
        생성된 세션 제목 (최대 50자)
    """
    try:
        # llm_provider의 ChatAnthropic 사용
        title_llm = ChatAnthropic(
            model_name="claude-3-5-haiku-20241022",
            api_key=SecretStr(settings.ANTHROPIC_API_KEY),
            temperature=0.3,
            max_tokens_to_sample=100,
            timeout=None,
            stop=None,
        )

        # 제목 생성 프롬프트
        prompt = f"""다음 대화를 기반으로 짧고 명확한 세션 제목을 생성해주세요.

사용자 질문: {user_message}
AI 응답: {ai_response[:500]}...

요구사항:
1. 한국어로 작성
2. 최대 50자 이내
3. 대화의 핵심 주제를 포함
4. 명사형으로 종결
5. 특수문자나 이모지 사용 금지

예시:
- "HSCode 8471.30 관련 관세율 문의"
- "미국 수출 규제 현황 질문"
- "중국 무역 정책 변화 논의"

제목만 응답하세요:"""

        # API 호출
        response = await title_llm.ainvoke([HumanMessage(content=prompt)])

        # 응답 텍스트 추출
        title = ""
        if isinstance(response.content, str):
            title = response.content.strip()
        elif isinstance(response.content, list) and response.content:
            # content가 list인 경우 첫 번째 요소 사용
            title = str(response.content[0]).strip()

        if not title:
            # 응답이 비어있을 경우 폴백
            fallback_title = user_message[:30].strip()
            if len(user_message) > 30:
                fallback_title += "..."
            return fallback_title

        # 따옴표 제거
        title = title.strip('"').strip("'")

        # 길이 제한
        if len(title) > 50:
            title = title[:47] + "..."

        return title

    except Exception as e:
        logger.warning(f"세션 제목 자동 생성 실패: {e}")
        # 폴백: 사용자 메시지 첫 30자 사용
        fallback_title = user_message[:30].strip()
        if len(user_message) > 30:
            fallback_title += "..."
        return fallback_title


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
        사용자 요청에 대한 AI 채팅 응답을 Anthropic Claude API 형식의 SSE 스트림으로 생성함.
        사용자 로그인 상태에 따라 대화 기록 관리 여부를 결정함.
        강화된 트랜잭션 관리로 데이터 일관성 보장.
        """
        user_id = chat_request.user_id
        session_uuid_str = chat_request.session_uuid

        # 직접 ChatAnthropic 모델 사용 (chain 대신)
        chat_model = llm_provider.news_chat_model
        history = None
        session_obj = None
        current_session_uuid = None
        previous_messages = []  # 기본값으로 빈 리스트 설정
        is_new_session = False  # 새 세션 여부 추적

        # 메시지 및 content block을 위한 UUID 생성
        message_id = f"chatcompl_{uuid.uuid4().hex[:24]}"
        parent_uuid = str(uuid.uuid4())
        message_uuid = str(uuid.uuid4())
        content_block_start_timestamp = datetime.utcnow().isoformat() + "Z"

        try:
            # 세션 및 히스토리 초기화
            if user_id:
                # 세션 관련 트랜잭션을 세이브포인트로 관리
                async with db.begin_nested() as session_savepoint:
                    try:
                        # 1. 비동기 CRUD 함수를 사용하여 세션을 먼저 가져오거나 생성
                        session_obj = await crud.chat.get_or_create_session(
                            db=db, user_id=user_id, session_uuid_str=session_uuid_str
                        )

                        # 새 세션인지 확인 (session_uuid_str이 없었던 경우)
                        is_new_session = not session_uuid_str

                        # 세션 생성 후 즉시 플러시하여 세이브포인트에 반영
                        await db.flush()

                        # 세이브포인트 커밋
                        await session_savepoint.commit()

                    except Exception as session_error:
                        logger.error(
                            f"세션 생성/조회 중 오류 발생: {session_error}",
                            exc_info=True,
                        )
                        await session_savepoint.rollback()
                        # 세션 생성 실패 시 비회원으로 처리
                        user_id = None
                        session_obj = None

                if session_obj and user_id is not None:
                    # 2. History 객체를 직접 생성
                    history = PostgresChatMessageHistory(
                        db=db,
                        user_id=user_id,
                        session=session_obj,
                    )

                    # 새로 생성되었거나 기존의 세션 UUID를 가져옴
                    current_session_uuid = str(session_obj.session_uuid)

                    # 이전 대화 내역을 가져와서 모델 입력에 포함
                    try:
                        previous_messages = await history.aget_messages()
                    except Exception as history_error:
                        logger.warning(f"대화 내역 조회 중 오류 발생: {history_error}")
                        previous_messages = []

                    # 사용자 메시지 저장을 세이브포인트로 관리
                    async with db.begin_nested() as user_message_savepoint:
                        try:
                            from langchain_core.messages import HumanMessage

                            human_message = HumanMessage(content=chat_request.message)
                            await history.aadd_message(human_message)
                            await db.flush()
                            await user_message_savepoint.commit()

                        except Exception as message_save_error:
                            logger.error(
                                f"사용자 메시지 저장 중 오류 발생: {message_save_error}",
                                exc_info=True,
                            )
                            await user_message_savepoint.rollback()
                            # 메시지 저장 실패해도 응답은 계속 진행

            # Anthropic 형식의 message_start 이벤트 전송
            message_start_event = {
                "type": "message_start",
                "message": {
                    "id": message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": settings.ANTHROPIC_MODEL,  # 실제 사용 모델
                    "parent_uuid": parent_uuid,
                    "uuid": message_uuid,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                },
            }
            yield f"event: message_start\ndata: {json.dumps(message_start_event)}\n\n"

            # 세션 ID가 새로 생성된 경우, 별도의 metadata content block으로 전송
            content_index = 0
            if is_new_session and current_session_uuid:
                metadata_block_event = {
                    "type": "content_block_start",
                    "index": content_index,
                    "content_block": {
                        "start_timestamp": datetime.utcnow().isoformat() + "Z",
                        "stop_timestamp": None,
                        "type": "metadata",
                        "metadata": {"session_uuid": current_session_uuid},
                    },
                }
                yield f"event: content_block_start\ndata: {json.dumps(metadata_block_event)}\n\n"

                # 메타데이터 블록 종료
                metadata_stop_event = {
                    "type": "content_block_stop",
                    "index": content_index,
                    "stop_timestamp": datetime.utcnow().isoformat() + "Z",
                }
                yield f"event: content_block_stop\ndata: {json.dumps(metadata_stop_event)}\n\n"
                content_index += 1

            # 메인 텍스트 content block 시작
            content_block_event = {
                "type": "content_block_start",
                "index": content_index,
                "content_block": {
                    "start_timestamp": content_block_start_timestamp,
                    "stop_timestamp": None,
                    "type": "text",
                    "text": "",
                    "citations": [],
                },
            }
            yield f"event: content_block_start\ndata: {json.dumps(content_block_event)}\n\n"

            # 무역 전문가 시스템 프롬프트 추가
            system_prompt = (
                "당신은 대한민국의 무역 및 수출입 전문가입니다. 다음 지침을 엄격히 준수하세요:\n\n"
                "1. **무역 관련 질문만 답변**: 무역, 수출입, 관세, 통관, 원산지, FTA, 무역규제, 품목분류, HSCode 등과 관련된 질문에만 답변합니다.\n\n"
                "2. **무역 외 질문 거부**: 무역과 관련이 없는 질문(일반상식, 개인적 조언, 오락, 요리, 여행 등)에 대해서는 다음과 같이 정중히 거부합니다:\n"
                "   '죄송하지만 저는 무역 및 수출입 전문 AI입니다. 무역, 관세, 통관, 수출입 규제 등과 관련된 질문만 답변할 수 있습니다. 무역 관련 질문이 있으시면 언제든지 문의해 주세요.'\n\n"
                "3. **전문적 답변**: 무역 관련 질문에 대해서는 정확하고 전문적인 정보를 제공하며, 최신 규정과 정책 변화를 반영합니다.\n\n"
                "4. **한국어 답변**: 모든 답변은 한국어로 제공합니다.\n\n"
                "5. **안전성**: 불법적이거나 유해한 무역 행위에 대해서는 조언하지 않습니다."
            )

            # 메시지 구성
            messages = []

            # 시스템 프롬프트 추가
            from langchain_core.messages import SystemMessage

            messages.append(SystemMessage(content=system_prompt))

            # 이전 대화 내역 추가 (있는 경우)
            if previous_messages:
                messages.extend(previous_messages)

            # 현재 사용자 메시지 추가
            messages.append(HumanMessage(content=chat_request.message))

            # 직접 ChatAnthropic 모델로 스트리밍 - 한 글자씩 스트리밍됨
            ai_response = ""

            try:
                # langchain의 astream 메서드를 사용하여 토큰별 스트리밍
                async for chunk in chat_model.astream(messages):
                    # chunk.content가 문자열인 경우 직접 사용
                    if hasattr(chunk, "content") and chunk.content:
                        chunk_text = ""
                        if isinstance(chunk.content, str):
                            chunk_text = chunk.content
                        elif isinstance(chunk.content, list) and chunk.content:
                            # content가 list인 경우 첫 번째 요소 사용
                            chunk_text = str(chunk.content[0])

                        if chunk_text:
                            ai_response += chunk_text

                            # content_block_delta 이벤트로 텍스트 전송
                            delta_event = {
                                "type": "content_block_delta",
                                "index": content_index,
                                "delta": {"type": "text_delta", "text": chunk_text},
                            }
                            yield f"event: content_block_delta\ndata: {json.dumps(delta_event)}\n\n"

            except Exception as stream_error:
                logger.error(
                    f"모델 스트리밍 중 오류 발생: {stream_error}", exc_info=True
                )
                # 에러 발생 시 에러 메시지를 delta로 전송
                error_text = "AI 응답 생성 중 오류가 발생했습니다."
                error_delta_event = {
                    "type": "content_block_delta",
                    "index": content_index,
                    "delta": {"type": "text_delta", "text": error_text},
                }
                yield f"event: content_block_delta\ndata: {json.dumps(error_delta_event)}\n\n"
                ai_response = error_text

            # content block 종료
            content_stop_event = {
                "type": "content_block_stop",
                "index": content_index,
                "stop_timestamp": datetime.utcnow().isoformat() + "Z",
            }
            yield f"event: content_block_stop\ndata: {json.dumps(content_stop_event)}\n\n"

            # 2. AI 응답 메시지 저장 (회원인 경우)
            if user_id and history and ai_response:
                async with db.begin_nested() as ai_message_savepoint:
                    try:
                        from langchain_core.messages import AIMessage

                        ai_message = AIMessage(content=ai_response)
                        await history.aadd_message(ai_message)
                        await db.flush()
                        await ai_message_savepoint.commit()

                    except Exception as ai_save_error:
                        logger.error(
                            f"AI 응답 저장 중 오류 발생: {ai_save_error}", exc_info=True
                        )
                        await ai_message_savepoint.rollback()
                        # AI 응답 저장 실패해도 응답은 계속 진행

            # 3. 세션 제목 자동 생성 (새 세션이고 첫 번째 대화인 경우)
            if user_id and is_new_session and session_obj and ai_response:
                async with db.begin_nested() as title_savepoint:
                    try:
                        generated_title = await generate_session_title(
                            chat_request.message, ai_response
                        )

                        # 세션 제목 업데이트
                        setattr(session_obj, "session_title", generated_title)
                        await db.flush()
                        await title_savepoint.commit()

                        logger.info(f"세션 제목 자동 생성 완료: {generated_title}")

                    except Exception as title_error:
                        logger.error(
                            f"세션 제목 생성 중 오류 발생: {title_error}", exc_info=True
                        )
                        await title_savepoint.rollback()
                        # 제목 생성 실패해도 응답은 계속 진행

            # 최종 커밋 (모든 세이브포인트가 성공한 경우에만)
            try:
                await db.commit()
            except Exception as commit_error:
                logger.error(f"최종 커밋 중 오류 발생: {commit_error}", exc_info=True)
                await db.rollback()

            # message_delta 이벤트 (stop_reason 포함)
            message_delta_event = {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            }
            yield f"event: message_delta\ndata: {json.dumps(message_delta_event)}\n\n"

            # message_limit 이벤트
            message_limit_event = {
                "type": "message_limit",
                "message_limit": {
                    "type": "within_limit",
                    "resetsAt": None,
                    "remaining": None,
                    "perModelLimit": None,
                },
            }
            yield f"event: message_limit\ndata: {json.dumps(message_limit_event)}\n\n"

            # message_stop 이벤트
            yield 'event: message_stop\ndata: {"type":"message_stop"}\n\n'

        except Exception as e:
            logger.error(f"채팅 스트림 처리 중 치명적 오류 발생: {e}", exc_info=True)

            # 치명적 오류 발생 시 전체 트랜잭션 롤백
            try:
                await db.rollback()
            except Exception as rollback_error:
                logger.error(f"롤백 중 추가 오류 발생: {rollback_error}", exc_info=True)

            # 에러를 content_block_delta로 전송
            error_text = "채팅 서비스에서 예기치 않은 오류가 발생했습니다."
            error_delta = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": error_text},
            }
            yield f"event: content_block_delta\ndata: {json.dumps(error_delta)}\n\n"

            # content block 종료
            error_stop = {
                "type": "content_block_stop",
                "index": 0,
                "stop_timestamp": datetime.utcnow().isoformat() + "Z",
            }
            yield f"event: content_block_stop\ndata: {json.dumps(error_stop)}\n\n"

            # message 종료
            yield f'event: message_delta\ndata: {{"type":"message_delta","delta":{{"stop_reason":"error","stop_sequence":null}}}}\n\n'
            yield 'event: message_stop\ndata: {"type":"message_stop"}\n\n'
