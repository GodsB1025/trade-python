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
    모니터링이 활성화된 모든 북마크의 최신 변경 사항을 주기적으로 감지하고, 유의미한 업데이트 발생 시 알림 생성 작업을 Redis에 큐잉하는 백그라운드 엔드포인트입니다.

    <details>
    <summary>I. Producer (생산자: FastAPI) 로직</summary>

    > 이 엔드포인트는 알림 작업을 생성하는 '생산자' 역할을 수행합니다.

    **주요 처리 순서:**
    1.  **분산 락 (Distributed Lock):** Redis (`SET NX`)를 사용하여 여러 인스턴스의 동시 실행을 방지합니다.
    2.  **북마크 조회:** `monitoring_active=True`인 모든 북마크를 DB에서 조회합니다.
    3.  **병렬 및 속도 제어 처리:**
        -   `asyncio.Semaphore`: LangChain 서비스에 대한 동시 요청 수를 제한하여 과부하를 방지합니다.
        -   `Aiolimiter`: 분당 요청 수를 제어하여 외부 API의 속도 제한(Rate Limit)을 준수합니다.
        -   `Tenacity`: API 호출 실패 시 지수 백오프(Exponential Backoff)를 적용하여 자동으로 재시도합니다.
    4.  **업데이트 처리 및 Redis 큐잉 (신뢰성 큐 패턴):**
        -   **DB 저장:** 변경 사항 발견 시, `update_feeds` 테이블에 업데이트 내역을 저장합니다.
        -   **Redis 큐잉:**
            1.  **알림 상세 정보 (Hash):** `HSET` 명령어를 사용하여 `daily_notification:detail:{uuid}` 키에 알림 상세 내용을 저장합니다.
                -   `HSET`: Hash 데이터 구조(Key-Value 맵과 유사)에 여러 필드-값 쌍을 저장하는 명령어입니다.
            2.  **알림 작업 큐 (List):** `LPUSH` 명령어를 사용하여 `daily_notification:queue:{TYPE}` (예: `...:EMAIL`) 키에 처리할 작업의 `uuid`를 추가합니다.
                -   `LPUSH`: List 데이터 구조(Array 또는 LinkedList와 유사)의 맨 앞에 요소를 추가하는 명령어입니다.
    </details>

    <details>
    <summary>II. Consumer (소비자: Spring Boot) 구현 가이드</summary>

    > Redis 큐에 쌓인 작업은 Spring Boot와 같은 별도의 워커(Worker) 프로세스가 처리해야 합니다.

    **권장 처리 순서 (신뢰성 보장):**
    1.  **작업 원자적으로 이동 (`BLMOVE`):** '대기 큐'에서 '처리 중 큐'로 작업을 안전하게 이동시킵니다.
    2.  **상세 정보 조회 (`HGETALL`):** 이동시킨 작업 `uuid`를 사용하여 상세 정보를 가져옵니다.
    3.  **비즈니스 로직 수행:** 실제 이메일 발송 등 알림 처리를 수행합니다.
    4.  **작업 완료 처리 (`LREM`):** 작업이 성공하면 '처리 중 큐'에서 해당 작업을 제거합니다.
    5.  **예외 처리:** 오류 발생 시 작업을 '처리 중 큐'에 남겨두어 데이터 유실을 방지합니다.
    </details>

    <details>
    <summary>III. 핵심 Redis 명령어 및 Spring Data Redis 타입 매핑</summary>

    > Spring Boot (`RedisTemplate`) 사용 시 각 Redis 명령어와 매핑되는 Java 타입을 명시합니다.

    #### **1. `BLMOVE`**
    -   **설명:** 리스트의 마지막 요소를 다른 리스트의 첫 번째 요소로 **원자적으로 이동**시키고, 만약 원본 리스트가 비어있으면 지정된 시간 동안 새로운 요소가 추가되기를 기다리는(Blocking) 명령어입니다.
    -   **핵심 역할:** 워커가 여러 개 실행되어도 **단 하나의 워커만이 작업을 가져가도록 보장**하며(경쟁 상태 방지), 큐가 비었을 때 불필요한 CPU 사용을 막아줍니다. 작업 유실 방지의 핵심입니다.
    -   **Java `RedisTemplate` 반환 타입:** `String`
        -   이동된 작업 `uuid`가 문자열로 반환됩니다. 큐가 비어 타임아웃이 발생하면 `null`이 반환됩니다.
        ```java
        String taskId = redisTemplate.opsForList().move(
            "daily_notification:queue:EMAIL", ListOperations.Direction.RIGHT,
            "daily_notification:processing_queue:EMAIL", ListOperations.Direction.LEFT,
            Duration.ofSeconds(10)
        );
        if (taskId != null) {
            // ... process task
        }
        ```

    #### **2. `HGETALL`**
    -   **설명:** Hash 데이터 구조에서 모든 필드와 값의 쌍을 가져오는 명령어입니다.
    -   **핵심 역할:** 작업 `uuid`에 해당하는 모든 알림 상세 정보(수신자, 메시지 내용 등)를 한 번의 명령어로 조회합니다.
    -   **Java `RedisTemplate` 반환 타입:** `Map<Object, Object>` 또는 `Map<String, String>`
        -   조회된 Hash의 필드-값 쌍들이 `Map`으로 반환됩니다. `RedisTemplate` 설정에 따라 타입을 명시적으로 지정할 수 있습니다.
        ```java
        Map<Object, Object> details = redisTemplate.opsForHash().entries("daily_notification:detail:" + taskId);
        String userId = (String) details.get("user_id");
        String message = (String) details.get("message");
        ```

    #### **3. `LREM`**
    -   **설명:** 리스트에서 지정된 값과 일치하는 요소를 **개수를 지정하여** 제거하는 명령어입니다.
    -   **핵심 역할:** 알림 발송을 성공적으로 마친 작업을 '처리 중 큐'에서 **정확히 하나만 제거**하여, 동일한 작업이 중복 처리되는 것을 방지합니다.
    -   **Java `RedisTemplate` 반환 타입:** `Long`
        -   제거된 요소의 개수가 반환됩니다. 보통 `1`이 반환되며, `0`이 반환되면 무언가 잘못된 상황(예: 이미 삭제됨)임을 인지할 수 있습니다.
        ```java
        // count: 1 > 앞에서부터 taskId와 일치하는 요소 1개만 제거
        Long removedCount = redisTemplate.opsForList().remove("daily_notification:processing_queue:EMAIL", 1, taskId);
        ```
    </details>
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
