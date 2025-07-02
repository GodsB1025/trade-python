"""
채팅 히스토리 서비스 테스트
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from pytest_mock import MockerFixture
from uuid import uuid4
from datetime import datetime

from app.services.chat_history_service import DatabaseChatMessageHistory, _db_message_to_base_message
from app.models.db_models import ChatSession, ChatMessage
from app.models.schemas import ChatMessageCreate
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


class TestChatHistoryService:
    """채팅 히스토리 서비스 테스트 클래스"""

    @pytest.fixture
    def mock_db_session(self) -> AsyncMock:
        """Mock 데이터베이스 세션 생성"""
        return AsyncMock(spec=AsyncSession)

    @pytest.fixture
    def mock_chat_session(self) -> ChatSession:
        """Mock 채팅 세션 생성"""
        session = ChatSession()
        session.session_uuid = uuid4()
        session.created_at = datetime.now()
        session.user_id = 1
        session.session_title = "Test Session"
        return session

    @pytest.fixture
    def mock_chat_messages(self, mock_chat_session: ChatSession) -> list[ChatMessage]:
        """Mock 채팅 메시지 리스트 생성"""
        messages = []

        # USER 메시지
        user_msg = ChatMessage()
        user_msg.message_id = 1
        user_msg.session_uuid = mock_chat_session.session_uuid
        user_msg.session_created_at = mock_chat_session.created_at
        user_msg.message_type = "USER"
        user_msg.content = "안녕하세요"
        messages.append(user_msg)

        # AI 메시지
        ai_msg = ChatMessage()
        ai_msg.message_id = 2
        ai_msg.session_uuid = mock_chat_session.session_uuid
        ai_msg.session_created_at = mock_chat_session.created_at
        ai_msg.message_type = "AI"
        ai_msg.content = "안녕하세요! 무엇을 도와드릴까요?"
        messages.append(ai_msg)

        return messages

    def test_db_message_to_base_message_user(self):
        """DB 메시지를 LangChain USER 메시지로 변환 테스트"""
        # Given: USER 타입 DB 메시지
        db_message = ChatMessage()
        db_message.message_type = "USER"
        db_message.content = "안녕하세요"

        # When: 변환 실행
        result = _db_message_to_base_message(db_message)

        # Then: HumanMessage로 변환됨
        assert isinstance(result, HumanMessage)
        assert result.content == "안녕하세요"

    def test_db_message_to_base_message_ai(self):
        """DB 메시지를 LangChain AI 메시지로 변환 테스트"""
        # Given: AI 타입 DB 메시지
        db_message = ChatMessage()
        db_message.message_type = "AI"
        db_message.content = "도움을 드릴게요"

        # When: 변환 실행
        result = _db_message_to_base_message(db_message)

        # Then: AIMessage로 변환됨
        assert isinstance(result, AIMessage)
        assert result.content == "도움을 드릴게요"

    def test_db_message_to_base_message_system(self):
        """DB 메시지를 LangChain SYSTEM 메시지로 변환 테스트"""
        # Given: SYSTEM 타입 DB 메시지
        db_message = ChatMessage()
        db_message.message_type = "SYSTEM"
        db_message.content = "시스템 메시지입니다"

        # When: 변환 실행
        result = _db_message_to_base_message(db_message)

        # Then: SystemMessage로 변환됨
        assert isinstance(result, SystemMessage)
        assert result.content == "시스템 메시지입니다"

    def test_db_message_to_base_message_unknown_type(self):
        """알 수 없는 메시지 타입 에러 처리 테스트"""
        # Given: 알 수 없는 타입 DB 메시지
        db_message = ChatMessage()
        db_message.message_type = "UNKNOWN"
        db_message.content = "알 수 없는 메시지"

        # When & Then: ValueError 발생
        with pytest.raises(ValueError) as exc_info:
            _db_message_to_base_message(db_message)
        assert "Unknown message type: UNKNOWN" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_messages_property(
        self,
        mock_db_session: AsyncMock,
        mock_chat_session: ChatSession,
        mock_chat_messages: list[ChatMessage],
        mocker: MockerFixture
    ):
        """메시지 조회 프로퍼티 테스트"""
        # Given: Mock CRUD 함수 설정
        mocker.patch('app.services.chat_history_service.crud.get_chat_messages',
                     return_value=mock_chat_messages)

        # DatabaseChatMessageHistory 인스턴스 생성
        history = DatabaseChatMessageHistory(
            mock_chat_session, mock_db_session)

        # When: messages 프로퍼티 호출
        messages = await history.messages

        # Then: 결과 검증
        assert len(messages) == 2
        assert isinstance(messages[0], HumanMessage)
        assert messages[0].content == "안녕하세요"
        assert isinstance(messages[1], AIMessage)
        assert messages[1].content == "안녕하세요! 무엇을 도와드릴까요?"

    @pytest.mark.asyncio
    async def test_add_messages(
        self,
        mock_db_session: AsyncMock,
        mock_chat_session: ChatSession,
        mocker: MockerFixture
    ):
        """메시지 추가 테스트"""
        # Given: Mock CRUD 함수 설정
        mock_create_message = mocker.patch(
            'app.services.chat_history_service.crud.create_chat_message')

        # DatabaseChatMessageHistory 인스턴스 생성
        history = DatabaseChatMessageHistory(
            mock_chat_session, mock_db_session)

        # 추가할 메시지들
        messages_to_add = [
            HumanMessage(content="새로운 질문입니다"),
            AIMessage(content="새로운 답변입니다")
        ]

        # When: 메시지 추가 실행
        await history.add_messages(messages_to_add)

        # Then: CRUD 함수 호출 검증
        assert mock_create_message.call_count == 2

        # 첫 번째 호출 인자 검증
        first_call_args = mock_create_message.call_args_list[0]
        assert first_call_args[0][0] == mock_db_session  # db 세션
        message_create = first_call_args[0][1]  # ChatMessageCreate 객체
        assert message_create.session_uuid == mock_chat_session.session_uuid
        assert message_create.message_type == "HUMAN"
        assert message_create.content == "새로운 질문입니다"

    @pytest.mark.asyncio
    async def test_clear_method(
        self,
        mock_db_session: AsyncMock,
        mock_chat_session: ChatSession
    ):
        """메시지 삭제 테스트 (현재는 구현되지 않음)"""
        # Given: DatabaseChatMessageHistory 인스턴스 생성
        history = DatabaseChatMessageHistory(
            mock_chat_session, mock_db_session)

        # When: clear 메서드 호출
        await history.clear()

        # Then: 현재는 pass이므로 에러 없이 실행됨
        # (향후 구현 시 실제 삭제 로직 테스트 필요)

    def test_initialization(
        self,
        mock_db_session: AsyncMock,
        mock_chat_session: ChatSession
    ):
        """DatabaseChatMessageHistory 초기화 테스트"""
        # When: 인스턴스 생성
        history = DatabaseChatMessageHistory(
            mock_chat_session, mock_db_session)

        # Then: 속성 확인
        assert history.session == mock_chat_session
        assert history.db == mock_db_session
