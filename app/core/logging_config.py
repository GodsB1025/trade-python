import logging
import sys
from typing import List, Union

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
    shared_processors: List[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    log_level: Union[int, str]
    renderer: Processor

    if settings.ENVIRONMENT == "development":
        log_level = "DEBUG"
        shared_processors.append(structlog.processors.TimeStamper(fmt="iso"))
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        log_level = "INFO"
        shared_processors.append(structlog.processors.TimeStamper(fmt="iso"))
        renderer = structlog.processors.JSONRenderer()

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
            "formatters": {
                "default": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        renderer,
                    ],
                    "foreign_pre_chain": shared_processors,
                },
            },
            "handlers": {
                "default": {
                    "level": log_level,
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": sys.stdout,
                },
            },
            "loggers": {
                "": {"handlers": ["default"], "level": log_level, "propagate": False},
                "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "sqlalchemy": {"handlers": ["default"], "level": "WARNING", "propagate": False},
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
