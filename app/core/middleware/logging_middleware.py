import time
import uuid
from typing import Callable

import structlog
from asgi_correlation_id import correlation_id
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

log = structlog.get_logger()


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    FastAPI 요청/응답에 대한 로깅을 처리하는 미들웨어.

    - 각 요청에 대한 시작 시간과 처리 시간을 기록.
    - `asgi_correlation_id`로부터 요청 ID를 가져와 로그 컨텍스트에 바인딩.
    - 클라이언트 IP, HTTP 메서드, 경로, 상태 코드 등 상세한 정보를 구조화된 로그로 출력.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        structlog.contextvars.clear_contextvars()

        request_id = correlation_id.get()
        if request_id is None:
            request_id = str(uuid.uuid4())

        structlog.contextvars.bind_contextvars(request_id=request_id)

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
        except Exception as e:
            log.exception("Unhandled exception")
            raise e
        finally:
            process_time = time.perf_counter() - start_time

            log_info = {
                "process_time": f"{process_time:.4f}",
                "client_host": request.client.host,
                "request_method": request.method,
                "request_path": request.url.path,
                "request_query_params": str(request.query_params),
                "http_version": request.scope.get("http_version", "unknown"),
            }
            if 'response' in locals():
                log_info["status_code"] = response.status_code
                log.info("Request completed", **log_info)
            else:
                log.error("Request failed without a response", **log_info)

        return response
