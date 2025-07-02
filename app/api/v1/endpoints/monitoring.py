"""
북마크 모니터링 API 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_news_service
from app.db import crud
from app.db.session import get_db
from app.models import schemas
from app.services.news_service import NewsService

router = APIRouter()


@router.post("/run-monitoring", response_model=schemas.MonitoringResult)
async def run_bookmark_monitoring(
    db: AsyncSession = Depends(get_db),
    news_service: NewsService = Depends(get_news_service),
):
    """
    Spring Boot 스케줄러에 의해 호출되는 북마크 모니터링 엔드포인트.

    활성화된 모든 북마크를 조회하여 최신 업데이트를 확인하고,
    변경 사항이 감지되면 `update_feeds` 테이블에 요약 정보를 저장합니다.
    """
    try:
        # 1. 활성화된 북마크 조회
        active_bookmarks = await crud.get_active_bookmarks(db)
        monitored_count = len(active_bookmarks)
        update_count = 0

        # 2. 각 북마크에 대해 업데이트 확인
        for bookmark in active_bookmarks:
            # 3. NewsService를 통해 북마크 관련 변경사항 감지 및 구조화된 데이터 획득
            update_data = await news_service.find_updates_for_bookmark(bookmark)

            if update_data:
                # 4. 변경 사항이 있으면 update_feeds 테이블에 저장
                feed_data = schemas.UpdateFeedCreate(**update_data)
                await crud.create_update_feed(db, feed_data)
                update_count += 1

        await db.commit()

        return schemas.MonitoringResult(
            monitored_bookmarks=monitored_count, updates_found=update_count
        )
    except Exception as e:
        # TODO: 실제 프로덕션에서는 구조화된 로깅 프레임워크를 사용해야 합니다.
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"An error occurred during monitoring: {str(e)}")
