import asyncio
import logging
from typing import AsyncGenerator, Optional
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import BackgroundTasks

from app.models.chat_models import ChatRequest
from app.models.schemas import DetailPageInfo
from app.services.detail_page_service import DetailPageService
from app.services.sse_event_generator import SSEEventGenerator

logger = logging.getLogger(__name__)


@dataclass
class ParallelTaskResults:
    """병렬 작업 결과"""

    detail_page_info: Optional[DetailPageInfo]
    chat_saved: bool
    processing_times: dict


class ParallelTaskManager:
    """3단계 병렬 처리 매니저"""

    def __init__(self):
        self.detail_page_service = DetailPageService()
        self.sse_generator = SSEEventGenerator()

    async def execute_parallel_tasks(
        self,
        chat_request: ChatRequest,
        db: AsyncSession,
        background_tasks: BackgroundTasks,
    ) -> AsyncGenerator[str, None]:
        """3단계 병렬 처리 실행"""

        # 즉시 병렬 처리 시작 이벤트 전송
        yield self.sse_generator.generate_thinking_event(
            "parallel_processing_start",
            "3단계 병렬 처리를 시작합니다: 자연어 응답, 상세페이지 준비, 회원 기록 저장",
            15,
        )

        # 상세페이지 버튼 준비 시작 이벤트 (웹 검색 수행 포함)
        yield self.sse_generator.generate_detail_buttons_start_event(3)

        # 작업 B: 상세페이지 정보 준비를 백그라운드에서 실행 (실제 웹 검색 포함)
        detail_page_task = asyncio.create_task(
            self._execute_detail_page_preparation(chat_request, db)
        )

        # 작업 C: 채팅 저장을 백그라운드에서 실행 (시뮬레이션)
        chat_save_task = asyncio.create_task(
            self._execute_chat_saving(chat_request, db)
        )

        # 상세페이지 작업 완료를 기다리며 이벤트 생성
        try:
            detail_info = await asyncio.wait_for(detail_page_task, timeout=10.0)

            # 상세페이지 버튼 준비 완료 이벤트들 생성
            async for event in self.sse_generator.generate_detail_button_events(
                detail_info
            ):
                yield event

        except asyncio.TimeoutError:
            logger.warning("상세페이지 정보 준비 타임아웃")
            yield self.sse_generator.generate_detail_buttons_timeout_event()

        except Exception as e:
            logger.error(f"상세페이지 정보 준비 중 오류: {e}")
            yield self.sse_generator.generate_detail_buttons_error_event(
                "DETAIL_PAGE_ERROR",
                f"상세페이지 정보 준비 중 오류가 발생했습니다: {str(e)}",
            )

        # 채팅 저장 작업 완료 확인 (시뮬레이션)
        try:
            await asyncio.wait_for(chat_save_task, timeout=5.0)
            logger.info("채팅 저장 작업 완료")
        except asyncio.TimeoutError:
            logger.warning("채팅 저장 타임아웃")
        except Exception as e:
            logger.error(f"채팅 저장 중 오류: {e}")

    async def _execute_detail_page_preparation(
        self, chat_request: ChatRequest, db: AsyncSession
    ) -> DetailPageInfo:
        """작업 B: 상세페이지 정보 준비"""
        try:
            detail_info = await self.detail_page_service.prepare_detail_page_info(
                chat_request.message,  # ChatRequest에서는 message 필드 사용
                chat_request.session_uuid or "",
                chat_request.user_id,
                db,  # DB 세션 전달
            )
            logger.info(f"상세페이지 정보 준비 완료: {detail_info.analysis_source}")
            return detail_info

        except Exception as e:
            logger.error(f"상세페이지 정보 준비 실패: {e}")
            # 폴백 정보 반환
            return self._create_fallback_detail_info()

    async def _execute_chat_saving(
        self, chat_request: ChatRequest, db: AsyncSession
    ) -> bool:
        """작업 C: 채팅 저장 (시뮬레이션)"""
        try:
            # 실제로는 여기서 데이터베이스에 채팅 저장
            await asyncio.sleep(0.5)  # 데이터베이스 작업 시뮬레이션
            logger.info("채팅 저장 작업 완료")
            return True

        except Exception as e:
            logger.error(f"채팅 저장 실패: {e}")
            return False

    def _create_fallback_detail_info(self) -> DetailPageInfo:
        """폴백 상세페이지 정보 생성"""
        from app.models.schemas import DetailButton

        return DetailPageInfo(
            detected_intent="general_chat",
            detail_buttons=[],
            processing_time_ms=0,
            confidence_score=0.1,
            analysis_source="fallback",
        )
