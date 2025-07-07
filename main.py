#!/usr/bin/env python3
"""
Trade Python AI Service 엔트리포인트
LangChain + Claude + FastAPI 기반 웹 검색 AI 서비스
"""
import uvicorn
from app.core.config import settings


def main():
    """메인 실행 함수"""
    print(f"🚀 {settings.PROJECT_NAME} v{settings.app_version} 시작")
    print(f"📝 설정된 Anthropic 모델: {settings.ANTHROPIC_MODEL}")
    print(f"🔍 웹 검색: {'활성화' if settings.WEB_SEARCH_ENABLED else '비활성화'}")

    uvicorn.run(
        "app.main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=settings.debug,
        timeout_keep_alive=600,  # 10분으로 증가
        timeout_graceful_shutdown=60,  # 1분으로 증가
        log_level="info" if not settings.debug else "debug",
    )


if __name__ == "__main__":
    main()
