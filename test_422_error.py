#!/usr/bin/env python3
"""
422 에러 발생 원인을 테스트하는 스크립트
다양한 잘못된 요청을 보내서 어떤 에러가 발생하는지 확인
"""

import requests
import json
import time

# 서버 URL
BASE_URL = "http://127.0.0.1:8000"
CHAT_URL = f"{BASE_URL}/api/v1/chat"


def test_request(test_name: str, data: dict, expected_status: int = 422):
    """
    테스트 요청을 보내고 결과를 출력
    """
    print(f"\n=== {test_name} ===")
    print(f"요청 데이터: {json.dumps(data, ensure_ascii=False, indent=2)}")

    try:
        response = requests.post(
            CHAT_URL, json=data, headers={"Content-Type": "application/json"}, timeout=5
        )

        print(f"응답 상태 코드: {response.status_code}")
        print(f"응답 헤더: {dict(response.headers)}")

        if response.status_code != 200:
            print(f"응답 본문: {response.text}")

        if response.status_code == expected_status:
            print("✅ 예상대로 에러 발생")
        else:
            print("❌ 예상과 다른 응답")

    except requests.exceptions.RequestException as e:
        print(f"요청 실패: {e}")

    print("-" * 50)


def main():
    """
    다양한 테스트 케이스 실행
    """
    print("422 에러 테스트 시작...")

    # 1. 정상 요청 (200 응답 기대)
    test_request(
        "정상 요청",
        {"user_id": 123, "session_uuid": "test-session-uuid", "message": "안녕하세요"},
        expected_status=200,
    )

    # 2. message 필드 누락
    test_request(
        "message 필드 누락", {"user_id": 123, "session_uuid": "test-session-uuid"}
    )

    # 3. message 필드가 빈 문자열
    test_request(
        "message 필드가 빈 문자열",
        {"user_id": 123, "session_uuid": "test-session-uuid", "message": ""},
    )

    # 4. message 필드가 null
    test_request(
        "message 필드가 null",
        {"user_id": 123, "session_uuid": "test-session-uuid", "message": None},
    )

    # 5. message 필드가 숫자
    test_request(
        "message 필드가 숫자",
        {"user_id": 123, "session_uuid": "test-session-uuid", "message": 12345},
    )

    # 6. user_id가 문자열
    test_request(
        "user_id가 문자열",
        {
            "user_id": "not-a-number",
            "session_uuid": "test-session-uuid",
            "message": "안녕하세요",
        },
    )

    # 7. message가 너무 긴 경우 (5000자 초과)
    long_message = "a" * 5001
    test_request(
        "message가 5000자 초과",
        {"user_id": 123, "session_uuid": "test-session-uuid", "message": long_message},
    )

    # 8. 잘못된 JSON 형식 (별도 테스트)
    print("\n=== 잘못된 JSON 형식 테스트 ===")
    try:
        response = requests.post(
            CHAT_URL,
            data='{"user_id": 123, "message": "안녕하세요", invalid_json}',
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        print(f"응답 상태 코드: {response.status_code}")
        print(f"응답 본문: {response.text}")
    except Exception as e:
        print(f"요청 실패: {e}")

    # 9. Content-Type 헤더 누락
    print("\n=== Content-Type 헤더 누락 테스트 ===")
    try:
        response = requests.post(CHAT_URL, json={"message": "안녕하세요"}, timeout=5)
        print(f"응답 상태 코드: {response.status_code}")
        print(f"응답 본문: {response.text}")
    except Exception as e:
        print(f"요청 실패: {e}")


if __name__ == "__main__":
    main()
