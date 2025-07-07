import logging
import json
import re
import time
import asyncio
from typing import (
    AsyncGenerator,
    Dict,
    Any,
    List,
    cast,
    Union,
    Optional,
    Tuple,
)
import uuid
from datetime import datetime

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse
from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
    BaseMessage,
)
from pydantic import SecretStr

from app.db import crud
from app.db.session import SessionLocal
from app.models.chat_models import (
    ChatRequest,
    CargoTrackingResponse,
    CargoTrackingError,
)
from app.services.chat_history_service import PostgresChatMessageHistory
from app.services.langchain_service import LLMService
from app.services.cargo_tracking_service import CargoTrackingService
from app.services.hscode_classification_service import HSCodeClassificationService
from app.services.intent_classification_service import (
    IntentClassificationService,
    IntentType,
)
from app.services.enhanced_detail_generator import EnhancedDetailGenerator
from app.core.config import settings
from app.core.llm_provider import llm_provider
from app.services.parallel_task_manager import ParallelTaskManager
from app.services.sse_event_generator import SSEEventGenerator
from app.models import db_models

logger = logging.getLogger(__name__)


async def generate_session_title(user_message: str, ai_response: str) -> str:
    try:
        title_llm = ChatAnthropic(
            model_name="claude-3-5-haiku-20241022",
            api_key=SecretStr(settings.ANTHROPIC_API_KEY),
            temperature=0.3,
            max_tokens_to_sample=100,
            timeout=None,
            stop=None,
        )
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
        response = await title_llm.ainvoke([HumanMessage(content=prompt)])
        from app.utils.llm_response_parser import extract_text_from_anthropic_response

        title = extract_text_from_anthropic_response(response).strip()
        if not title:
            fallback_title = user_message[:30].strip()
            if len(user_message) > 30:
                fallback_title += "..."
            return fallback_title
        title = title.strip('"').strip("'")
        if len(title) > 50:
            title = title[:47] + "..."
        return title
    except Exception as e:
        logger.warning(f"세션 제목 자동 생성 실패: {e}")
        fallback_title = user_message[:30].strip()
        if len(user_message) > 30:
            fallback_title += "..."
        return fallback_title


async def _extract_hscode_from_message(
    message: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    사용자 메시지에서 HSCode와 품목명을 추출하는 경량화된 LLM 호출.
    메인 LLM 호출 전에 실행하여 HSCode를 확정함.
    """
    try:
        extractor_llm = ChatAnthropic(
            model_name="claude-3-5-haiku-20241022",
            api_key=SecretStr(settings.ANTHROPIC_API_KEY),
            temperature=0.0,
            max_tokens_to_sample=200,
            timeout=None,
            stop=None,
        )
        prompt = f"""사용자의 다음 메시지에서 HSCode와 가장 핵심적인 품목명을 추출해주세요.
- HSCode는 숫자와 점(.)으로 구성됩니다 (예: 8471.30.0000).
- 품목명은 제품을 가장 잘 나타내는 간단한 명사입니다.
- 둘 중 하나 또는 둘 다 없을 수 있습니다.
- 결과는 반드시 다음 JSON 형식으로만 응답해주세요. 다른 설명은 절대 추가하지 마세요.

{{
  "hscode": "추출된 HSCode 또는 null",
  "product_name": "추출된 품목명 또는 null"
}}

사용자 메시지: "{message}"
"""
        response = await extractor_llm.ainvoke([HumanMessage(content=prompt)])
        from app.utils.llm_response_parser import extract_text_from_anthropic_response

        content = extract_text_from_anthropic_response(response)
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if not json_match:
            logger.warning("HSCode 추출기에서 JSON 응답을 찾지 못했습니다.")
            return None, None
        result = json.loads(json_match.group())
        hscode = result.get("hscode")
        product_name = result.get("product_name")
        logger.info(f"HSCode 예비 추출 결과: 코드={hscode}, 품목명={product_name}")
        return hscode, product_name
    except Exception as e:
        logger.error(f"HSCode 예비 추출 실패: {e}", exc_info=True)
        return None, None


class ChatService:
    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service
        self.cargo_tracking_service = CargoTrackingService()
        self.hscode_classification_service = HSCodeClassificationService()
        self.intent_classification_service = IntentClassificationService()
        self.enhanced_detail_generator = EnhancedDetailGenerator()
        self.parallel_task_manager = ParallelTaskManager()
        self.sse_generator = SSEEventGenerator()

    def _convert_datetime_to_string(self, data: Dict[str, Any]) -> None:
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
            elif isinstance(value, dict):
                self._convert_datetime_to_string(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._convert_datetime_to_string(item)

    async def check_unified_intent(
        self, chat_request: ChatRequest
    ) -> Union[Dict[str, Any], None]:
        start_time = time.time()
        try:
            intent_result = await self.intent_classification_service.classify_intent(
                chat_request.message
            )
            intent_type = intent_result.intent_type
            confidence = intent_result.confidence_score
            logger.info(
                f"통합 의도 분류 결과: {intent_type.value}, 신뢰도: {confidence:.3f}"
            )
            if intent_type == IntentType.CARGO_TRACKING:
                logger.info(f"화물통관 조회 의도 감지됨: 신뢰도 {confidence:.3f}")
                cargo_data = (
                    await self.cargo_tracking_service.extract_cargo_information(
                        chat_request.message
                    )
                )
                processing_time_ms = int((time.time() - start_time) * 1000)
                if cargo_data:
                    response = (
                        await self.cargo_tracking_service.create_success_response(
                            cargo_data=cargo_data,
                            session_uuid=chat_request.session_uuid,
                            user_id=chat_request.user_id,
                            processing_time_ms=processing_time_ms,
                        )
                    )
                    response_dict = response.model_dump()
                    self._convert_datetime_to_string(response_dict)
                    return response_dict
                else:
                    error_response = (
                        await self.cargo_tracking_service.create_error_response(
                            error_code="CARGO_NUMBER_NOT_FOUND",
                            error_message="메시지에서 화물번호를 찾을 수 없습니다.",
                            original_message=chat_request.message,
                            session_uuid=chat_request.session_uuid,
                            user_id=chat_request.user_id,
                        )
                    )
                    error_dict = error_response.model_dump()
                    self._convert_datetime_to_string(error_dict)
                    return error_dict
            elif intent_type == IntentType.HSCODE_CLASSIFICATION:
                logger.info(f"HSCode 분류 의도 감지됨: 신뢰도 {confidence:.3f}")
                logger.info(
                    "HSCode 분류는 SSE 스트리밍으로 처리하기 위해 일반 채팅으로 분류"
                )
                return None
            else:
                logger.info(f"일반 채팅 의도로 분류됨: {intent_type.value}")
                return None
        except Exception as intent_error:
            logger.error(f"통합 의도 분류 처리 중 오류: {intent_error}", exc_info=True)
            return None

    async def _get_session_info(
        self, db: AsyncSession, user_id: int, session_uuid_str: str
    ) -> Tuple[
        PostgresChatMessageHistory,
        db_models.ChatSession,
        str,
        List[BaseMessage],
        bool,
    ]:
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select

        session_obj = await crud.chat.get_session_by_uuid(
            db=db, user_id=user_id, session_uuid_str=session_uuid_str
        )

        # 세션에 메시지가 없는 경우, 즉 첫 대화인 경우 '새 세션'으로 간주하여 제목 생성
        is_new_session = not session_obj.messages

        history = PostgresChatMessageHistory(
            db=db, user_id=user_id, session=session_obj
        )
        current_session_uuid = str(session_obj.session_uuid)
        previous_messages = await history.aget_messages()

        return (
            history,
            session_obj,
            current_session_uuid,
            previous_messages,
            is_new_session,
        )

    async def stream_chat_response(
        self,
        chat_request: ChatRequest,
        db: AsyncSession,
        background_tasks: BackgroundTasks,
    ) -> AsyncGenerator[str, None]:
        user_id = chat_request.user_id
        session_uuid_str = chat_request.session_uuid
        message_id = f"chatcompl_{uuid.uuid4().hex[:24]}"
        parent_uuid = str(uuid.uuid4())
        message_uuid = str(uuid.uuid4())
        content_index = 0
        final_response_text = ""
        is_new_session = False
        previous_messages: List[BaseMessage] = []

        # --- 단계별 상태 메시지 정의 ---
        steps = [
            "사용자 요청 분석",
            "대화 맥락 파악",
            "AI 생각 및 정보 검색",
            "AI 답변 생성",
        ]
        is_hscode_intent = (
            await self.intent_classification_service.classify_intent(
                chat_request.message
            )
        ).intent_type == IntentType.HSCODE_CLASSIFICATION

        if is_hscode_intent:
            steps.insert(2, "상세 정보 준비")
        if user_id:
            steps.append("대화 내용 저장")
        total_steps = len(steps)
        step_counter = 0

        async def send_status(message: str) -> AsyncGenerator[str, None]:
            nonlocal step_counter
            step_counter += 1
            yield self.sse_generator.generate_processing_status_event(
                message, step_counter, total_steps
            )
            await asyncio.sleep(0.1)

        try:
            # 1. 사용자 요청 분석 및 LLM 모델 선택
            async for event in send_status(steps[0]):
                yield event
            extracted_hscode, extracted_product_name = None, None
            if is_hscode_intent:
                extracted_hscode, extracted_product_name = (
                    await _extract_hscode_from_message(chat_request.message)
                )
                chat_model = llm_provider.hscode_llm_with_web_search
            else:
                chat_model = llm_provider.news_chat_model

            # 2. 대화 맥락 파악 (DB 처리)
            async for event in send_status(steps[1]):
                yield event
            history: Optional[PostgresChatMessageHistory] = None
            session_obj: Optional[db_models.ChatSession] = None
            current_session_uuid: Optional[str] = None

            if user_id:
                try:
                    (
                        history,
                        session_obj,
                        current_session_uuid,
                        previous_messages,
                        is_new_session,
                    ) = await self._get_session_info(db, user_id, session_uuid_str)

                    if history:
                        human_message = HumanMessage(content=chat_request.message)
                        await history.aadd_message(human_message)
                        await db.commit()
                except Exception as db_error:
                    logger.error(f"DB 처리 중 오류: {db_error}", exc_info=True)
                    await db.rollback()
                    user_id = None

            # 3. 초기 SSE 이벤트 전송
            yield self.sse_generator._format_event(
                "chat_message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": message_id,
                        "type": "message",
                        "role": "assistant",
                        "model": settings.ANTHROPIC_MODEL,
                        "parent_uuid": parent_uuid,
                        "uuid": message_uuid,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                    },
                },
            )
            if is_new_session and current_session_uuid:
                yield self.sse_generator._format_event(
                    "chat_metadata_start",
                    {
                        "type": "content_block_start",
                        "index": content_index,
                        "content_block": {
                            "type": "metadata",
                            "metadata": {"session_uuid": current_session_uuid},
                        },
                    },
                )
                yield self.sse_generator._format_event(
                    "chat_metadata_stop",
                    {"type": "content_block_stop", "index": content_index},
                )
                content_index += 1
            yield self.sse_generator._format_event(
                "chat_content_start",
                {
                    "type": "content_block_start",
                    "index": content_index,
                    "content_block": {"type": "text", "text": ""},
                },
            )

            # 4. 시스템 프롬프트 및 메시지 구성
            system_prompt = (
                "당신은 대한민국의 무역 및 수출입 전문가입니다..."  # 전체 프롬프트 생략
            )
            messages: List[BaseMessage] = [SystemMessage(content=system_prompt)]
            messages.extend(previous_messages)

            # 5. 병렬 작업 시작 (HSCode 상세 버튼)
            detail_page_generator = None
            if is_hscode_intent:
                async for event in send_status(steps[2]):
                    yield event
                detail_page_generator = (
                    self.parallel_task_manager.execute_parallel_tasks(
                        chat_request,
                        db,
                        background_tasks,
                        extracted_hscode,
                        extracted_product_name,
                    )
                )
                try:
                    yield await detail_page_generator.__anext__()
                except StopAsyncIteration:
                    pass

            # 6. AI의 사고 과정 및 최종 답변 스트리밍
            async for event in send_status(steps[3 if is_hscode_intent else 2]):
                yield event

            current_user_message = HumanMessage(content=chat_request.message)
            if is_hscode_intent:
                current_user_message.content = (
                    self.hscode_classification_service.create_expert_prompt(
                        user_message=chat_request.message,
                        hscode=extracted_hscode,
                        product_name=extracted_product_name,
                    )
                )
            messages.append(current_user_message)

            async for event in chat_model.astream_events(messages, version="v2"):
                kind = event["event"]

                if kind == "on_chat_model_start":
                    # Anthropic 'thinking' 이벤트 처리
                    if "thinking" in event["data"]:
                        for thought in event["data"]["thinking"]:
                            yield self.sse_generator.generate_thinking_process_event(
                                thought
                            )

                if kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if not chunk:
                        continue

                    # AIMessageChunk의 content가 리스트 형태일 경우 처리 (Anthropic 모델 대응)
                    if isinstance(chunk.content, list):
                        for content_block in chunk.content:
                            if isinstance(content_block, dict):
                                block_type = content_block.get("type")
                                if block_type in ["text_delta", "text"]:
                                    text_content = content_block.get("text", "")
                                    if text_content:
                                        final_response_text += text_content
                                        delta_event = {
                                            "type": "content_block_delta",
                                            "index": content_index,
                                            "delta": {
                                                "type": "text_delta",
                                                "text": text_content,
                                            },
                                        }
                                        yield self.sse_generator._format_event(
                                            "chat_content_delta", delta_event
                                        )
                    # 기존 문자열 content 처리 (하위 호환성)
                    elif isinstance(chunk.content, str) and chunk.content:
                        final_response_text += chunk.content
                        delta_event = {
                            "type": "content_block_delta",
                            "index": content_index,
                            "delta": {"type": "text_delta", "text": chunk.content},
                        }
                        yield self.sse_generator._format_event(
                            "chat_content_delta", delta_event
                        )

                elif kind == "on_tool_start":
                    tool_name = event["data"].get("name")
                    tool_input = event["data"].get("input")
                    run_id = event.get("run_id")
                    if (
                        isinstance(tool_name, str)
                        and isinstance(tool_input, dict)
                        and run_id
                    ):
                        yield self.sse_generator.generate_tool_use_event(
                            tool_name, tool_input, str(run_id)
                        )

                elif kind == "on_tool_end" and event.get("name") == "web_search":
                    # 웹 검색 종료 시, 간략한 상태 업데이트 제공
                    yield self.sse_generator.generate_processing_status_event(
                        "웹 검색 완료, 답변 생성 중",
                        step_counter,
                        total_steps,
                        is_sub_step=True,
                    )

            # 7. 스트림 종료 및 후처리
            yield self.sse_generator._format_event(
                "chat_content_stop",
                {"type": "content_block_stop", "index": content_index},
            )
            if detail_page_generator:
                async for event in detail_page_generator:
                    yield event

            if user_id and history and final_response_text:
                async for event in send_status(steps[-1]):
                    yield event
                await history.aadd_message(AIMessage(content=final_response_text))
                await db.commit()

            if user_id and is_new_session and session_obj and final_response_text:
                title = await generate_session_title(
                    chat_request.message, final_response_text
                )
                setattr(session_obj, "session_title", title)
                await db.commit()

            yield self.sse_generator._format_event(
                "chat_message_delta",
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            )
            yield 'event: chat_message_stop\ndata: {"type":"message_stop"}\n\n'

        except Exception as e:
            logger.error(f"채팅 스트림 처리 중 치명적 오류 발생: {e}", exc_info=True)
            await db.rollback()
            error_text = "채팅 서비스에서 예기치 않은 오류가 발생했습니다."
            yield self.sse_generator._format_event(
                "chat_content_delta",
                {
                    "type": "content_block_delta",
                    "index": content_index,
                    "delta": {"type": "text_delta", "text": error_text},
                },
            )
            yield self.sse_generator._format_event(
                "chat_content_stop",
                {"type": "content_block_stop", "index": content_index},
            )
            yield self.sse_generator._format_event(
                "chat_message_delta",
                {"type": "message_delta", "delta": {"stop_reason": "error"}},
            )
            yield 'event: chat_message_stop\ndata: {"type":"message_stop"}\n\n'
