from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyUrl, RedisDsn, Field, AnyHttpUrl, EmailStr
from typing import List, Union


class Settings(BaseSettings):
    """
    애플리케이션의 설정을 관리하는 클래스.
    .env 파일에서 환경 변수를 로드함.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

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
    DATABASE_URL: str = "postgresql://localhost:5432/tradedb"

    # Redis - 환경변수 기반 설정으로 변경
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_USERNAME: str | None = None
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0
    REDIS_TIMEOUT: int = 2000  # milliseconds

    @property
    def redis_dsn(self) -> str:
        """
        Redis DSN 생성
        개발 환경에서는 인증 없는 로컬 Redis 사용
        운영 환경에서는 인증이 필요한 Redis 사용
        """
        # 인증 정보가 있는 경우
        if self.REDIS_USERNAME and self.REDIS_PASSWORD:
            return f"redis://{self.REDIS_USERNAME}:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        # 인증 정보가 없는 경우 (개발 환경)
        else:
            return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # Monitoring Settings
    MONITORING_JOB_LOCK_KEY: str = "monitoring:job:lock"
    MONITORING_JOB_LOCK_TIMEOUT: int = 3600  # 1 hour
    MONITORING_CONCURRENT_REQUESTS_LIMIT: int = 5
    MONITORING_RPM_LIMIT: int = Field(
        default=60, description="모니터링 시 Claude API에 대한 분당 요청 수 제한"
    )
    MONITORING_NOTIFICATION_QUEUE_KEY_PREFIX: str = "daily_notification:queue:"
    MONITORING_NOTIFICATION_DETAIL_KEY_PREFIX: str = "daily_notification:detail:"

    # AI Model API Keys & Settings
    ANTHROPIC_API_KEY: str = Field(default="", alias="ANTHROPIC_API_KEY")
    VOYAGE_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    # Web Search Settings
    WEB_SEARCH_ENABLED: bool = True

    # Logging Settings
    LOG_FILE_PATH: str = "logs/app.log"
    LOG_ROTATION_WHEN: str = "midnight"
    LOG_ROTATION_INTERVAL: int = 1
    LOG_ROTATION_BACKUP_COUNT: int = 7

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:8081", "http://127.0.0.1:8081"]

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
