"""
FastAPI 메인 애플리케이션
"""
from fastapi import FastAPI
from asgi_correlation_id import CorrelationIdMiddleware
from starlette.middleware.cors import CORSMiddleware
from langchain.globals import set_debug

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.middleware.logging_middleware import LoggingMiddleware

# LangChain 디버그 모드 활성화
# True로 설정 시, 모든 LangChain 구성 요소의 상세한 입출력 정보를 로깅합니다.
set_debug(True)


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

    # CORS 설정
    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                str(origin) for origin in settings.BACKEND_CORS_ORIGINS
            ],
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
