from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyUrl, RedisDsn, Field
from typing import List, Union


class Settings(BaseSettings):
    """
    애플리케이션의 설정을 관리하는 클래스.
    .env 파일에서 환경 변수를 로드함.
    """
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding='utf-8', extra='ignore')

    # Project Settings
    PROJECT_NAME: str = "Trade Python AI Service"
    API_V1_STR: str = "/api/v1"
    app_version: str = "6.1.0"
    GUEST_USER_ID: int = 1
    debug: bool = False
    ENVIRONMENT: str = "development"

    # Server Settings
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000

    # Database
    DATABASE_URL: str = Field(..., env="DATABASE_URL")

    # Redis
    REDIS_HOST: str = "db.k-developer.pro"
    REDIS_PORT: int = 6379
    REDIS_USERNAME: str = "trade"
    REDIS_PASSWORD: str = "your-redis-password-here"
    REDIS_TIMEOUT: int = 2000  # milliseconds

    @property
    def redis_dsn(self) -> RedisDsn:
        return f"redis://{self.REDIS_USERNAME}:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}"

    # AI Model API Keys & Settings
    ANTHROPIC_API_KEY: str = Field(..., alias="CLAUDE_API_KEY")
    VOYAGE_API_KEY: str = Field(..., env="VOYAGE_API_KEY")
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    # Web Search Settings
    WEB_SEARCH_ENABLED: bool = True

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:8081",
        "http://127.0.0.1:8081"
    ]

    # 비동기 드라이버를 사용하도록 URL을 재구성
    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """
        SQLAlchemy 비동기 엔진을 위해 'postgresql' 스키마를
        'postgresql+asyncpg'로 변환함
        """
        url_str = str(self.DATABASE_URL)
        if url_str.startswith("postgresql://"):
            return url_str.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url_str

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """
        SQLAlchemy 동기 엔진(LangChain PGVector)을 위해 'postgresql' 스키마를
        'postgresql+psycopg'로 변환함
        """
        url_str = str(self.DATABASE_URL)
        if url_str.startswith("postgresql://"):
            return url_str.replace("postgresql://", "postgresql+psycopg://", 1)
        return url_str


# 싱글톤처럼 사용하기 위해 인스턴스 생성
settings = Settings()
