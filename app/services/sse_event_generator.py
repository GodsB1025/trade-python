import json
import asyncio
from datetime import datetime
from typing import Dict, Any, AsyncGenerator, Optional, List
import uuid

from app.models.schemas import DetailPageInfo, DetailButton


class SSEEventGenerator:
    """SSE 이벤트 생성기"""

    def _get_timestamp(self) -> str:
        """ISO 8601 형식의 타임스탬프를 반환함"""
        return datetime.utcnow().isoformat() + "Z"

    def _format_event(self, event_name: str, data: Dict[str, Any]) -> str:
        """SSE 이벤트 문자열을 포맷팅함"""
        return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def generate_processing_status_event(
        self, message: str, step: int, total_steps: int, is_sub_step: bool = False
    ) -> str:
        """서버 처리 상태를 알리는 이벤트 생성"""
        base_progress = ((step - 1) / total_steps) * 100
        if is_sub_step:
            progress = int(
                base_progress + (1 / total_steps) * 50
            )  # 현재 단계의 절반 진행으로 표시
            message = f"└ {message}"
        else:
            progress = int((step / total_steps) * 100)

        data = {
            "id": f"status-{uuid.uuid4().hex[:8]}",
            "type": "processing_status",
            "message": message,
            "progress": progress,
            "current_step": step,
            "total_steps": total_steps,
            "timestamp": self._get_timestamp(),
        }
        return self._format_event("processing_status", data)

    def generate_detail_buttons_start_event(self, buttons_count: int = 3) -> str:
        """상세페이지 버튼 준비 시작 이벤트"""
        data = {
            "type": "start",
            "buttonsCount": buttons_count,
            "estimatedPreparationTime": 5000,
            "timestamp": self._get_timestamp(),
            "processingInfo": {
                "fallback_available": True,
                "cache_checked": True,
                "web_search_enabled": True,
            },
        }
        return self._format_event("detail_buttons_start", data)

    async def generate_detail_button_events(
        self, detail_info: DetailPageInfo
    ) -> AsyncGenerator[str, None]:
        """상세페이지 버튼 준비 완료 이벤트들 생성"""

        for i, button in enumerate(detail_info.detail_buttons):
            button_data = {
                "type": "button",
                "buttonType": button.type,
                "priority": button.priority,
                "url": button.url,
                "title": button.label,
                "description": self._get_button_description(button.type),
                "isReady": True,
                "metadata": {
                    "hscode": detail_info.hscode,
                    "confidence": detail_info.confidence_score,
                    "source": detail_info.analysis_source,
                    "query_params": button.query_params or {},
                },
                "actionData": {
                    "queryParams": button.query_params or {},
                    "analytics": {
                        "click_tracking": True,
                        "conversion_target": f"{button.type.lower()}_detail_view",
                    },
                },
            }
            yield self._format_event("detail_button_ready", button_data)
            await asyncio.sleep(0.1)

        complete_data = {
            "type": "complete",
            "totalPreparationTime": detail_info.processing_time_ms,
            "buttonsGenerated": len(detail_info.detail_buttons),
            "timestamp": self._get_timestamp(),
            "summary": {
                "hscode_detected": detail_info.hscode,
                "confidence_score": detail_info.confidence_score,
                "analysis_source": detail_info.analysis_source,
                "fallback_used": detail_info.analysis_source == "fallback",
                "cache_hit": detail_info.analysis_source == "cache",
                "web_search_used": detail_info.analysis_source == "web_search",
            },
            "performance": {
                "total_processing_time": detail_info.processing_time_ms,
                "database_queries": 0,
            },
        }
        yield self._format_event("detail_buttons_complete", complete_data)

    def generate_detail_buttons_timeout_event(self) -> str:
        """상세페이지 버튼 준비 타임아웃 이벤트"""
        data = {
            "type": "timeout",
            "errorCode": "DETAIL_PAGE_TIMEOUT",
            "errorMessage": "상세페이지 정보 준비 시간 초과",
            "timestamp": self._get_timestamp(),
            "fallbackActivated": True,
            "retryInfo": {"retryable": True, "retryAfter": 30, "maxRetries": 3},
        }
        return self._format_event("detail_buttons_error", data)

    def generate_detail_buttons_error_event(
        self,
        error_code: str,
        error_message: str,
        detail_info: Optional[DetailPageInfo] = None,
    ) -> str:
        """상세페이지 버튼 에러 이벤트"""
        data = {
            "type": "error",
            "errorCode": error_code,
            "errorMessage": error_message,
            "timestamp": self._get_timestamp(),
            "fallbackActivated": True,
            "partialResults": {
                "buttonsGenerated": (
                    len(detail_info.detail_buttons) if detail_info else 0
                ),
                "hscode_detected": detail_info.hscode if detail_info else None,
                "confidence_score": (
                    detail_info.confidence_score if detail_info else 0.0
                ),
            },
            "retryInfo": {"retryable": True, "retryAfter": 30, "maxRetries": 3},
        }
        return self._format_event("detail_buttons_error", data)

    def _get_button_description(self, button_type: str) -> str:
        """버튼 타입별 설명 반환"""
        descriptions = {
            "HS_CODE": "관세율, 규제정보 등 상세 조회",
            "REGULATION": "수출입 규제, 허가사항 등",
            "STATISTICS": "수출입 현황, 트렌드 분석",
        }
        return descriptions.get(button_type, "상세 정보 조회")

    def generate_tool_use_event(
        self, tool_name: str, tool_input: Dict[str, Any], tool_use_id: str
    ) -> str:
        """AI의 도구 사용 시작 이벤트를 생성함"""
        event_data = {
            "type": "tool_use",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "timestamp": self._get_timestamp(),
        }
        return self._format_event("tool_use", event_data)

    def generate_tool_use_end_event(
        self, tool_name: str, output: Any, tool_use_id: str
    ) -> str:
        data = {
            "type": "tool_use_end",
            "tool_name": tool_name,
            "tool_use_id": tool_use_id,
            "output": output,
            "timestamp": self._get_timestamp(),
        }
        return self._format_event("tool_use_end", data)

    def generate_thinking_process_event(self, thought: str) -> str:
        """AI의 사고 과정(Thinking) 이벤트를 생성함"""
        event_data = {
            "type": "thinking",
            "thought": thought,
            "timestamp": self._get_timestamp(),
        }
        return self._format_event("thinking_process", event_data)

    def generate_hscode_inferred_event(
        self, hscode: str, product_name: Optional[str]
    ) -> str:
        """
        초기 HSCode 추론 완료 이벤트를 생성함
        """
        data = {
            "type": "hscode_inferred",
            "hscode": hscode,
            "product_name": product_name,
            "confidence": 0.85,  # 예비 추론 단계의 신뢰도 (고정값)
            "source": "preliminary_llm_extraction",
            "timestamp": self._get_timestamp(),
        }
        return self._format_event("hscode_inferred", data)
