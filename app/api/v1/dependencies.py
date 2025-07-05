"""
API 엔드포인트에서 사용할 의존성을 정의하는 모듈
"""

from functools import lru_cache
from fastapi import Depends, HTTPException
import redis.asyncio as redis
import logging
from typing import Type
from redis.asyncio.client import Redis
from redis.exceptions import AuthenticationError, RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.chat_service import ChatService
from app.services.news_service import NewsService
from app.services.langchain_service import LLMService
from app.services.chat_history_service import PostgresChatMessageHistory
from app.db.session import get_db

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_llm_service() -> LLMService:
    """
    LLMService 의존성 주입.
    애플리케이션 생명주기 동안 단일 인스턴스를 유지 (싱글톤).
    """
    return LLMService()


@lru_cache(maxsize=1)
def get_redis_pool() -> redis.ConnectionPool:
    """
    Redis 연결 풀을 생성.
    실제 연결은 클라이언트가 처음 사용할 때 이루어짐.
    """
    try:
        pool = redis.ConnectionPool.from_url(
            settings.redis_dsn,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        logger.info(
            f"Redis 연결 풀 생성 완료: {settings.REDIS_HOST}:{settings.REDIS_PORT}"
        )
        return pool
    except Exception as e:
        logger.critical(f"치명적 오류: Redis 연결 풀 생성 실패. 에러: {e}")
        raise


async def get_redis_client(
    pool: redis.ConnectionPool = Depends(get_redis_pool),
) -> Redis:
    """
    Redis 클라이언트 의존성 주입.
    생성된 연결 풀에서 클라이언트를 가져와 연결을 테스트.
    """
    try:
        client = redis.Redis(connection_pool=pool)
        await client.ping()
        return client
    except AuthenticationError as e:
        logger.error(f"Redis 인증 실패: {e}")
        raise HTTPException(
            status_code=503, detail="Failed to authenticate with Redis."
        )
    except RedisError as e:
        logger.error(f"Redis 클라이언트 생성 또는 ping 실패: {e}")
        raise HTTPException(
            status_code=503, detail=f"Failed to create or connect to Redis: {e}"
        )
    except Exception as e:
        logger.error(f"알 수 없는 Redis 오류: {e}")
        raise HTTPException(
            status_code=503, detail=f"An unknown error occurred with Redis: {e}"
        )


def get_chat_service(llm_service: LLMService = Depends(get_llm_service)) -> ChatService:
    """
    ChatService 의존성 주입.

    요청마다 새로운 ChatService 인스턴스를 생성하되,
    싱글톤인 LLMService를 주입받아 사용.
    """
    return ChatService(llm_service=llm_service)


def get_news_service() -> NewsService:
    """
    NewsService 의존성 주입.

    NewsService는 DB 세션이 필요 없으므로, 인스턴스만 생성하여 반환.
    LLM Provider와 같은 무거운 객체는 NewsService 내부에서 싱글톤으로 관리됨.
    """
    return NewsService()


def get_chat_history_service() -> Type[PostgresChatMessageHistory]:
    """
    PostgresChatMessageHistory 클래스 타입을 반환하는 의존성.

    실제 인스턴스는 엔드포인트에서 session_uuid와 user_id를 사용하여 생성.
    """
    return PostgresChatMessageHistory


# 타입 힌트를 위한 별칭
# get_db는 app.db.session에서 import되며, 비동기 데이터베이스 세션을 제공
# 사용 방법: db: AsyncSession = Depends(get_db)
__all__ = [
    "get_llm_service",
    "get_redis_pool",
    "get_redis_client",
    "get_chat_service",
    "get_news_service",
    "get_chat_history_service",
    "get_db",
    "AsyncSession",
]
