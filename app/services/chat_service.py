import logging
import json
import re
import time  # 추가
import asyncio  # 추가
from typing import AsyncGenerator, Dict, Any, List, cast, Union  # Union 추가
import uuid
from datetime import datetime

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse  # 추가
from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from pydantic import SecretStr

from app.db import crud
from app.db.session import SessionLocal, get_db
from app.models.chat_models import (
    ChatRequest,
    CargoTrackingResponse,
    CargoTrackingError,
)  # 추가
from app.services.chat_history_service import PostgresChatMessageHistory
from app.services.langchain_service import LLMService
from app.services.cargo_tracking_service import CargoTrackingService  # 추가
from app.services.hscode_classification_service import (
    HSCodeClassificationService,
)  # HSCode 분류 서비스 추가
from app.services.intent_classification_service import (
    IntentClassificationService,
    IntentType,
)  # 고급 의도 분류 서비스 추가
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

        # 응답 텍스트 추출 (타입 안전)
        from app.utils.llm_response_parser import extract_text_from_anthropic_response

        title = extract_text_from_anthropic_response(response).strip()

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
        self.cargo_tracking_service = (
            CargoTrackingService()
        )  # 화물통관 조회 서비스 추가
        self.hscode_classification_service = (
            HSCodeClassificationService()
        )  # HSCode 분류 서비스 추가
        self.intent_classification_service = (
            IntentClassificationService()
        )  # 고급 의도 분류 서비스 추가
        # 병렬 처리 매니저 추가
        from app.services.parallel_task_manager import ParallelTaskManager

        self.parallel_task_manager = ParallelTaskManager()

    def _convert_datetime_to_string(self, data: Dict[str, Any]) -> None:
        """딕셔너리에서 datetime 객체를 ISO 문자열로 변환하여 JSON 직렬화 문제 해결"""
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
        """
        통합 의도 분류: 한 번의 호출로 모든 의도를 분류하여 중복 호출 문제 해결.

        Returns:
            특수 응답 딕셔너리 또는 None (일반 채팅 처리 필요)
        """
        start_time = time.time()

        try:
            # 한 번의 의도 분류로 모든 의도 확인
            intent_result = await self.intent_classification_service.classify_intent(
                chat_request.message
            )

            intent_type = intent_result.intent_type
            confidence = intent_result.confidence_score

            logger.info(
                f"통합 의도 분류 결과: {intent_type.value}, 신뢰도: {confidence:.3f}"
            )

            # 1. 화물통관 조회 처리
            if intent_type == IntentType.CARGO_TRACKING:
                logger.info(f"화물통관 조회 의도 감지됨: 신뢰도 {confidence:.3f}")

                # 화물 정보 추출
                cargo_data = (
                    await self.cargo_tracking_service.extract_cargo_information(
                        chat_request.message
                    )
                )

                processing_time_ms = int((time.time() - start_time) * 1000)

                if cargo_data:
                    # 성공 응답 생성
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
                    # 화물번호 추출 실패
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

            # 2. HSCode 분류 처리 - SSE 스트리밍으로 처리하기 위해 일반 채팅으로 분류
            elif intent_type == IntentType.HSCODE_CLASSIFICATION:
                logger.info(f"HSCode 분류 의도 감지됨: 신뢰도 {confidence:.3f}")
                logger.info(
                    "HSCode 분류는 SSE 스트리밍으로 처리하기 위해 일반 채팅으로 분류"
                )
                # HSCode 분류는 SSE 스트리밍으로 처리하기 위해 None 반환
                return None

            # 3. 기타 의도 (일반 채팅으로 처리)
            else:
                logger.info(f"일반 채팅 의도로 분류됨: {intent_type.value}")
                return None

        except Exception as intent_error:
            logger.error(f"통합 의도 분류 처리 중 오류: {intent_error}", exc_info=True)
            return None  # 에러 발생 시 일반 채팅으로 폴백

    # 기존 메서드들을 deprecated로 표시하고 새 메서드로 리다이렉트
    async def check_cargo_tracking_intent(
        self, chat_request: ChatRequest
    ) -> Union[Dict[str, Any], None]:
        """
        화물통관 조회 의도 확인 (deprecated - check_unified_intent 사용 권장)
        """
        logger.info(
            "⚠️ DEPRECATED: check_cargo_tracking_intent 호출됨 - check_unified_intent 사용 권장"
        )
        result = await self.check_unified_intent(chat_request)
        # 화물통관 결과만 필터링
        if result and result.get("intent_type") == "cargo_tracking":
            return result
        return None

    async def check_hscode_classification_intent(
        self, chat_request: ChatRequest
    ) -> Union[Dict[str, Any], None]:
        """
        HSCode 분류 의도 확인 (deprecated - 이제 항상 None 반환)
        """
        logger.info(
            "⚠️ DEPRECATED: check_hscode_classification_intent 호출됨 - HSCode 분류는 일반 채팅으로 처리"
        )
        # HSCode 분류는 이제 항상 일반 채팅으로 처리
        return None

    async def _convert_json_to_streaming_response(
        self,
        json_response: Dict[str, Any],
        message_id: str,
        parent_uuid: str,
        message_uuid: str,
    ) -> AsyncGenerator[str, None]:
        """
        JSON 응답을 Anthropic Claude API 형식의 SSE 스트림으로 변환함.
        화물통관 조회 등의 특수 응답을 스트리밍 형태로 변환.
        """
        try:
            # message_start 이벤트
            message_start_event = {
                "type": "message_start",
                "message": {
                    "id": message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": "special_service",
                    "parent_uuid": parent_uuid,
                    "uuid": message_uuid,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                },
            }
            yield f"event: chat_message_start\ndata: {json.dumps(message_start_event)}\n\n"

            # content_block_start 이벤트
            content_block_event = {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "start_timestamp": datetime.utcnow().isoformat() + "Z",
                    "stop_timestamp": None,
                    "type": "text",
                    "text": "",
                    "citations": [],
                },
            }
            yield f"event: chat_content_start\ndata: {json.dumps(content_block_event)}\n\n"

            # JSON 응답을 텍스트로 변환
            if json_response.get("type") == "preliminary_hscode_info":
                # 초기 HSCode 정보 제공 (화이트리스트 검색 결과)
                preliminary_result = json_response.get("preliminary_search_result", "")
                response_text = preliminary_result

            elif json_response.get("type") == "professional_hscode_classification":
                # 전문적인 HSCode 분류 결과
                result_data = json_response.get("classification_result", {})
                response_text = f"""## 🎯 전문 HSCode 분류 결과

### 📋 분류 정보
**HSCode**: `{result_data.get('hscode', 'N/A')}`
**신뢰도**: {result_data.get('confidence_score', 0.0):.1%}

### 📖 분류 근거
{result_data.get('classification_reason', '분류 근거 정보 없음')}

### ⚖️ 적용된 GRI 통칙
{result_data.get('gri_application', 'GRI 통칙 정보 없음')}

### ⚠️ 위험 평가
{result_data.get('risk_assessment', '위험 평가 정보 없음')}"""

                # 대안 코드가 있는 경우 추가
                if result_data.get("alternative_codes"):
                    alt_codes = result_data.get("alternative_codes", [])
                    response_text += f"\n\n### 🔄 대안 HSCode\n" + "\n".join(
                        f"- `{code}`" for code in alt_codes
                    )

                # 검증 출처가 있는 경우 추가
                if result_data.get("verification_sources"):
                    sources = result_data.get("verification_sources", [])
                    response_text += f"\n\n### 📚 참조 출처\n" + "\n".join(
                        f"- {source}" for source in sources
                    )

                # 권장사항이 있는 경우 추가
                if result_data.get("recommendations"):
                    recommendations = result_data.get("recommendations", [])
                    response_text += f"\n\n### 💡 권장사항\n" + "\n".join(
                        f"- {rec}" for rec in recommendations
                    )

            elif json_response.get("type") == "classification_result":
                # 기존 HSCode 분류 결과 (하위 호환성)
                result_data = json_response.get("result", {})
                response_text = f"""## HSCode 분류 결과

**분류 코드**: {result_data.get('hscode', 'N/A')}
**신뢰도**: {result_data.get('confidence_score', 0.0):.2%}

**분류 근거**:
{result_data.get('classification_reason', '')}

**적용 규칙**:
{result_data.get('gri_application', '')}

**위험 평가**:
{result_data.get('risk_assessment', '')}
"""
                if result_data.get("alternative_codes"):
                    response_text += f"\n**대안 코드**: {', '.join(result_data.get('alternative_codes', []))}"

                if result_data.get("recommendations"):
                    response_text += f"\n\n**권장사항**:\n" + "\n".join(
                        f"- {rec}" for rec in result_data.get("recommendations", [])
                    )

            elif json_response.get("intent_type") == "cargo_tracking":
                # 화물통관 조회 응답
                if json_response.get("status") == "success":
                    cargo_data = json_response.get("cargo_data", {})
                    response_text = f"""## 화물통관 조회 결과

**화물번호**: {cargo_data.get('cargo_number', 'N/A')}
**화물유형**: {cargo_data.get('cargo_type', 'N/A')}
**인식 신뢰도**: {cargo_data.get('confidence_score', 0.0):.2%}

{json_response.get('message', '')}

처리시간: {json_response.get('processing_time_ms', 0)}ms
"""
                else:
                    response_text = f"""## 화물통관 조회 오류

**오류 코드**: {json_response.get('error_code', 'UNKNOWN')}
**오류 메시지**: {json_response.get('error_message', '')}

{json_response.get('message', '')}
"""
            else:
                # 기타 응답
                response_text = json_response.get("message", str(json_response))

            # 텍스트를 청크 단위로 스트리밍
            chunk_size = 10  # 문자 단위
            for i in range(0, len(response_text), chunk_size):
                chunk = response_text[i : i + chunk_size]

                delta_event = {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": chunk},
                }
                yield f"event: chat_content_delta\ndata: {json.dumps(delta_event)}\n\n"

                # 스트리밍 효과를 위한 짧은 지연
                await asyncio.sleep(0.01)

            # content_block_stop 이벤트
            content_stop_event = {
                "type": "content_block_stop",
                "index": 0,
                "stop_timestamp": datetime.utcnow().isoformat() + "Z",
            }
            yield f"event: chat_content_stop\ndata: {json.dumps(content_stop_event)}\n\n"

            # message_delta 이벤트
            message_delta_event = {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            }
            yield f"event: chat_message_delta\ndata: {json.dumps(message_delta_event)}\n\n"

            # message_stop 이벤트
            yield 'event: chat_message_stop\ndata: {"type":"message_stop"}\n\n'

        except Exception as e:
            logger.error(f"JSON to streaming 변환 중 오류: {e}", exc_info=True)

            # 에러 응답
            error_delta = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "text_delta",
                    "text": "응답 처리 중 오류가 발생했습니다.",
                },
            }
            yield f"event: chat_content_delta\ndata: {json.dumps(error_delta)}\n\n"

            # 에러 종료
            yield f'event: chat_message_delta\ndata: {{"type":"message_delta","delta":{{"stop_reason":"error","stop_sequence":null}}}}\n\n'
            yield 'event: chat_message_stop\ndata: {"type":"message_stop"}\n\n'

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

        # HSCode 분류 의도 감지 및 전문 처리 (SSE 스트리밍 방식)
        intent_result = await self.intent_classification_service.classify_intent(
            chat_request.message
        )

        if intent_result.intent_type == IntentType.HSCODE_CLASSIFICATION:
            logger.info(
                f"HSCode 분류 의도 감지됨 (SSE 스트리밍 처리): 신뢰도 {intent_result.confidence_score:.3f}"
            )

            # HSCode 전문 분류 처리를 위한 특별한 LLM 모델 사용
            chat_model = llm_provider.hscode_llm_with_web_search

            # 정보 충분성 분석
            is_sufficient, product_category, requirements = (
                self.hscode_classification_service.analyze_information_sufficiency(
                    chat_request.message
                )
            )

            if not is_sufficient:
                # 정보 부족 시: 화이트리스트 검색 + 정보 요구사항 안내
                hscode_prompt = f"""
{self.hscode_classification_service.create_information_request_response(
    chat_request.message, product_category, requirements
)}

---

**🔍 초기 HSCode 검색 시도**

위의 상세 정보를 기다리는 동안, 현재 제공된 정보로 예상 HSCode 범위를 검색해보겠습니다...

**검색 대상**: {chat_request.message}
**제품 카테고리**: {product_category}

신뢰할 수 있는 관세청, WCO 등 공식 사이트에서 관련 정보를 검색하여 참고 정보를 제공해드리겠습니다.
"""
            else:
                # 정보 충분 시: 전문 HSCode 분류 수행
                hscode_prompt = f"""
당신은 20년 경력의 세계적인 HSCode 분류 전문가입니다.

**Step-Back Analysis (분류 원칙 정의):**
HSCode 분류의 근본 원칙:
1. 관세율표 해석에 관한 통칙(GRI) 1-6호를 순서대로 적용
2. 호(Heading)의 용어와 관련 부/류의 주(Note) 규정 우선
3. 본질적 특성(Essential Character) 기준으로 판단
4. 최종 확정 전 위험 요소 평가 필수

**Chain-of-Thought 분석 과정:**

### 1단계: 제품 정보 종합 분석
**사용자 요청:** "{chat_request.message}"

다음 체크리스트를 따라 단계별로 분석하세요:
- 제품명과 모델명 정확히 파악
- 주요 재료 구성과 비율 확인  
- 핵심 기능과 본질적 특성 도출
- 사용 대상과 용도 명확화

### 2단계: GRI 통칙 순차 적용
- **통칙 1**: 호의 용어와 주 규정 검토
- **통칙 2**: 미완성품/혼합물 해당 여부
- **통칙 3**: 복수 호 해당시 구체성/본질적 특성/최종호 원칙
- **통칙 4-6**: 필요시 추가 적용

### 3단계: Self-Consistency 검증
다음 3가지 관점에서 분류 결과 검증:
1. **법적 관점**: GRI 통칙 적용의 타당성
2. **기술적 관점**: 제품 특성 분석의 정확성
3. **실무적 관점**: 세관 심사 시 예상 쟁점

### 4단계: 위험 평가 및 권고사항
- 오분류 위험 요소 식별
- 대안 코드 검토
- 실무상 주의사항

**화이트리스트 기반 웹 검색도 함께 수행하여 최신 공식 정보를 참조해주세요.**

신뢰할 수 있는 관세청, WCO, 무역 관련 공식 사이트의 정보를 우선적으로 참조하여 정확한 HSCode 분류를 제공해주세요.
"""

        else:
            # 일반 채팅으로 처리 (기존 로직 유지)
            chat_model = llm_provider.news_chat_model
            hscode_prompt = None

        try:
            # 세션 및 히스토리 초기화
            if user_id:
                # 세션 관련 트랜잭션을 세이브포인트로 관리
                async with db.begin_nested() as session_savepoint:
                    try:
                        # 1. 기존 세션 조회를 위한 사전 확인
                        existing_session = None
                        from uuid import UUID
                        from sqlalchemy.future import select
                        from sqlalchemy.orm import selectinload
                        from app.models import db_models

                        try:
                            session_uuid = UUID(session_uuid_str)
                            query = (
                                select(db_models.ChatSession)
                                .where(
                                    db_models.ChatSession.session_uuid == session_uuid,
                                    db_models.ChatSession.user_id == user_id,
                                )
                                .options(selectinload(db_models.ChatSession.messages))
                            )
                            result = await db.execute(query)
                            existing_session = result.scalars().first()
                        except ValueError:
                            pass

                        # 2. 세션 생성/조회
                        session_obj = await crud.chat.get_or_create_session(
                            db=db, user_id=user_id, session_uuid_str=session_uuid_str
                        )

                        # 새 세션인지 확인 (기존 세션이 없었던 경우)
                        is_new_session = existing_session is None

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

                    # 사용자 메시지 저장을 세이브포인트로 관리 (대화 내역 조회 성공/실패와 무관하게 항상 실행)
                    async with db.begin_nested() as user_message_savepoint:
                        try:
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
            yield f"event: chat_message_start\ndata: {json.dumps(message_start_event)}\n\n"

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
                yield f"event: chat_metadata_start\ndata: {json.dumps(metadata_block_event)}\n\n"

                # 메타데이터 블록 종료
                metadata_stop_event = {
                    "type": "content_block_stop",
                    "index": content_index,
                    "stop_timestamp": datetime.utcnow().isoformat() + "Z",
                }
                yield f"event: chat_metadata_stop\ndata: {json.dumps(metadata_stop_event)}\n\n"
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
            yield f"event: chat_content_start\ndata: {json.dumps(content_block_event)}\n\n"

            # 무역 전문가 시스템 프롬프트 추가
            system_prompt = (
                "당신은 대한민국의 무역 및 수출입 전문가입니다. 다음 지침을 엄격히 준수하세요:\n\n"
                "1. **무역 관련 질문만 답변**: 무역, 수출입, 관세, 통관, 원산지, FTA, 무역규제, 품목분류, HSCode 등과 관련된 질문에만 답변합니다.\n\n"
                "2. **무역 외 질문 거부**: 무역과 관련이 없는 질문(일반상식, 개인적 조언, 오락, 요리, 여행 등)에 대해서는 다음과 같이 정중히 거부합니다:\n"
                "   '죄송하지만 저는 무역 및 수출입 전문 AI입니다. 무역, 관세, 통관, 수출입 규제 등과 관련된 질문만 답변할 수 있습니다. 무역 관련 질문이 있으시면 언제든지 문의해 주세요.'\n\n"
                "3. **HSCode 분류 우선 제공**: HSCode 분류 요청 시:\n"
                "   - **불충분한 정보라도 일단 가장 가능성 높은 HSCode를 먼저 제시**하세요\n"
                "   - **반드시 출처 URL을 함께 제공**하세요 (예: https://customs.go.kr/tariff/8517.12.00)\n"
                "   - 예시: '스마트폰'만 언급되어도 'HSCode 8517.12.00(휴대전화)' 먼저 제시\n"
                "   - 예시: '노트북'만 언급되어도 'HSCode 8471.30.00(휴대용 자동자료처리기계)' 먼저 제시\n"
                "   - 제시한 HSCode 다음에 더 정확한 분류를 위한 추가 정보를 요청하세요\n"
                "   - 제조사, 모델명, 재료, 용도, 기능, 가격대 등 세부사항을 요청하세요\n"
                "   - General Rules of Interpretation (GRI)을 적용하여 분류 근거를 설명하세요\n\n"
                "4. **관세청 문의 지양**: 다음과 같은 표현을 사용하지 마세요:\n"
                "   - '관세청에 문의하세요'\n"
                "   - '관세청 사전심사 신청'\n"
                "   - '관세청에 확인 요청'\n"
                "   대신 구체적인 HSCode와 출처를 제공한 후 추가 정보를 요청하세요.\n\n"
                "5. **전문적 답변**: 무역 관련 질문에 대해서는 정확하고 전문적인 정보를 제공하며, 최신 규정과 정책 변화를 반영합니다.\n\n"
                "6. **한국어 답변**: 모든 답변은 한국어로 제공합니다.\n\n"
                "7. **안전성**: 불법적이거나 유해한 무역 행위에 대해서는 조언하지 않습니다.\n\n"
                "8. **실용적 조언**: 구체적이고 실행 가능한 조언을 제공하며, 관련 규정이나 참고 자료 링크를 안내합니다."
            )

            # 메시지 구성
            messages = []

            # 시스템 프롬프트 추가
            messages.append(SystemMessage(content=system_prompt))

            # 이전 대화 내역 추가 (있는 경우)
            if previous_messages:
                messages.extend(previous_messages)

            # 현재 사용자 메시지 추가 (HSCode 분류인 경우 특별한 프롬프트 사용)
            if (
                intent_result.intent_type == IntentType.HSCODE_CLASSIFICATION
                and "hscode_prompt" in locals()
                and hscode_prompt is not None
            ):
                # HSCode 분류용 전문 프롬프트 사용
                messages.append(HumanMessage(content=hscode_prompt))
                logger.info("HSCode 전문 분류 프롬프트 적용됨")
            else:
                # 일반 채팅 메시지 사용
                messages.append(HumanMessage(content=chat_request.message))

            # 병렬 처리: AI 응답 스트리밍과 동시에 상세페이지 정보 준비
            detail_page_generator = None
            try:
                # 병렬 처리 시작
                detail_page_generator = (
                    self.parallel_task_manager.execute_parallel_tasks(
                        chat_request, db, background_tasks
                    )
                )

                # 병렬 처리 이벤트를 먼저 1개 보내고
                try:
                    first_parallel_event = await detail_page_generator.__anext__()
                    yield first_parallel_event
                except StopAsyncIteration:
                    pass

            except Exception as parallel_error:
                logger.warning(f"병렬 처리 초기화 실패: {parallel_error}")

            # 직접 ChatAnthropic 모델로 스트리밍 - 한 글자씩 스트리밍됨
            ai_response = ""

            try:
                # langchain의 astream 메서드를 사용하여 토큰별 스트리밍
                from app.utils.llm_response_parser import extract_text_from_stream_chunk

                async for chunk in chat_model.astream(messages):
                    # 타입 안전 텍스트 추출
                    chunk_text = extract_text_from_stream_chunk(chunk)

                    if chunk_text:
                        ai_response += chunk_text

                        # content_block_delta 이벤트로 텍스트 전송
                        delta_event = {
                            "type": "content_block_delta",
                            "index": content_index,
                            "delta": {"type": "text_delta", "text": chunk_text},
                        }
                        yield f"event: chat_content_delta\ndata: {json.dumps(delta_event)}\n\n"

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
                yield f"event: chat_content_delta\ndata: {json.dumps(error_delta_event)}\n\n"
                ai_response = error_text

            # content block 종료
            content_stop_event = {
                "type": "content_block_stop",
                "index": content_index,
                "stop_timestamp": datetime.utcnow().isoformat() + "Z",
            }
            yield f"event: chat_content_stop\ndata: {json.dumps(content_stop_event)}\n\n"

            # 병렬 처리 나머지 이벤트 전송
            if detail_page_generator:
                try:
                    async for parallel_event in detail_page_generator:
                        yield parallel_event
                except Exception as parallel_error:
                    logger.warning(f"병렬 처리 이벤트 전송 중 오류: {parallel_error}")

            # 2. AI 응답 메시지 저장 (회원인 경우)
            if user_id and history and ai_response:
                async with db.begin_nested() as ai_message_savepoint:
                    try:
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
            yield f"event: chat_message_delta\ndata: {json.dumps(message_delta_event)}\n\n"

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
            yield f"event: chat_message_limit\ndata: {json.dumps(message_limit_event)}\n\n"

            # message_stop 이벤트
            yield 'event: chat_message_stop\ndata: {"type":"message_stop"}\n\n'

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
            yield f"event: chat_content_delta\ndata: {json.dumps(error_delta)}\n\n"

            # content block 종료
            error_stop = {
                "type": "content_block_stop",
                "index": 0,
                "stop_timestamp": datetime.utcnow().isoformat() + "Z",
            }
            yield f"event: chat_content_stop\ndata: {json.dumps(error_stop)}\n\n"

            # message 종료
            yield f'event: chat_message_delta\ndata: {{"type":"message_delta","delta":{{"stop_reason":"error","stop_sequence":null}}}}\n\n'
            yield 'event: chat_message_stop\ndata: {"type":"message_stop"}\n\n'
