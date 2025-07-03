import logging
import logging.config
import sys
from typing import List, Union
import os

import structlog
from structlog.types import Processor

from app.core.config import settings


def configure_logging() -> None:
    """
    애플리케이션의 로깅 시스템을 구성함.

    - 환경(개발/프로덕션)에 따라 다른 로깅 프로세서와 포맷터를 설정.
    - `structlog`를 사용하여 구조화된 로그를 생성.
    - Python의 기본 `logging` 모듈과 통합하여 서드파티 라이브러리의 로그도 일관되게 처리.
    """
    # 로그 파일을 저장할 디렉토리 생성
    log_dir = os.path.dirname(settings.LOG_FILE_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    shared_processors: List[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    log_level: Union[int, str]

    if settings.ENVIRONMENT == "development":
        log_level = "DEBUG"
        console_renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        log_level = "INFO"
        console_renderer = structlog.processors.JSONRenderer()

    # 파일 로거는 항상 JSON 렌더러 사용
    file_renderer = structlog.processors.JSONRenderer()

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,  # 다른 라이브러리 로거와의 호환성을 위해 False로 변경
            "formatters": {
                "console": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        console_renderer,
                    ],
                    "foreign_pre_chain": shared_processors,
                },
                "file": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        file_renderer,
                    ],
                    "foreign_pre_chain": shared_processors,
                },
            },
            "handlers": {
                "console": {
                    "level": log_level,
                    "class": "logging.StreamHandler",
                    "formatter": "console",
                    "stream": sys.stdout,
                },
                "file": {
                    "level": log_level,
                    "class": "logging.handlers.TimedRotatingFileHandler",
                    "filename": settings.LOG_FILE_PATH,
                    "when": settings.LOG_ROTATION_WHEN,
                    "interval": settings.LOG_ROTATION_INTERVAL,
                    "backupCount": settings.LOG_ROTATION_BACKUP_COUNT,
                    "formatter": "file",
                    "encoding": "utf8",
                    "utc": True,
                },
            },
            "loggers": {
                "": {"handlers": ["console", "file"], "level": log_level, "propagate": False},
                "uvicorn.error": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
                "uvicorn.access": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
                "sqlalchemy": {"handlers": ["console", "file"], "level": "WARNING", "propagate": False},
            },
        }
    )

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
