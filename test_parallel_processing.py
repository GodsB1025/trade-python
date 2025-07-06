#!/usr/bin/env python3
"""
병렬 처리 기능 테스트 스크립트
"""
import asyncio
import time
import json
from app.services.sse_event_generator import SSEEventGenerator
from app.services.parallel_task_manager import ParallelTaskManager
from app.services.detail_page_service import DetailPageService
from app.models.chat_models import ChatRequest
from app.models.schemas import DetailPageInfo, DetailButton


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
    """SSE 이벤트 생성기 테스트 (작업 A)"""
    print("=== SSE 이벤트 생성기 테스트 ===")

    generator = SSEEventGenerator()

    # 1. thinking 이벤트 테스트
    print("1. Thinking 이벤트:")
    thinking_event = generator.generate_thinking_event(
        "intent_analysis", "사용자 의도를 분석하고 있습니다...", 25
    )
    print(thinking_event)

    # 2. 버튼 시작 이벤트 테스트
    print("2. 버튼 시작 이벤트:")
    buttons_start_event = generator.generate_detail_buttons_start_event(3)
    print(buttons_start_event)

    # 3. 타임아웃 이벤트 테스트
    print("3. 타임아웃 이벤트:")
    timeout_event = generator.generate_detail_buttons_timeout_event()
    print(timeout_event)

    # 4. 에러 이벤트 테스트
    print("4. 에러 이벤트:")
    error_event = generator.generate_detail_buttons_error_event(
        "ANALYSIS_FAILED", "분석 서비스 일시 장애"
    )
    print(error_event)


async def test_parallel_task_manager():
    """병렬 작업 관리자 테스트"""
    print("=== 병렬 작업 관리자 테스트 ===")

    manager = ParallelTaskManager()

    # 모의 사용자 메시지
    user_message = "8517.12.00 HSCode에 대해 알려주세요"
    session_uuid = "test-session-uuid"
    user_id = 4

    print(f"사용자 메시지: {user_message}")
    print(f"세션 UUID: {session_uuid}")
    print(f"사용자 ID: {user_id}")

    # 상세페이지 정보 모의 객체 생성
    detail_info = DetailPageInfo(
        hscode="8517.12.00",
        detected_intent="hscode_search",
        detail_buttons=[],
        processing_time_ms=800,
        confidence_score=0.85,
        analysis_source="fallback",
    )

    print(f"분석 소스: {detail_info.analysis_source}")
    print(f"신뢰도: {detail_info.confidence_score}")
    print(f"처리 시간: {detail_info.processing_time_ms}ms")

    # 병렬 작업 실행 시뮬레이션
    print("\n--- 병렬 작업 시뮬레이션 ---")

    start_time = time.time()

    # 작업 A와 B를 병렬로 실행한다고 가정
    tasks = [
        asyncio.create_task(simulate_chat_save_task()),
        asyncio.create_task(simulate_detail_page_task()),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    end_time = time.time()
    total_time = (end_time - start_time) * 1000

    print(f"총 처리 시간: {total_time:.2f}ms")

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"  - 작업 {i+1}: 실패 ({result})")
        else:
            print(f"  - 작업 {i+1}: 성공 ({result})")


async def simulate_chat_save_task():
    """채팅 저장 작업 시뮬레이션"""
    await asyncio.sleep(0.3)  # 300ms 시뮬레이션
    return "채팅 저장 완료"


async def simulate_detail_page_task():
    """상세페이지 준비 작업 시뮬레이션"""
    await asyncio.sleep(0.5)  # 500ms 시뮬레이션
    return "상세페이지 준비 완료"


async def test_detailed_page_preparation():
    """상세페이지 정보 준비 테스트 (작업 B)"""
    print("=== 상세페이지 정보 준비 테스트 ===")

    # 모의 DetailPageInfo 객체 생성 (실제 분석 결과)
    detail_info = DetailPageInfo(
        hscode="8517.12.00",
        detected_intent="hscode_search",
        detail_buttons=[
            DetailButton(
                type="HS_CODE",
                label="HS Code 상세정보",
                url="/detail/hscode",
                query_params={"hscode": "8517.12.00"},
                priority=1,
            ),
            DetailButton(
                type="REGULATION",
                label="규제 정보",
                url="/regulation",
                query_params={"hscode": "8517.12.00"},
                priority=2,
            ),
        ],
        processing_time_ms=1500,
        confidence_score=0.95,
        analysis_source="web_search",
    )

    print(f"HSCode: {detail_info.hscode}")
    print(f"분석 소스: {detail_info.analysis_source}")
    print(f"신뢰도: {detail_info.confidence_score}")
    print(f"처리 시간: {detail_info.processing_time_ms}ms")
    print(f"버튼 수: {len(detail_info.detail_buttons)}")

    # SSE 이벤트 생성 테스트
    sse_generator = SSEEventGenerator()

    print("\n--- SSE 이벤트 생성 ---")

    # 상세페이지 버튼 시작 이벤트
    start_event = sse_generator.generate_detail_buttons_start_event(
        len(detail_info.detail_buttons)
    )
    print("시작 이벤트:")
    print(start_event)

    # 상세페이지 버튼 준비 이벤트들
    print("버튼 이벤트들:")
    async for button_event in sse_generator.generate_detail_button_events(detail_info):
        print(button_event)


async def main():
    """메인 테스트 실행"""
    print("병렬 처리 기능 테스트 시작")
    print("=" * 50)

    await test_detail_page_service()
    await test_sse_event_generator()
    await test_parallel_task_manager()
    await test_detailed_page_preparation()

    print("=" * 50)
    print("모든 테스트 완료")


if __name__ == "__main__":
    asyncio.run(main())
