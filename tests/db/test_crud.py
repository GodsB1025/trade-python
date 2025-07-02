"""
CRUD 함수에 대한 Mock 기반 단위 테스트
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4, UUID
from datetime import datetime, timedelta

from app.db import crud
from app.models import schemas, db_models

pytestmark = pytest.mark.asyncio


async def test_create_and_get_news(mock_db_session):
    """
    뉴스 생성 로직이 올바르게 동작하는지 테스트 (Mock 기반).
    """
    # Given: 테스트 데이터 준비
    news_item_create = schemas.NewsItem(
        title="Test News",
        summary="This is a test summary.",
        url="http://example.com/news",
        published_at="2024-07-31"
    )

    # When: CRUD 함수 실행
    result = await crud.create_news_items(mock_db_session, [news_item_create])

    # Then: 결과 검증
    assert len(result) == 1
    assert isinstance(result[0], db_models.News)
    assert result[0].title == "Test News"
    assert result[0].summary == "This is a test summary."
    assert result[0].url == "http://example.com/news"

    # DB 메서드 호출 검증
    mock_db_session.add_all.assert_called_once()
    mock_db_session.flush.assert_called_once()


async def test_get_or_create_chat_session_creation(mock_db_session):
    """
    session_id 없이 호출 시 새로운 채팅 세션이 생성되는지 테스트 (Mock 기반).
    """
    # Given: 테스트 데이터 준비
    user_id = 1

    # When: CRUD 함수 실행 (session_id 없음)
    result = await crud.get_or_create_chat_session(mock_db_session, user_id=user_id)

    # Then: 결과 검증
    assert isinstance(result, db_models.ChatSession)
    assert result.user_id == user_id

    # DB 메서드 호출 검증
    mock_db_session.add.assert_called_once()
    mock_db_session.flush.assert_called_once()
    mock_db_session.refresh.assert_called_once()


async def test_get_or_create_chat_session_retrieval(mock_db_session):
    """
    session_id로 조회 시 기존 세션을 가져오는지 테스트 (Mock 기반).
    """
    # Given: 테스트 데이터 준비
    user_id = 1
    session_uuid = uuid4()

    # Mock 쿼리 결과 설정
    existing_session = db_models.ChatSession(
        session_uuid=session_uuid,
        user_id=user_id,
        created_at=datetime.now()
    )

    # Mock 쿼리 결과 준비
    mock_result = Mock()
    mock_scalars = Mock()
    mock_scalars.first.return_value = existing_session
    mock_result.scalars.return_value = mock_scalars
    mock_db_session.execute.return_value = mock_result

    # When: CRUD 함수 실행 (session_id 있음)
    result = await crud.get_or_create_chat_session(
        mock_db_session, user_id=user_id, session_id=session_uuid
    )

    # Then: 결과 검증
    assert result == existing_session
    assert result.session_uuid == session_uuid
    assert result.user_id == user_id

    # DB 메서드 호출 검증
    mock_db_session.execute.assert_called_once()
    # 기존 세션이 있으므로 add, flush, refresh는 호출되지 않아야 함
    mock_db_session.add.assert_not_called()
    mock_db_session.flush.assert_not_called()
    mock_db_session.refresh.assert_not_called()


async def test_get_or_create_chat_session_no_existing_session(mock_db_session):
    """
    session_id로 조회했지만 기존 세션이 없을 때 새로 생성하는지 테스트 (Mock 기반).
    """
    # Given: 테스트 데이터 준비
    user_id = 1
    session_uuid = uuid4()

    # Mock 쿼리 결과 설정 (기존 세션 없음)
    mock_result = Mock()
    mock_scalars = Mock()
    mock_scalars.first.return_value = None  # 기존 세션 없음
    mock_result.scalars.return_value = mock_scalars
    mock_db_session.execute.return_value = mock_result

    # When: CRUD 함수 실행
    result = await crud.get_or_create_chat_session(
        mock_db_session, user_id=user_id, session_id=session_uuid
    )

    # Then: 결과 검증
    assert isinstance(result, db_models.ChatSession)
    assert result.user_id == user_id

    # DB 메서드 호출 검증
    mock_db_session.execute.assert_called_once()  # 조회 시도
    mock_db_session.add.assert_called_once()      # 새 세션 추가
    mock_db_session.flush.assert_called_once()    # flush 호출
    mock_db_session.refresh.assert_called_once()  # refresh 호출


async def test_create_chat_message(mock_db_session):
    """
    채팅 메시지 생성이 올바르게 동작하는지 테스트 (Mock 기반).
    """
    # Given: 테스트 데이터 준비
    session_uuid = uuid4()
    session_created_at = datetime.now()

    message_create = schemas.ChatMessageCreate(
        session_uuid=session_uuid,
        session_created_at=session_created_at,
        message_type="USER",
        content="Hello, mock world!"
    )

    # When: CRUD 함수 실행
    result = await crud.create_chat_message(mock_db_session, message_create)

    # Then: 결과 검증
    assert isinstance(result, db_models.ChatMessage)
    assert result.session_uuid == session_uuid
    assert result.session_created_at == session_created_at
    assert result.message_type == "USER"
    assert result.content == "Hello, mock world!"

    # DB 메서드 호출 검증
    mock_db_session.add.assert_called_once()
    mock_db_session.flush.assert_called_once()
    mock_db_session.refresh.assert_called_once()


async def test_get_chat_messages(mock_db_session):
    """
    채팅 메시지 조회가 올바르게 동작하는지 테스트 (Mock 기반).
    """
    # Given: 테스트 데이터 준비
    session_uuid = uuid4()
    session_created_at = datetime.now()

    # Mock 쿼리 결과 설정
    mock_messages = [
        db_models.ChatMessage(
            message_id=1,
            session_uuid=session_uuid,
            session_created_at=session_created_at,
            message_type="USER",
            content="Hello!"
        ),
        db_models.ChatMessage(
            message_id=2,
            session_uuid=session_uuid,
            session_created_at=session_created_at,
            message_type="AI",
            content="Hi there!"
        )
    ]

    mock_result = Mock()
    mock_scalars = Mock()
    mock_scalars.all.return_value = mock_messages
    mock_result.scalars.return_value = mock_scalars
    mock_db_session.execute.return_value = mock_result

    # When: CRUD 함수 실행
    result = await crud.get_chat_messages(
        mock_db_session, session_uuid, session_created_at
    )

    # Then: 결과 검증
    assert len(result) == 2
    assert result[0].content == "Hello!"
    assert result[1].content == "Hi there!"
    assert all(msg.session_uuid == session_uuid for msg in result)

    # DB 메서드 호출 검증
    mock_db_session.execute.assert_called_once()


async def test_get_active_bookmarks(mock_db_session):
    """
    활성화된 북마크 조회가 올바르게 동작하는지 테스트 (Mock 기반).
    """
    # Given: 테스트 데이터 준비
    mock_bookmarks = [
        db_models.Bookmark(
            id=1,
            user_id="user1",
            target_type="HS_CODE",
            target_value="123456",
            is_active=True
        ),
        db_models.Bookmark(
            id=2,
            user_id="user2",
            target_type="CARGO",
            target_value="CARGO123",
            is_active=True
        )
    ]

    mock_result = Mock()
    mock_scalars = Mock()
    mock_scalars.all.return_value = mock_bookmarks
    mock_result.scalars.return_value = mock_scalars
    mock_db_session.execute.return_value = mock_result

    # When: CRUD 함수 실행
    result = await crud.get_active_bookmarks(mock_db_session)

    # Then: 결과 검증
    assert len(result) == 2
    assert all(bookmark.is_active for bookmark in result)
    assert result[0].target_type == "HS_CODE"
    assert result[1].target_type == "CARGO"

    # DB 메서드 호출 검증
    mock_db_session.execute.assert_called_once()
