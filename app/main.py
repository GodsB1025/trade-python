"""
FastAPI 메인 애플리케이션
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from asgi_correlation_id import CorrelationIdMiddleware
from starlette.middleware.cors import CORSMiddleware
from langchain.globals import set_debug
import logging

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.middleware.logging_middleware import LoggingMiddleware

set_debug(True)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """
    FastAPI 애플리케이션을 생성하고 설정합니다.

    - 로깅 설정 초기화
    - CORS 미들웨어 추가
    - Correlation ID 미들웨어 추가
    - 커스텀 로깅 미들웨어 추가
    - API 라우터 포함
    """
    configure_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
    )

    # 전역 RequestValidationError 핸들러 추가
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        """
        전역 요청 validation 에러 핸들러
        422 에러 발생 시 자세한 로그 출력
        """
        try:
            # 요청 본문 읽기
            body = await request.body()
            body_str = body.decode("utf-8") if body else "없음"

            # 요청 정보 로깅
            logger.error(f"=== 422 VALIDATION ERROR 발생 ===")
            logger.error(f"요청 URL: {request.url}")
            logger.error(f"요청 메소드: {request.method}")
            logger.error(f"요청 헤더: {dict(request.headers)}")
            logger.error(f"요청 본문: {body_str}")
            logger.error(f"Validation 에러: {exc.errors()}")
            logger.error(f"================================")

            # 에러 응답 반환
            return JSONResponse(
                status_code=422,
                content={
                    "detail": exc.errors(),
                    "received_body": body_str,
                    "expected_format": {
                        "user_id": "int (선택사항)",
                        "session_uuid": "string (선택사항)",
                        "message": "string (필수, 1-5000자)",
                    },
                    "help": "message 필드는 필수이며, 1자 이상 5000자 이하여야 함",
                },
            )
        except Exception as e:
            logger.error(f"Validation 에러 핸들러에서 예외 발생: {e}", exc_info=True)
            return JSONResponse(
                status_code=422,
                content={
                    "detail": "요청 검증 실패",
                    "error": "요청 본문을 읽을 수 없음",
                },
            )

    # CORS 설정
    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # 미들웨어 추가
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(LoggingMiddleware)

    app.include_router(api_router, prefix=settings.API_V1_STR)

    return app


app = create_app()
