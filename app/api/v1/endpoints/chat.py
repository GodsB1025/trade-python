from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.v1.dependencies import get_chat_service, get_db
from app.models.chat_models import ChatRequest
from app.services.chat_service import ChatService

router = APIRouter()


@router.post("/", summary="AI Chat Endpoint with Streaming")
async def handle_chat(
    request: Request,
    chat_request: ChatRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    사용자의 채팅 메시지를 받아 AI와 대화하고, 응답을 실시간으로 스트리밍합니다.

    - **요청 본문:** `ChatRequest` 모델 참조
        - `user_id`: 회원 식별자 (없으면 비회원)
        - `session_uuid`: 기존 대화의 UUID
        - `message`: 사용자 메시지
    - **응답:**
        - `StreamingResponse`: `text/event-stream` 형식의 SSE 스트림.
        - 각 이벤트는 JSON 형식이며, `type`과 `data` 필드를 포함합니다.
          - `type: 'session_id'`: 새 채팅 세션이 시작될 때 반환되는 세션 UUID
          - `type: 'token'`: AI가 생성하는 응답 토큰
          - `type: 'finish'`: 스트림 종료
          - `type: 'error'`: 오류 발생
    """
    generator = chat_service.stream_chat_response(
        chat_request=chat_request,
        db=db,
        background_tasks=background_tasks
    )

    return StreamingResponse(generator, media_type="text/event-stream")
