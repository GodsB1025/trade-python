from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.api.v1.dependencies import get_chat_service
from app.models.schemas import ChatRequest
from app.services.chat_service import ChatService

router = APIRouter()


@router.post("", summary="실시간 스트리밍 채팅")
async def stream_chat(
    chat_request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service),
):
    """
    ## 실시간 AI 채팅 (SSE 스트리밍)

    사용자의 질문에 대해 LangChain RAG 파이프라인을 통해 답변을 생성하고,
    Server-Sent Events (SSE) 형식으로 실시간 스트리밍합니다.

    - **question**: 사용자의 자연어 질문 (필수)
    - **userId**: 회원 ID (선택 사항). 제공되지 않으면 비회원으로 간주하여 임시 세션으로 처리됩니다.
    - **sessionId**: 세션 ID (선택 사항). 제공하여 이전 대화 내용을 이어갈 수 있습니다.

    `sse-starlette`의 `EventSourceResponse`를 사용하여 안정적인 스트림을 제공합니다.
    """
    event_generator = chat_service.stream_chat_response(chat_request)

    return EventSourceResponse(event_generator)
