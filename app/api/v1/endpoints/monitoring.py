"""
북마크 모니터링 API 엔드포인트
"""
import logging
import asyncio
import uuid
from typing import Tuple, List

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio.client import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from anthropic import RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from aiolimiter import AsyncLimiter

from app.api.v1.dependencies import get_redis_client, get_langchain_service
from app.core.config import settings
from app.db import crud
from app.db.session import get_db, SessionLocal
from app.services.langchain_service import LangChainService
from app.models.db_models import Bookmark, UpdateFeed
from app.models.monitoring_models import MonitoringUpdate

logger = logging.getLogger(__name__)

# --- Module-level Rate Limiter ---
# 분당 요청 수를 제어하기 위한 공유 처리율 제한기.
# 모든 비동기 작업이 이 인스턴스를 공유하여 전역적인 API 호출 속도를 제어함.
rate_limiter = AsyncLimiter(settings.MONITORING_RPM_LIMIT, 60)

router = APIRouter()


class MonitoringResponse(BaseModel):
    """
    모니터링 실행 결과 응답 모델
    """
    status: str
    monitored_bookmarks: int
    updates_found: int
    lock_status: str


async def _handle_update_found(
    db: AsyncSession,
    redis_client: Redis,
    *,
    bookmark: Bookmark,
    update_result: MonitoringUpdate,
) -> bool:
    """
    "UPDATE_FOUND" 상태의 결과를 처리. DB에 저장하고 Redis 큐에 작업을 기록.

    Returns:
        bool: 업데이트 처리 및 Redis 큐잉 성공 여부
    """
    # 다른 세션에서 온 bookmark 객체를 현재 세션에 병합
    merged_bookmark = await db.merge(bookmark)

    if not update_result.summary:
        logger.warning(
            f"북마크 ID {merged_bookmark.id}에 대한 업데이트 요약이 비어있어 처리를 건너뜁니다.")
        return False

    # Just-in-Time Check: 처리 직전 북마크의 최신 상태를 확인
    await db.refresh(merged_bookmark, attribute_names=['monitoring_active'])
    if not merged_bookmark.monitoring_active:
        logger.info(f"북마크 ID {merged_bookmark.id}가 비활성화되어 알림 생성을 건너뜁니다.")
        return False

    existing_feed = await crud.update_feed.get_by_bookmark_and_content(
        db,
        user_id=merged_bookmark.user_id,
        target_value=merged_bookmark.target_value,
        content=update_result.summary,
    )

    if existing_feed:
        logger.info(
            f"북마크 ID {merged_bookmark.id}에 대한 중복 업데이트 피드가 있어 처리를 건너뜁니다.")
        return False

    # 1. UpdateFeed 생성
    new_feed = await crud.update_feed.create_from_bookmark(
        db, bookmark=merged_bookmark, summary=update_result.summary
    )
    logger.info(
        f"북마크 '{merged_bookmark.display_name}'(ID: {merged_bookmark.id})에 대한 업데이트를 DB에 저장했습니다.")

    # 2. Redis에 알림 작업 큐잉
    # `Redis 데이터 구조.md` v6.2 스펙 기반
    try:
        # TODO: 사용자의 실제 알림 설정을 기반으로 여러 채널(EMAIL, SMS 등)에 대한 작업을 생성해야 함
        if merged_bookmark.email_notification_enabled:
            notification_uuid = str(uuid.uuid4())
            detail_key = f"daily_notification:detail:{notification_uuid}"
            queue_key = "daily_notification:queue:EMAIL"

            # 2-1. 알림 상세 정보 HSET으로 저장
            await redis_client.hset(
                detail_key,
                mapping={
                    "user_id": str(merged_bookmark.user_id),
                    "message": f"'{merged_bookmark.display_name}'에 새로운 업데이트가 있습니다!",
                    "type": "EMAIL",
                    "update_feed_id": str(new_feed.id),
                    "created_at": new_feed.created_at.isoformat(),
                },
            )
            # 2-2. 처리 큐에 작업 ID를 LPUSH
            await redis_client.lpush(queue_key, notification_uuid)

            logger.info(
                f"북마크 ID {merged_bookmark.id}에 대한 EMAIL 알림 작업을 Redis 큐({queue_key})에 추가했습니다.")

        # 다른 채널(예: SMS)에 대한 로직도 여기에 추가 가능
        return True
    except RedisError as e:
        logger.critical(
            f"UpdateFeed(id={new_feed.id}) 저장 후 Redis 큐잉 실패. 수동 조치 필요. 오류: {e}",
            exc_info=True
        )
        # DB 트랜잭션은 성공했으므로 True가 아닌 False를 반환하여 실패를 알림
        return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((asyncio.TimeoutError, RateLimitError)),
    reraise=True  # 재시도 실패 시 최종 예외를 다시 발생시킴
)
async def _fetch_update_with_retry(
    langchain_service: LangChainService, hscode: str
) -> MonitoringUpdate:
    """
    tenacity를 사용하여 재시도 로직을, aiolimiter로 처리율 제한을 적용한 LangChain 서비스 호출 래퍼.
    """
    async with rate_limiter:
        logger.debug(f"HSCode {hscode}에 대한 업데이트 확인 시도...")
        return await langchain_service.get_hscode_update_and_sources(hscode=hscode)


async def _process_bookmark(
    semaphore: asyncio.Semaphore,
    redis_client: Redis,
    *,
    bookmark: Bookmark,
    langchain_service: LangChainService,
) -> bool:
    """
    단일 북마크에 대한 모니터링 프로세스를 실행.
    세마포어를 사용하여 동시 요청 수를 제어.

    Returns:
        bool: 유의미한 업데이트 발견 및 처리 완료 여부
    """
    async with semaphore:
        try:
            update_result = await _fetch_update_with_retry(
                langchain_service=langchain_service, hscode=bookmark.target_value
            )
            logger.debug(f"북마크 ID {bookmark.id} 처리 결과: {update_result.status}")

            if update_result.status == "UPDATE_FOUND":
                # 데이터베이스 작업을 위해 새로운 세션 사용
                async with SessionLocal() as db:
                    async with db.begin():  # 트랜잭션 관리
                        return await _handle_update_found(
                            db, redis_client, bookmark=bookmark, update_result=update_result
                        )
            elif update_result.status == "ERROR":
                logger.error(
                    f"북마크 ID {bookmark.id} 처리 중 LangChain 오류: {update_result.error_message}"
                )

        except RateLimitError as e:
            # 재시도 실패 후에도 RateLimitError가 발생할 수 있음
            logger.warning(
                f"API 속도 제한으로 북마크 ID {bookmark.id} 처리를 최종 실패했습니다. 오류: {e}"
            )
        except Exception as e:
            logger.error(
                f"_process_bookmark 내 예외 발생 (북마크 ID: {bookmark.id}): {e}",
                exc_info=True,
            )
    return False


@router.post("/run-monitoring", response_model=MonitoringResponse)
async def run_monitoring(
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(get_redis_client),
    langchain_service: LangChainService = Depends(get_langchain_service),
):
    """
    주기적으로 호출되어 사용자의 북마크에 대한 최신 변경 사항을 감지하고,
    유의미한 업데이트 발생 시 알림을 생성하기 위한 백그라운드 작업 엔드포인트.

    **주요 로직:**
    1. Redis 분산 락(Distributed Lock)을 사용하여 동시 실행을 방지.
    2. 모니터링이 활성화된 모든 북마크를 데이터베이터스에서 조회.
    3. 각 북마크를 병렬로 처리하여 LangChain 서비스로 최신 정보를 조회.
    4. 변경 사항이 발견되면 'update_feeds' 테이블에 저장하고 'notification_tasks' Outbox 테이블에 알림 작업을 기록.
    5. 결과를 집계하여 반환.

    **참고:**
    'notification_tasks' 테이블에 기록된 작업은 별도의 워커 프로세스에 의해 처리되어
    실제 사용자에게 알림(이메일, SMS 등)을 발송합니다.
    """
    if not redis_client:
        logger.critical("Redis 클라이언트를 사용할 수 없어 모니터링 작업을 시작할 수 없습니다.")
        raise HTTPException(
            status_code=503,
            detail="Redis is not available, cannot start monitoring job.",
        )

    lock = redis_client.lock(
        settings.MONITORING_JOB_LOCK_KEY,
        timeout=settings.MONITORING_JOB_LOCK_TIMEOUT
    )
    if not await lock.acquire(blocking=False):
        logger.warning("이미 다른 모니터링 작업이 실행 중입니다.")
        return MonitoringResponse(
            status="already_running",
            monitored_bookmarks=0,
            updates_found=0,
            lock_status="not_acquired",
        )

    try:
        logger.info("Redis 분산 락 획득 성공")

        active_bookmarks = await crud.get_active_bookmarks(db)
        if not active_bookmarks:
            logger.info("모니터링할 활성 북마크가 없습니다.")
            return MonitoringResponse(
                status="success",
                monitored_bookmarks=0,
                updates_found=0,
                lock_status="acquired",
            )

        monitored_count = len(active_bookmarks)
        logger.info(f"{monitored_count}개의 활성 북마크에 대한 모니터링을 시작합니다.")

        semaphore = asyncio.Semaphore(
            settings.MONITORING_CONCURRENT_REQUESTS_LIMIT)
        tasks = [
            _process_bookmark(
                semaphore,
                redis_client,
                bookmark=b,
                langchain_service=langchain_service,
            )
            for b in active_bookmarks
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 예외가 발생한 경우 로깅
        updates_found_count = 0
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(
                    f"북마크 처리 중 예외 발생 (북마크 ID: {active_bookmarks[i].id}): {res}",
                    exc_info=res
                )
            elif res is True:
                updates_found_count += 1

        logger.info(
            f"모니터링 작업 완료. 총 {monitored_count}개 중 {updates_found_count}개의 업데이트 발견 및 큐잉."
        )
        return MonitoringResponse(
            status="success",
            monitored_bookmarks=monitored_count,
            updates_found=updates_found_count,
            lock_status="acquired",
        )

    except RedisError as e:
        logger.critical(f"Redis 오류로 인해 모니터링 작업을 중단합니다: {e}", exc_info=True)
        raise HTTPException(
            status_code=503, detail=f"Redis error occurred: {e}")
    finally:
        if await lock.locked():
            try:
                await lock.release()
                logger.info("Redis 분산 락 해제 완료")
            except Exception as e:
                logger.warning(f"Redis 락 해제 중 오류 발생: {e}")
