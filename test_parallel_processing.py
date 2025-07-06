#!/usr/bin/env python3
"""
병렬 처리 기능 테스트 스크립트
"""
import asyncio
import json
from app.services.detail_page_service import DetailPageService
from app.services.sse_event_generator import SSEEventGenerator
from app.services.parallel_task_manager import ParallelTaskManager
from app.models.chat_models import ChatRequest


async def test_detail_page_service():
    """DetailPageService 기능 테스트"""
    print("=== DetailPageService 테스트 ===")

    service = DetailPageService()

    # 테스트 케이스 1: HSCode 관련 질문
    test_message = "8517.12.00 HSCode에 대한 관세율과 규제 정보를 알려주세요"

    detail_info = await service.prepare_detail_page_info(
        test_message, "test-session-123", user_id=None
    )

    print(f"분석 소스: {detail_info.analysis_source}")
    print(f"신뢰도: {detail_info.confidence_score}")
    print(f"처리 시간: {detail_info.processing_time_ms}ms")
    print(f"버튼 수: {len(detail_info.detail_buttons)}")

    for button in detail_info.detail_buttons:
        print(f"- {button.label} ({button.type})")

    print()


async def test_sse_event_generator():
    """SSEEventGenerator 기능 테스트"""
    print("=== SSEEventGenerator 테스트 ===")

    generator = SSEEventGenerator()

    # 테스트 DetailPageInfo 생성
    from app.models.schemas import DetailPageInfo, DetailButton

    test_info = DetailPageInfo(
        hscode="8517.12.00",
        detected_intent="hscode_search",
        detail_buttons=[
            DetailButton(
                type="HS_CODE",
                label="HS Code 상세정보",
                url="/detail/hscode",
                query_params={"hscode": "8517.12.00"},
                priority=1,
            )
        ],
        processing_time_ms=1500,
        confidence_score=0.85,
        analysis_source="context7",
    )

    # 시작 이벤트 생성
    start_event = generator.generate_detail_buttons_start_event(1)
    print("시작 이벤트:")
    print(start_event)

    # 버튼 이벤트들 생성
    print("버튼 이벤트들:")
    async for event in generator.generate_detail_button_events(test_info):
        print(event)

    print()


async def test_parallel_task_manager():
    """ParallelTaskManager 기능 테스트"""
    print("=== ParallelTaskManager 테스트 ===")

    manager = ParallelTaskManager()

    # 테스트 ChatRequest 생성
    chat_request = ChatRequest(
        user_id=None,
        session_uuid="test-session-456",
        message="8517.12.00 HSCode에 대한 수출입 규제 정보를 알려주세요",
    )

    # 병렬 처리 실행 (실제 DB 없이 테스트)
    print("병렬 처리 이벤트들:")
    try:
        # 실제 DB 세션 없이는 테스트 불가능하므로 직접 DetailPageService만 테스트
        detail_info = await manager.detail_page_service.prepare_detail_page_info(
            chat_request.message, chat_request.session_uuid, chat_request.user_id
        )

        print(f"  - 상세페이지 정보 준비 완료")
        print(f"  - 분석 소스: {detail_info.analysis_source}")
        print(f"  - 신뢰도: {detail_info.confidence_score}")
        print(f"  - 버튼 수: {len(detail_info.detail_buttons)}")

        # SSE 이벤트 생성 테스트
        async for event in manager.sse_generator.generate_detail_button_events(
            detail_info
        ):
            print(f"  - 이벤트 생성: {event.split('data:')[0].strip()}")

    except Exception as e:
        print(f"병렬 처리 테스트 중 오류 (예상됨): {e}")

    print()


async def test_context7_integration():
    """Context7 통합 테스트"""
    print("=== Context7 통합 테스트 ===")

    service = DetailPageService()

    # 다양한 테스트 케이스
    test_cases = [
        "8517.12.00 HSCode 관련 정보",
        "휴대폰 수출할 때 필요한 서류는?",
        "FTA 활용 방법",
        "일반적인 인사말",
    ]

    for test_case in test_cases:
        print(f"테스트 케이스: {test_case}")

        detail_info = await service.prepare_detail_page_info(
            test_case, "test-session", user_id=None
        )

        print(f"  - 의도: {detail_info.detected_intent}")
        print(f"  - 신뢰도: {detail_info.confidence_score}")
        print(f"  - 소스: {detail_info.analysis_source}")
        print(f"  - 버튼 수: {len(detail_info.detail_buttons)}")
        print()


async def main():
    """메인 테스트 실행"""
    print("병렬 처리 기능 테스트 시작")
    print("=" * 50)

    await test_detail_page_service()
    await test_sse_event_generator()
    await test_parallel_task_manager()
    await test_context7_integration()

    print("=" * 50)
    print("모든 테스트 완료")


if __name__ == "__main__":
    asyncio.run(main())
