import time
import uuid
import json
from typing import Callable, Dict, Any, Optional

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
    - 클라이언트 IP, HTTP 메서드, 경로, 상태 코드, 요청 바디 등 상세한 정보를 구조화된 로그로 출력.
    - 민감한 데이터는 마스킹 처리하여 보안을 유지.
    """

    # 민감한 데이터로 간주되는 필드명들
    SENSITIVE_FIELDS = {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "key",
        "auth",
        "authorization",
        "credential",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "session_token",
        "jwt",
        "bearer",
        "cookie",
        "x-api-key",
        "x-auth-token",
        "x-access-token",
    }

    # 요청 바디 로깅 최대 크기 (바이트)
    MAX_BODY_SIZE = 10 * 1024  # 10KB

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    def _mask_sensitive_data(self, data: Any) -> Any:
        """
        민감한 데이터를 마스킹 처리함.

        Args:
            data: 마스킹할 데이터

        Returns:
            마스킹된 데이터
        """
        if isinstance(data, dict):
            masked_data = {}
            for key, value in data.items():
                if isinstance(key, str) and key.lower() in self.SENSITIVE_FIELDS:
                    masked_data[key] = "***MASKED***"
                else:
                    masked_data[key] = self._mask_sensitive_data(value)
            return masked_data
        elif isinstance(data, list):
            return [self._mask_sensitive_data(item) for item in data]
        else:
            return data

    def _parse_request_body(self, body: bytes) -> Optional[Dict[str, Any]]:
        """
        요청 바디를 파싱하여 JSON 형태로 변환함.

        Args:
            body: 요청 바디 바이트 데이터

        Returns:
            파싱된 JSON 데이터 또는 None
        """
        if not body:
            return None

        try:
            # 크기 제한 체크
            if len(body) > self.MAX_BODY_SIZE:
                body_str = body[: self.MAX_BODY_SIZE].decode("utf-8", errors="ignore")
                return {
                    "truncated": True,
                    "size": len(body),
                    "preview": body_str + "...[TRUNCATED]",
                }

            # JSON 파싱 시도
            body_str = body.decode("utf-8")
            try:
                parsed_data = json.loads(body_str)
                return self._mask_sensitive_data(parsed_data)
            except json.JSONDecodeError:
                # JSON이 아닌 경우 문자열로 반환
                return {"raw_body": body_str}

        except Exception as e:
            log.warning(f"요청 바디 파싱 중 오류 발생: {e}")
            return {"parse_error": str(e)}

    async def _get_request_body(self, request: Request) -> Optional[Dict[str, Any]]:
        """
        요청 바디를 안전하게 읽어옴.

        Args:
            request: FastAPI 요청 객체

        Returns:
            파싱된 요청 바디 또는 None
        """
        try:
            # 요청 바디 읽기
            body = await request.body()
            if not body:
                return None

            return self._parse_request_body(body)

        except Exception as e:
            log.warning(f"요청 바디 읽기 중 오류 발생: {e}")
            return {"read_error": str(e)}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        structlog.contextvars.clear_contextvars()

        request_id = correlation_id.get()
        if request_id is None:
            request_id = str(uuid.uuid4())

        structlog.contextvars.bind_contextvars(request_id=request_id)

        start_time = time.perf_counter()

        # 요청 바디 로깅
        request_body_data = await self._get_request_body(request)

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
                "client_host": request.client.host if request.client else "unknown",
                "request_method": request.method,
                "request_path": request.url.path,
                "request_query_params": str(request.query_params),
                "http_version": request.scope.get("http_version", "unknown"),
            }

            # 요청 바디 정보 추가
            if request_body_data:
                log_info["request_body"] = request_body_data

            # 요청 헤더 정보 추가 (민감한 헤더는 마스킹)
            headers = dict(request.headers)
            masked_headers = self._mask_sensitive_data(headers)
            log_info["request_headers"] = masked_headers

            if "response" in locals():
                log_info["status_code"] = response.status_code
                log.info("Request completed", **log_info)
            else:
                log.error("Request failed without a response", **log_info)

        return response
