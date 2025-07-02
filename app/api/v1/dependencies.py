"""
API 엔드포인트에서 사용할 의존성을 정의하는 모듈
"""
from functools import lru_cache
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chat_service import ChatService
from app.services.news_service import NewsService
from app.db.session import get_db


def get_chat_service(
    db: AsyncSession = Depends(get_db)
) -> ChatService:
    """
    ChatService 의존성 주입.

    요청마다 DB 세션을 주입받아 새로운 ChatService 인스턴스를 생성.
    """
    return ChatService(db_session=db)


def get_news_service() -> NewsService:
    """
    NewsService 의존성 주입.

    NewsService는 DB 세션이 필요 없으므로, 인스턴스만 생성하여 반환.
    LLM Provider와 같은 무거운 객체는 NewsService 내부에서 싱글톤으로 관리됨.
    """
    return NewsService()
