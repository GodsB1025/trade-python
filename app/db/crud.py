"""
데이터베이스 CRUD(Create, Read, Update, Delete) 함수
"""
from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime
from sqlalchemy import desc

# SQLAlchemy 모델과 Pydantic 스키마를 임포트합니다.
# 참고: 실제 프로젝트에서는 models.py 또는 유사한 파일에 SQLAlchemy 모델이 정의되어 있어야 합니다.
# 여기서는 해당 모델이 존재한다고 가정합니다.
from ..models import db_models
from ..models import schemas


async def create_news_items(db: AsyncSession, news_items: List[schemas.NewsCreate]) -> List[db_models.News]:
    """
    여러 개의 새로운 뉴스 항목을 데이터베이스에 비동기적으로 생성.
    `구현계획.md` v6.3 및 SQLAlchemy 2.0 비동기 모범 사례에 맞게 수정됨.
    """
    db_news_list = [
        db_models.News(
            title=item.title,
            source_url=str(item.source_url),
            source_name=item.source_name,
            published_at=item.published_at,
        )
        for item in news_items
    ]
    db.add_all(db_news_list)
    await db.flush()
    # flush는 DB에 변경사항을 보내고 PK 같은 정보를 동기화하지만, commit은 하지 않음.
    # 트랜잭션 제어는 상위 서비스 계층에서 담당.
    return db_news_list


async def get_active_bookmarks(db: AsyncSession) -> List[db_models.Bookmark]:
    """
    알림이 활성화된 모든 북마크를 데이터베이스에서 비동기적으로 조회.
    'monitoring_active' Computed 필드를 사용하도록 수정됨.
    """
    query = select(db_models.Bookmark).where(
        db_models.Bookmark.monitoring_active == True)
    result = await db.execute(query)
    return result.scalars().all()


async def create_update_feed(db: AsyncSession, feed_data: schemas.UpdateFeedCreate) -> db_models.UpdateFeed:
    """
    새로운 업데이트 피드를 데이터베이스에 비동기적으로 생성.
    `구현계획.md` v6.3 및 SQLAlchemy 2.0 비동기 모범 사례에 맞게 수정됨.
    """
    db_feed = db_models.UpdateFeed(
        user_id=feed_data.user_id,  # 스키마에 user_id를 포함하는 것이 더 일관성 있음
        feed_type=feed_data.feed_type,
        target_type=feed_data.target_type,
        target_value=feed_data.target_value,
        title=feed_data.title,
        content=feed_data.content,
        source_url=str(feed_data.source_url) if feed_data.source_url else None,
        importance=feed_data.importance
    )
    db.add(db_feed)
    await db.flush()
    await db.refresh(db_feed)  # 서버에서 생성된 created_at 같은 필드까지 모두 로드
    return db_feed


async def get_or_create_chat_session(
    db: AsyncSession, user_id: int, session_id: Optional[UUID] = None
) -> db_models.ChatSession:
    """
    주어진 session_id로 가장 최신 채팅 세션을 찾거나, 없으면 새로 생성.
    """
    if session_id:
        query = (
            select(db_models.ChatSession)
            .where(
                db_models.ChatSession.session_uuid == session_id,
                db_models.ChatSession.user_id == user_id,
            )
            .order_by(desc(db_models.ChatSession.created_at))
            .options(selectinload(db_models.ChatSession.messages))
        )
        result = await db.execute(query)
        session = result.scalars().first()
        if session:
            return session

    # 세션이 없거나, session_id가 제공되지 않은 경우 새로 생성
    new_session = db_models.ChatSession(user_id=user_id)
    db.add(new_session)
    await db.flush()
    await db.refresh(new_session)
    return new_session


async def get_chat_messages(
    db: AsyncSession, session_uuid: UUID, session_created_at: str
) -> List[db_models.ChatMessage]:
    """특정 세션의 모든 메시지를 조회"""
    query = (
        select(db_models.ChatMessage)
        .where(
            db_models.ChatMessage.session_uuid == session_uuid,
            db_models.ChatMessage.session_created_at == session_created_at,
        )
        .order_by(db_models.ChatMessage.created_at)
    )
    result = await db.execute(query)
    return result.scalars().all()


async def create_chat_message(
    db: AsyncSession, message: schemas.ChatMessageCreate
) -> db_models.ChatMessage:
    """새로운 채팅 메시지를 생성"""
    db_message = db_models.ChatMessage(**message.model_dump())
    db.add(db_message)
    await db.flush()
    await db.refresh(db_message)
    return db_message
