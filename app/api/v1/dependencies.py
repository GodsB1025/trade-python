"""
API 엔드포인트에서 사용할 의존성을 정의하는 모듈
"""
from functools import lru_cache
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.langchain_service import LangChainService
from app.db.session import get_db


def get_langchain_service(
    db: AsyncSession = Depends(get_db)
) -> LangChainService:
    """
    LangChainService 의존성 주입.

    요청마다 DB 세션을 주입받아 새로운 LangChainService 인스턴스를 생성.
    LLM 모델과 같은 무거운 객체는 서비스 내부에서 캐싱 처리.
    """
    return LangChainService(db_session=db)
