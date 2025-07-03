"""
뉴스 생성 API 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_news_service
from app.db import crud
from app.db.session import get_db
from app.services.news_service import NewsService
# from app.services.db_service import DBService # TODO: DB 서비스 구현 후 주석 해제

router = APIRouter()


@router.post("/", status_code=201, summary="온디맨드 뉴스 생성")
async def generate_trade_news(
    db: AsyncSession = Depends(get_db),
    news_service: NewsService = Depends(get_news_service),
):
    """
    Spring Boot 스케줄러에 의해 호출되는 온디맨드 뉴스 생성 엔드포인트.
    Claude 4 Sonnet의 네이티브 웹 검색을 사용하여 최신 무역 뉴스를 생성하고 DB에 저장합니다.
    """
    try:
        # NewsService를 통해 Claude 웹 검색 및 뉴스 생성 실행
        generated_news_list = await news_service.create_news_via_claude()

        if not generated_news_list:
            return {
                "status": "success",
                "message": "No new news found.",
                "generated_count": 0,
            }

        # 생성된 뉴스를 DB에 저장
        await crud.create_news_articles(db, news_items=generated_news_list)
        await db.commit()  # 변경사항을 데이터베이스에 최종 커밋

        return {
            "status": "success",
            "message": f"{len(generated_news_list)} news items have been successfully generated and saved.",
            "generated_count": len(generated_news_list)
        }
    except Exception as e:
        # TODO: 에러 로깅 추가 권장 (실제 프로덕션에서는 구조화된 로깅 필요)
        await db.rollback()  # DB 트랜잭션 롤백
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred during news generation: {str(e)}",
        )
