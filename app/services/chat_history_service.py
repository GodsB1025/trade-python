from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Any, Optional
import asyncio

from app.db import crud
from app.models import schemas, db_models
from app.core.config import settings

# TODO: 이 클래스는 app/db/crud.py에 구현될 함수에 의존하게 됩니다.
# 현재는 뼈대만 구성합니다.


def _db_message_to_base_message(db_message: db_models.ChatMessage) -> BaseMessage:
    """DB 모델을 LangChain 메시지 모델로 변환"""
    if db_message.message_type == "USER":
        return HumanMessage(content=db_message.content)
    elif db_message.message_type == "AI":
        return AIMessage(content=db_message.content)
    elif db_message.message_type == "SYSTEM":
        return SystemMessage(content=db_message.content)
    else:
        raise ValueError(f"Unknown message type: {db_message.message_type}")


class DatabaseChatMessageHistory(BaseChatMessageHistory):
    """
    데이터베이스와 상호작용하여 채팅 기록을 관리하는 클래스.
    LangChain의 BaseChatMessageHistory를 상속받아, 프로젝트의 DB 스키마에 맞게 커스터마이징함.
    """

    def __init__(self, session_id: str, user_id: int, db: AsyncSession):
        self.session_id = session_id
        self.user_id = user_id
        self.db = db
        self._session: Optional[db_models.ChatSession] = None
        # 비동기 코드를 동기 메서드에서 실행하기 위한 이벤트 루프
        self._loop = asyncio.get_event_loop()

    async def _get_session(self) -> db_models.ChatSession:
        if self._session is None:
            try:
                session_uuid = UUID(self.session_id)
            except ValueError:
                session_uuid = None

            self._session = await crud.get_or_create_chat_session(
                db=self.db, user_id=self.user_id, session_id=session_uuid
            )
        return self._session

    @property
    def messages(self) -> list[BaseMessage]:
        """세션에 해당하는 모든 메시지를 DB에서 동기적으로 조회"""
        return self._loop.run_until_complete(self.aget_messages())

    async def aget_messages(self) -> list[BaseMessage]:
        """세션에 해당하는 모든 메시지를 DB에서 비동기적으로 조회"""
        session = await self._get_session()
        db_messages = await crud.get_chat_messages(
            self.db, session.session_uuid, session.created_at
        )
        return [_db_message_to_base_message(msg) for msg in db_messages]

    def add_messages(self, messages: list[BaseMessage]) -> None:
        """메시지 목록을 DB에 동기적으로 추가"""
        self._loop.run_until_complete(self.aadd_messages(messages))

    async def aadd_messages(self, messages: list[BaseMessage]) -> None:
        """메시지 목록을 DB에 비동기적으로 추가"""
        session = await self._get_session()
        for message in messages:
            message_create = schemas.ChatMessageCreate(
                session_uuid=session.session_uuid,
                session_created_at=session.created_at,
                message_type=message.type.upper(),
                content=message.content,
            )
            await crud.create_chat_message(self.db, message_create)

    async def clear(self) -> None:
        """세션의 모든 메시지를 DB에서 비동기적으로 삭제"""
        session = await self._get_session()
        await crud.delete_chat_messages(self.db, session.session_uuid, session.created_at)


class ChatHistoryService:
    """
    채팅 기록 관련 비즈니스 로직을 처리하는 서비스 클래스.
    get_chat_history 메서드는 LangChain의 RunnableWithMessageHistory에 의해 호출될 팩토리 함수 역할을 함.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    def get_chat_history(
        self, session_id: str, **kwargs: Any
    ) -> DatabaseChatMessageHistory:
        """
        주어진 세션 ID에 대한 채팅 기록 객체를 반환. (동기 함수)
        kwargs를 통해 LangChain의 RunnableConfig를 받아 user_id를 추출.
        """
        config = kwargs.get("config", {})
        configurable = config.get("configurable", {})
        request_user_id = configurable.get("user_id")

        final_user_id: int
        if request_user_id is None:
            final_user_id = settings.GUEST_USER_ID
        else:
            try:
                final_user_id = int(request_user_id)
            except (ValueError, TypeError):
                raise ValueError(
                    f"Invalid user_id format: {request_user_id}. Must be an integer.")

        return DatabaseChatMessageHistory(
            session_id=session_id, user_id=final_user_id, db=self.db
        )
