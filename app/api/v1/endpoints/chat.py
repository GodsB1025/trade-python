from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import json
import logging
from typing import AsyncGenerator

from app.api.v1.dependencies import get_chat_service, get_db
from app.models.chat_models import ChatRequest
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", summary="AI Chat Endpoint with Streaming")
async def handle_chat(
    request: Request,
    chat_request: ChatRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    chat_service: ChatService = Depends(get_chat_service),
):
    """
    사용자의 채팅 메시지를 받아 AI와 대화하고, 응답을 실시간으로 스트리밍함.

    - **요청 본문:** `ChatRequest` 모델 참조
        - `user_id`: 회원 식별자 (없으면 비회원)
        - `session_uuid`: 기존 대화의 UUID
        - `message`: 사용자 메시지
    - **응답:**
        - `StreamingResponse`: `text/event-stream` 형식의 SSE 스트림.
        - 각 이벤트는 JSON 형식이며, `type`과 `data` 필드를 포함함.
          - `type: 'session_id'`: 새 채팅 세션이 시작될 때 반환되는 세션 UUID
          - `type: 'token'`: AI가 생성하는 응답 토큰
          - `type: 'finish'`: 스트림 종료
          - `type: 'error'`: 오류 발생
    """

    async def generate_sse_stream() -> AsyncGenerator[str, None]:
        """
        SSE 형식의 스트림을 생성하는 비동기 제너레이터.
        클라이언트 연결 해제를 감지하고 적절한 에러 처리를 수행함.
        """
        try:
            # 클라이언트 연결 상태 확인
            if await request.is_disconnected():
                logger.info("클라이언트가 연결을 해제했습니다.")
                return

            # 채팅 서비스 스트림 생성
            async for chunk in chat_service.stream_chat_response(
                chat_request=chat_request, db=db, background_tasks=background_tasks
            ):
                # 연결 상태 재확인
                if await request.is_disconnected():
                    logger.info("스트리밍 중 클라이언트가 연결을 해제했습니다.")
                    break

                # SSE 형식으로 청크 전송
                yield chunk

                # 백프레셔 방지를 위한 짧은 대기
                await asyncio.sleep(0.001)

        except asyncio.CancelledError:
            logger.info("스트리밍이 취소되었습니다.")
        except Exception as e:
            logger.error(f"스트리밍 중 예외 발생: {e}", exc_info=True)
            # 에러 이벤트 전송
            error_event = {
                "type": "error",
                "data": {
                    "message": "스트리밍 중 서버 오류가 발생했습니다.",
                    "error_code": "STREAMING_ERROR",
                },
            }
            yield f"data: {json.dumps(error_event)}\n\n"
        finally:
            # 연결 종료 이벤트 전송
            finish_event = {"type": "finish", "data": {"message": "Stream finished."}}
            yield f"data: {json.dumps(finish_event)}\n\n"

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
