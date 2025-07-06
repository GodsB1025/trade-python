#!/usr/bin/env python3
"""
요청 바디 로깅 기능을 테스트하기 위한 스크립트

이 스크립트는 다양한 유형의 요청을 서버에 전송하여 
로깅 미들웨어가 올바르게 작동하는지 확인함.
"""

import asyncio
import json
import aiohttp
from typing import Dict, Any


async def test_request_logging():
    """
    다양한 요청 시나리오를 테스트하여 로깅 기능 검증
    """
    base_url = "http://localhost:8000"

    # 테스트 케이스들
    test_cases = [
        {
            "name": "일반 JSON 요청",
            "method": "POST",
            "url": f"{base_url}/api/v1/chat/messages",
            "json_data": {"message": "안녕하세요", "user_id": 123},
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "TestClient/1.0",
            },
        },
        {
            "name": "민감한 데이터 포함 요청",
            "method": "POST",
            "url": f"{base_url}/api/v1/chat/messages",
            "json_data": {
                "message": "로그인 요청",
                "password": "secret123",
                "api_key": "sk-1234567890",
                "user_id": 456,
            },
            "headers": {
                "Content-Type": "application/json",
                "Authorization": "Bearer token123",
                "X-API-Key": "secret-key",
            },
        },
        {
            "name": "큰 요청 바디 (truncation 테스트)",
            "method": "POST",
            "url": f"{base_url}/api/v1/chat/messages",
            "json_data": {"message": "A" * 15000, "user_id": 789},  # 15KB 메시지
            "headers": {"Content-Type": "application/json"},
        },
        {
            "name": "빈 요청 바디",
            "method": "GET",
            "url": f"{base_url}/api/v1/chat/sessions",
            "headers": {"User-Agent": "TestClient/1.0"},
        },
        {
            "name": "잘못된 JSON 요청",
            "method": "POST",
            "url": f"{base_url}/api/v1/chat/messages",
            "data": "잘못된 JSON 데이터",
            "headers": {"Content-Type": "application/json"},
        },
    ]

    async with aiohttp.ClientSession() as session:
        for test_case in test_cases:
            print(f"\n=== {test_case['name']} 테스트 시작 ===")

            try:
                # 요청 준비
                kwargs = {
                    "method": test_case["method"],
                    "url": test_case["url"],
                    "headers": test_case.get("headers", {}),
                }

                # 요청 데이터 추가
                if "json_data" in test_case:
                    kwargs["json"] = test_case["json_data"]
                elif "data" in test_case:
                    kwargs["data"] = test_case["data"]

                # 요청 전송
                async with session.request(**kwargs) as response:
                    print(f"상태 코드: {response.status}")

                    # 응답 내용 읽기 (필요한 경우)
                    if response.status != 200:
                        text = await response.text()
                        print(f"응답 내용: {text[:200]}...")

            except Exception as e:
                print(f"요청 실패: {e}")

            print(f"=== {test_case['name']} 테스트 완료 ===")

            # 요청 간 간격
            await asyncio.sleep(1)


if __name__ == "__main__":
    print("요청 바디 로깅 테스트 시작")
    print("서버가 실행 중인지 확인하세요 (http://localhost:8000)")
    print("로그 파일이나 콘솔에서 로깅 결과를 확인하세요")

    try:
        asyncio.run(test_request_logging())
        print("\n모든 테스트 완료!")
        print("로그를 확인하여 요청 바디와 헤더가 올바르게 로깅되었는지 확인하세요.")
    except KeyboardInterrupt:
        print("\n테스트 중단됨")
    except Exception as e:
        print(f"테스트 중 오류 발생: {e}")
