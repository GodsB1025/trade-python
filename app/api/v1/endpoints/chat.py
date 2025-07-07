"""
채팅 API 엔드포인트
"""

from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse  # JSONResponse 추가
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import json
import logging
from typing import AsyncGenerator, Union  # Union 추가

from app.api.v1.dependencies import get_chat_service, get_db
from app.models.chat_models import ChatRequest
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "", summary="AI Chat Endpoint with HSCode Search and Streaming", response_model=None
)
async def handle_chat(
    request: Request,
    chat_request: ChatRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    chat_service: ChatService = Depends(get_chat_service),
) -> Union[StreamingResponse, JSONResponse]:
    """
    사용자의 채팅 메시지를 받아 AI와 대화하고, 응답을 실시간으로 스트리밍함.
    HSCode 관련 쿼리는 별도 처리함.

    - **요청 본문:** `ChatRequest` 모델 참조
        - `user_id`: 회원 식별자 (없으면 비회원)
        - `session_uuid`: 기존 대화의 UUID
        - `message`: 사용자 메시지
    - **응답:**
        - `StreamingResponse`: `text/event-stream` 형식의 SSE 스트림.
        - 초기 응답에 session_uuid 포함
        - 표준화된 SSE 이벤트:
          - `event: chat_session_info`: 세션 정보 (session_uuid 포함)
          - `event: chat_message_start`: 메시지 시작
          - `event: chat_metadata_start/stop`: 메타데이터 블록 시작/종료
          - `event: chat_content_start`: 컨텐츠 블록 시작
          - `event: chat_content_delta`: 스트리밍 텍스트 청크
          - `event: chat_content_stop`: 컨텐츠 블록 종료
          - `event: parallel_processing`: 병렬 처리 정보
          - `event: detail_buttons_*`: 상세페이지 버튼 이벤트
          - `event: chat_message_delta`: 메시지 메타데이터 (stop_reason 등)
          - `event: chat_message_limit`: 메시지 제한 정보
          - `event: chat_message_stop`: 메시지 종료
    """

    # 성공적인 요청 로깅
    logger.info(f"=== 채팅 요청 성공 ===")
    logger.info(f"사용자 ID: {chat_request.user_id}")
    logger.info(f"세션 UUID: {chat_request.session_uuid}")
    logger.info(f"메시지 길이: {len(chat_request.message)}")
    logger.info(f"메시지 내용: {chat_request.message[:100]}...")  # 처음 100자만 로깅
    logger.info(f"====================")

    # === 통합 의도 분류 및 특수 처리 ===
    special_response = await chat_service.check_unified_intent(chat_request)
    if special_response:
        logger.info(
            f"특수 의도 감지됨: {special_response.get('type', 'unknown')}. JSON 응답을 반환합니다."
        )
        return JSONResponse(
            content=special_response,
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
            },
        )

    # === 일반 채팅 SSE 스트리밍 처리 ===
    async def generate_sse_stream() -> AsyncGenerator[str, None]:
        """
        SSE 형식의 스트림을 생성하는 비동기 제너레이터.
        클라이언트 연결 해제를 감지하고 적절한 에러 처리를 수행함.
        """
        accumulated_response = ""  # 응답 내용 누적용
        response_started = False

        try:
            # 클라이언트 연결 상태 확인
            if await request.is_disconnected():
                logger.info("클라이언트가 연결을 해제했습니다.")
                return

            # 초기 이벤트: session_uuid 전송
            session_info = {
                "session_uuid": chat_request.session_uuid,
                "timestamp": asyncio.get_event_loop().time(),
            }
            session_info_json = json.dumps(session_info, ensure_ascii=False)
            yield f"event: chat_session_info\ndata: {session_info_json}\n\n"

            # 백프레셔 방지를 위한 짧은 대기
            await asyncio.sleep(0.1)

            # 연결 상태 재확인
            if await request.is_disconnected():
                logger.info("세션 정보 전송 후 클라이언트가 연결을 해제했습니다.")
                return

            # ChatService의 스트림을 그대로 전달 (HSCode 쿼리도 내부에서 처리)
            async for chunk in chat_service.stream_chat_response(
                chat_request=chat_request, db=db, background_tasks=background_tasks
            ):
                # 연결 상태 재확인
                if await request.is_disconnected():
                    logger.info("스트리밍 중 클라이언트가 연결을 해제했습니다.")
                    break

                # 응답 시작 로깅 (최초 1회만)
                if not response_started:
                    logger.info(f"=== AI 응답 시작 ===")
                    logger.info(f"사용자 ID: {chat_request.user_id}")
                    logger.info(f"세션 UUID: {chat_request.session_uuid}")
                    response_started = True

                # 실제 응답 내용 추출 및 누적
                try:
                    # 모든 청크에 대한 디버깅 로깅 추가
                    logger.info(f"처리 중인 청크: {chunk[:200]}...")

                    # SSE 형식에서 data 부분 추출
                    if chunk.startswith("event: chat_content_delta\ndata: "):
                        data_part = chunk.split("data: ", 1)[1].split("\n\n")[0]
                        logger.info(f"추출된 data 부분: {data_part}")

                        delta_data = json.loads(data_part)

                        # 디버깅을 위한 delta_data 구조 로깅
                        logger.info(f"delta_data 구조: {delta_data}")

                        # delta에서 실제 텍스트 추출 (Context7 권장 방식)
                        if "delta" in delta_data and "text" in delta_data["delta"]:
                            text_content = delta_data["delta"]["text"]
                            accumulated_response += text_content
                            logger.info(f"텍스트 추출 성공 (방법1): '{text_content}'")
                        # LangChain astream_events v2 형식도 지원
                        elif (
                            "type" in delta_data
                            and delta_data["type"] == "content_block_delta"
                        ):
                            delta_info = delta_data.get("delta", {})
                            logger.info(f"v2 형식 감지, delta_info: {delta_info}")
                            if (
                                "type" in delta_info
                                and delta_info["type"] == "text_delta"
                            ):
                                text_content = delta_info.get("text", "")
                                accumulated_response += text_content
                                logger.info(
                                    f"텍스트 추출 성공 (방법2): '{text_content}'"
                                )
                        else:
                            logger.warning(f"알 수 없는 delta_data 형식: {delta_data}")

                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                    # JSON 파싱 실패하거나 예상된 구조가 아닌 경우는 디버깅을 위해 로깅
                    logger.info(
                        f"텍스트 추출 실패 - chunk: {chunk[:200]}..., error: {e}"
                    )
                    pass

                # SSE 형식으로 청크 전송
                yield chunk

                # 백프레셔 방지를 위한 짧은 대기
                await asyncio.sleep(0.001)

            # 응답 완료 로깅
            if response_started:
                logger.info(f"=== AI 응답 완료 ===")
                logger.info(f"사용자 ID: {chat_request.user_id}")
                logger.info(f"세션 UUID: {chat_request.session_uuid}")
                logger.info(f"응답 길이: {len(accumulated_response)}")
                if accumulated_response:
                    logger.info(
                        f"응답 내용: {accumulated_response[:500]}..."
                    )  # 처음 500자만 로깅
                else:
                    logger.warning(
                        "accumulated_response가 비어있음 - 텍스트 추출 로직 점검 필요"
                    )
                logger.info(f"====================")

        except asyncio.CancelledError:
            logger.info("스트리밍이 취소되었습니다.")
            if response_started and accumulated_response:
                logger.info(f"취소된 응답 내용 (일부): {accumulated_response[:200]}...")
        except Exception as e:
            logger.error(f"스트리밍 중 예외 발생: {e}", exc_info=True)
            if response_started and accumulated_response:
                logger.info(
                    f"예외 발생 전 응답 내용 (일부): {accumulated_response[:200]}..."
                )

    # SSE 스트리밍 응답 생성
    response = StreamingResponse(
        generate_sse_stream(),
        media_type="text/event-stream",
        headers={
            # SSE 표준 헤더 설정
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
            "Access-Control-Expose-Headers": "Content-Type",
            # 청크 전송 최적화
            "Transfer-Encoding": "chunked",
            "X-Accel-Buffering": "no",  # nginx 버퍼링 비활성화
        },
    )

    return response
