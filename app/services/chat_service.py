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
from langchain_core.output_parsers import StrOutputParser
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
from langchain_core.runnables import Runnable
from langchain_core.tracers.log_stream import RunLogPatch
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
from langchain_core.messages import AIMessageChunk

logger = logging.getLogger(__name__)


async def generate_session_title(user_message: str, ai_response: str) -> str:
    try:
        title_llm = ChatAnthropic(
            model_name="claude-3-5-haiku-20241022",
            api_key=SecretStr(settings.ANTHROPIC_API_KEY),
            temperature=0.3,
            max_tokens_to_sample=100,
            timeout=300.0,
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


async def update_session_title(
    session_uuid_str: str,
    user_message: str,
    ai_response: str,
):
    """세션 제목을 비동기적으로 생성하고 업데이트하는 백그라운드 작업"""
    async with SessionLocal() as db:
        try:
            title = await generate_session_title(user_message, ai_response)
            session_uuid = uuid.UUID(session_uuid_str)
            session = await db.get(db_models.ChatSession, session_uuid)
            if session:
                setattr(session, "session_title", title)
                await db.commit()
                logger.info(
                    f"세션(UUID: {session_uuid_str}) 제목 업데이트 완료: '{title}'"
                )
        except Exception as e:
            logger.error(
                f"세션(UUID: {session_uuid_str}) 제목 업데이트 실패: {e}", exc_info=True
            )
            await db.rollback()


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
            timeout=300.0,
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

            if is_hscode_intent:
                # 상태 업데이트: 상세 정보 준비 시작
                yield self.sse_generator.generate_processing_status_event(
                    "HSCode 상세 정보 준비 시작", 2, total_steps, is_sub_step=True
                )
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
            web_search_urls: List[str] = []

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
                        # await db.commit() # 트랜잭션 분리 문제를 해결하기 위해 이 커밋을 제거합니다.
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
            system_prompt = """
    [1. 역할 정의]
    당신은 'TrAI-Bot'입니다. 대한민국 중소기업의 수출입 담당자, 특히 이제 막 무역을 시작하는 실무자들을 돕기 위해 설계된, 신뢰할 수 있는 'AI 무역 전문가'이자 '든든한 파트너'입니다. 당신의 목표는 단순한 정보 전달을 넘어, 사용자가 겪는 불안감을 '확신'으로 바꾸어 주는 것입니다.

    [2. 핵심 임무]
    당신의 핵심 임무는 복잡하고 파편화된 무역 정보의 홍수 속에서, 사용자에게 '명확한 사실'과 '신뢰할 수 있는 출처'에 기반한 '실질적인 정보'를 제공하는 것입니다. 최신 자료 기준으로 웹 검색을 통해 최신 정보를 반영하여 답변을 생성하십시오. 항상 중립적이고 객관적인 사실만을 전달해야 합니다.

    [3. 전문 분야]
    당신은 아래 분야에 대한 깊이 있는 지식을 갖추고 있습니다.
    - HS 코드 분류 : 단순 코드 번호뿐만 아니라, 해당 코드로 분류되는 명확한 근거와 유사 코드와의 차이점까지 설명해야 합니다.
    - 관세 정보 : 기본 관세율, FTA 협정세율, 반덤핑 관세 등 모든 종류의 관세를 포함합니다.
    - **비관세장벽 (매우 중요)** : 사용자가 놓치기 쉬운 각국의 인증(KC, CE, FCC 등), 기술 표준(TBT), 위생 및 검역(SPS), 환경 규제, 라벨링 및 포장 규정 등을 관세 정보만큼, 혹은 그 이상으로 중요하게 다뤄야 합니다.
    - 수출입 통관 절차 및 필요 서류 : 각 국가별 통관 프로세스와 필수 서류(Invoice, B/L, C/O 등)를 안내합니다.

    [4. 행동 원칙]
    당신은 다음 원칙을 반드시 준수해야 합니다.
    1.  **출처 명시 최우선**: 모든 핵심 정보(HS 코드, 관세율, 규제 내용 등)는 반드시 공신력 있는 출처를 명시해야 합니다. 출처 없이는 답변하지 않습니다. 예: `(출처: 대한민국 관세청, 2025-07-07)`
    2.  **최신 정보 반영**: 반드시 어떠한 검색이던, 최신 정보 기준으로 반영하여 답변을 생성하십시오.
    3.  **비관세장벽 강조**: 사용자가 관세만 묻더라도, 해당 품목의 수출입에 영향을 미칠 수 있는 중요한 비관세장벽 정보가 있다면 반드시 함께 언급하여 잠재적 리스크를 알려주십시오.
    4.  **구조화된 답변**: 사용자가 쉽게 이해할 수 있도록, 답변을 명확한 소제목과 글머리 기호(bullet point)로 구조화하여 제공하십시오.
    5.  **쉬운 언어 사용**: 전문 용어 사용을 최소화하고, 무역 초보자도 이해할 수 있는 명확하고 간결한 언어로 설명하십시오.


    [5. 제약 조건]
    - 절대 법적, 재정적 자문을 제공하지 마십시오.
    - 개인적인 의견이나 추측을 포함하지 마십시오.
    - 특정 업체나 서비스를 추천하지 마십시오.
    - 정치적, 종교적으로 민감한 주제에 대해 언급하지 마십시오.
    - 오직 무역 관련 정보에만 집중하십시오.
    """
            messages: List[BaseMessage] = [SystemMessage(content=system_prompt)]
            messages.extend(previous_messages)

            # 5. 병렬 작업 시작 (HSCode 상세 버튼)
            # detail_page_generator = None
            # if is_hscode_intent:
            #     async for event in send_status(steps[2]):
            #         yield event

            #     # HSCode 사전 추출 로직을 제거하고, 메인 LLM이 컨텍스트를 활용하도록 함
            #     # _extract_hscode_from_message는 병렬 작업에서만 사용되도록 변경
            #     extracted_hscode, extracted_product_name = (
            #         await _extract_hscode_from_message(chat_request.message)
            #     )

            #     detail_page_generator = (
            #         self.parallel_task_manager.execute_parallel_tasks(
            #             chat_request,
            #             db,
            #             background_tasks,
            #             extracted_hscode,
            #             extracted_product_name,
            #         )
            #     )
            #     try:
            #         yield await detail_page_generator.__anext__()
            #     except StopAsyncIteration:
            #         pass

            # 6. AI의 사고 과정 및 최종 답변 스트리밍
            async for event in send_status(steps[3 if is_hscode_intent else 2]):
                yield event

            current_user_message = HumanMessage(content=chat_request.message)
            if is_hscode_intent:
                # 상세페이지 로직이 주석 처리되었으므로, 관련 변수를 None으로 초기화
                extracted_hscode, extracted_product_name = None, None
                current_user_message.content = (
                    self.hscode_classification_service.create_expert_prompt(
                        user_message=chat_request.message,
                        hscode=extracted_hscode,
                        product_name=extracted_product_name,
                    )
                )
            messages.append(current_user_message)

            # 6-1. 하트비트를 포함한 LLM 스트리밍 처리
            async for event_type, data in self._stream_llm_with_heartbeat(
                messages,
                chat_model,
                step_counter,
                total_steps,
            ):
                if event_type == "heartbeat":
                    yield data  # 하트비트 SSE 문자열
                elif event_type == "text_delta":
                    if not data:  # 빈 텍스트 델타는 무시
                        continue

                    final_response_text += data
                    delta_event = {
                        "type": "content_block_delta",
                        "index": content_index,
                        "delta": {"type": "text_delta", "text": data},
                    }
                    yield self.sse_generator._format_event(
                        "chat_content_delta", delta_event
                    )
                elif event_type == "tool_start":
                    yield data  # 도구 사용 시작 SSE 문자열
                elif event_type == "tool_end":
                    web_search_urls.extend(data.get("urls", []))
                    yield data.get("event_str")  # 웹 검색 완료 SSE 문자열

                    # hscode_classification 도구의 결과를 처리
                    if data.get("tool_name") == "hscode_classification":
                        tool_output = data.get("output")
                        if tool_output:
                            try:
                                # 도구 출력이 JSON 문자열일 수 있으므로 파싱
                                if isinstance(tool_output, str):
                                    tool_output = json.loads(tool_output)

                                final_hscode = tool_output.get("hscode")
                                product_name = tool_output.get("product_name")

                                if final_hscode:
                                    logger.info(
                                        f"Tool-based HSCode 추출 성공: {final_hscode}, 품목명: {product_name}"
                                    )
                                    yield self.sse_generator.generate_hscode_inferred_event(
                                        final_hscode, product_name
                                    )
                                else:
                                    logger.warning(
                                        "Tool-based HSCode 추출 실패: hscode 필드 없음"
                                    )
                            except (json.JSONDecodeError, AttributeError) as e:
                                logger.error(f"HSCode 도구 출력 파싱 실패: {e}")

            # 7. 스트리밍 종료 및 후처리
            yield self.sse_generator._format_event(
                "chat_content_stop",
                {"type": "content_block_stop", "index": content_index},
            )

            # 7-1. 최종 응답에서 HSCode 추출 및 이벤트 전송 (Tool 기반으로 변경되어 아래 로직 제거)
            # if is_hscode_intent and final_response_text:
            #     hscode_match = re.search(
            #         r"(?:가장 유력한 HS Code|HS Code|HS CODE)[:\s`]*(\d{4}\.\d{2}(?:\.\d{4})?|\d{6,10})",
            #         final_response_text,
            #         re.IGNORECASE,
            #     )
            #     if hscode_match:
            #         final_hscode = hscode_match.group(1)
            #         # 품목명은 사용자 메시지 기반으로 다시 추출
            #         _, product_name_for_event = await _extract_hscode_from_message(
            #             chat_request.message
            #         )
            #         logger.info(
            #             f"최종 응답에서 HSCode 추출 성공: {final_hscode}, 품목명: {product_name_for_event}"
            #         )
            #         yield self.sse_generator.generate_hscode_inferred_event(
            #             final_hscode, product_name_for_event
            #         )
            #     else:
            #         logger.warning("최종 응답에서 HSCode를 추출하지 못했습니다.")

            # 7-2. 웹 검색 결과가 있으면 이벤트 전송
            if web_search_urls:
                yield self.sse_generator._format_event(
                    "web_search_results",
                    {
                        "type": "web_search_results",
                        "urls": web_search_urls,
                        "timestamp": self.sse_generator._get_timestamp(),
                    },
                )

            # 8. 병렬 작업(상세 버튼) 나머지 결과 스트리밍
            # if detail_page_generator:
            #     async for event in detail_page_generator:
            #         yield event

            # 9. 대화 내용 저장
            async for event in send_status(steps[-1]):
                yield event

            if user_id and history and final_response_text:
                try:
                    # AI 응답 저장
                    ai_message = AIMessage(content=final_response_text)
                    await history.aadd_message(ai_message)

                    # 세션 제목 생성 (새 세션인 경우에만)
                    if is_new_session and session_obj:
                        background_tasks.add_task(
                            update_session_title,
                            str(session_obj.session_uuid),
                            chat_request.message,
                            final_response_text,
                        )

                    await db.commit()
                    logger.info("대화 내용이 성공적으로 저장되었습니다.")
                except Exception as db_error:
                    logger.error(f"대화 내용 저장 실패: {db_error}", exc_info=True)
                    await db.rollback()

            yield self.sse_generator._format_event(
                "chat_message_delta",
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            )
            yield self.sse_generator.generate_stream_end_event()

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
            yield self.sse_generator.generate_stream_end_event()

    async def _stream_llm_with_heartbeat(
        self,
        messages: List[BaseMessage],
        chat_model: Runnable,
        step_counter: int,
        total_steps: int,
        heartbeat_interval: int = 10,
        tool_timeout: int = 180,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        """
        LLM 응답을 스트리밍하면서, 응답이 없을 경우 주기적으로 하트비트 이벤트를 전송.
        `astream_events` API (v2)를 사용하여 이벤트 기반으로 처리함.
        (이벤트 타입, 데이터) 튜플을 반환.
        """
        is_tool_running = False
        last_event_time = time.time()
        web_search_args = {}

        async def producer():
            nonlocal is_finished
            try:
                async for chunk in chat_model.astream_log(
                    messages,
                    include_names=["hscode_llm_with_web_search", "news_chat_model"],
                ):
                    await queue.put(chunk)
            except Exception as e:
                logger.error(
                    f"LLM 스트리밍 중 오류 발생 (producer): {e}", exc_info=True
                )
                await queue.put(e)
            finally:
                is_finished = True
                await queue.put(None)

        producer_task = asyncio.create_task(producer())
        active_tool_calls: Dict[str, Dict] = {}

        while not is_finished:
            try:
                # 도구 실행 중에는 더 긴 타임아웃 적용
                timeout = tool_timeout if is_tool_running else heartbeat_interval
                event = await asyncio.wait_for(queue.get(), timeout=timeout)

                if event is None:
                    break
                if isinstance(event, Exception):
                    raise event
                if not isinstance(event, RunLogPatch):
                    continue

                for op in event.ops:
                    path = op.get("path", "")
                    value = op.get("value")

                    if op["op"] == "add" and "/streamed_output/-" in path:
                        if isinstance(value, AIMessageChunk):
                            text_content = ""
                            if isinstance(value.content, list):
                                for content_block in value.content:
                                    if isinstance(
                                        content_block, dict
                                    ) and content_block.get("type") in [
                                        "text",
                                        "text_delta",
                                    ]:
                                        text_content += content_block.get("text", "")
                            elif isinstance(value.content, str):
                                text_content = value.content

                            if text_content:
                                yield "text_delta", text_content

                    elif op["op"] == "add" and path.endswith("/tool_calls/-"):
                        if value and "id" in value:
                            tool_call_id = value["id"]
                            active_tool_calls[tool_call_id] = value
                            if value.get("name") == "web_search":
                                is_tool_running = True
                                event_str = self.sse_generator.generate_tool_use_event(
                                    "web_search", value.get("args", {}), tool_call_id
                                )
                                yield "tool_start", event_str

                elif (
                    kind == "on_tool_end"
                ):  # and name == "web_search": <- web_search뿐만 아니라 모든 도구 처리
                    is_tool_running = False
                    output = event["data"].get("output")
                    tool_name = name
                    urls = []

                    if tool_name == "web_search":
                        if isinstance(output, str):
                            try:
                                tool_output = json.loads(output)
                                results = tool_output.get("results", [])
                                urls.extend(
                                    r["url"]
                                    for r in results
                                    if isinstance(r, dict) and "url" in r
                                )
                            except json.JSONDecodeError:
                                logger.warning("웹 검색 결과 JSON 파싱 실패")
                                pass

                        status_message = (
                            f"웹 검색 완료. {len(urls)}개의 출처를 찾았습니다."
                        )
                        event_str_status = (
                            self.sse_generator.generate_processing_status_event(
                                status_message,
                                step_counter,
                                total_steps,
                                is_sub_step=True,
                            )
                        )
                        yield "thinking", event_str_status

                    event_str_tool = self.sse_generator.generate_tool_use_end_event(
                        tool_name, output, event["run_id"]
                    )
                    yield "tool_end", {
                        "urls": urls,
                        "event_str": event_str_tool,
                        "tool_name": tool_name,
                        "output": output,
                    }

                # 주기적인 하트비트 (응답이 너무 길어질 경우)
                if time.time() - last_event_time > heartbeat_interval:
                    if is_tool_running:
                        message = "외부 도구(웹 검색 등)를 사용하여 정보를 탐색하고 있습니다. 최대 3분까지 소요될 수 있습니다."
                    else:
                        message = "AI가 답변을 생성중입니다. 잠시만 기다려주세요..."

                    event_str = self.sse_generator.generate_processing_status_event(
                        message,
                        step_counter,
                        total_steps,
                        is_sub_step=True,
                    )
                    yield "heartbeat", event_str
                    last_event_time = time.time()

        except Exception as e:
            logger.error(
                f"LLM 스트리밍 중 오류 발생 (astream_events): {e}", exc_info=True
            )
            # 여기서 예외를 다시 발생시켜 상위 핸들러가 처리하도록 할 수 있음
            raise
