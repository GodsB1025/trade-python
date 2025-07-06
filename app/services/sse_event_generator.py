import json
import asyncio
from datetime import datetime
from typing import Dict, Any, AsyncGenerator, Optional

from app.models.schemas import DetailPageInfo, DetailButton


class SSEEventGenerator:
    """SSE 이벤트 생성기"""

    def generate_thinking_event(self, stage: str, content: str, progress: int) -> str:
        """thinking 단계 이벤트 생성"""
        data = {
            "stage": stage,
            "content": content,
            "progress": progress,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        return f"event: parallel_processing\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def generate_detail_buttons_start_event(self, buttons_count: int = 3) -> str:
        """상세페이지 버튼 준비 시작 이벤트"""
        data = {
            "type": "start",
            "buttonsCount": buttons_count,
            "estimatedPreparationTime": 5000,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "processingInfo": {
                "context7_enabled": True,
                "fallback_available": True,
                "cache_checked": True,
            },
        }
        return f"event: detail_buttons_start\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

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

            yield f"event: detail_button_ready\ndata: {json.dumps(button_data, ensure_ascii=False)}\n\n"

            # 버튼 간 간격 (UX 개선)
            await asyncio.sleep(0.1)

        # 모든 버튼 준비 완료
        complete_data = {
            "type": "complete",
            "totalPreparationTime": detail_info.processing_time_ms,
            "buttonsGenerated": len(detail_info.detail_buttons),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "summary": {
                "hscode_detected": detail_info.hscode,
                "confidence_score": detail_info.confidence_score,
                "analysis_source": detail_info.analysis_source,
                "fallback_used": detail_info.analysis_source != "context7",
                "cache_hit": detail_info.analysis_source == "cache",
            },
            "performance": {
                "context7_calls": (
                    detail_info.context7_metadata.get("api_calls", 0)
                    if detail_info.context7_metadata
                    else 0
                ),
                "context7_latency_ms": (
                    detail_info.processing_time_ms
                    if detail_info.analysis_source == "context7"
                    else 0
                ),
                "database_queries": 0,  # 현재는 사용하지 않음
                "total_processing_time": detail_info.processing_time_ms,
            },
        }
        yield f"event: detail_buttons_complete\ndata: {json.dumps(complete_data, ensure_ascii=False)}\n\n"

    def generate_detail_buttons_timeout_event(self) -> str:
        """상세페이지 버튼 준비 타임아웃 이벤트"""
        data = {
            "type": "timeout",
            "errorCode": "DETAIL_PAGE_TIMEOUT",
            "errorMessage": "상세페이지 정보 준비 시간 초과",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "fallbackActivated": True,
            "retryInfo": {"retryable": True, "retryAfter": 30, "maxRetries": 3},
        }
        return f"event: detail_buttons_error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

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
            "timestamp": datetime.utcnow().isoformat() + "Z",
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
        return f"event: detail_buttons_error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _get_button_description(self, button_type: str) -> str:
        """버튼 타입별 설명 반환"""
        descriptions = {
            "HS_CODE": "관세율, 규제정보 등 상세 조회",
            "REGULATION": "수출입 규제, 허가사항 등",
            "STATISTICS": "수출입 현황, 트렌드 분석",
        }
        return descriptions.get(button_type, "상세 정보 조회")
