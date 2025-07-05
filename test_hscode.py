#!/usr/bin/env python3
"""
HSCode 검색 기능 테스트 스크립트
"""

import asyncio
import json
from typing import Dict, Any, List

import httpx


async def test_hscode_search(query: str, user_id: int = 1) -> List[Dict[str, Any]]:
    """HSCode 검색 API 테스트"""

    url = "http://localhost:8000/api/v1/chat"

    payload = {"message": query, "user_id": user_id}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )

        if response.status_code != 200:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            return []

        # SSE 스트림 파싱
        results = []
        for line in response.text.strip().split("\n"):
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    results.append(data)
                except json.JSONDecodeError:
                    continue

        return results


async def main():
    """메인 테스트 함수"""

    print("🚀 HSCode 검색 기능 테스트 시작\n")

    # 테스트 케이스 1: 정상적인 HSCode 검색
    print("=" * 50)
    print("테스트 1: 냉동 양념 족발 HSCode 검색")
    print("=" * 50)

    results = await test_hscode_search("냉동 양념 족발의 HSCode를 알려줘")

    for result in results:
        if result.get("type") == "hscode_result":
            data = result.get("data", {})
            print(f"\n✅ 성공: {data.get('success')}")
            print(f"쿼리 타입: {data.get('query_type')}")
            print(f"추가 정보 필요: {data.get('needs_more_info')}")

            if data.get("results"):
                print("\n📋 검색 결과:")
                for r in data.get("results", []):
                    print(f"  - {r['country_name']} ({r['country']}): {r['hscode']}")
                    print(f"    설명: {r['description']}")
                    print(f"    신뢰도: {r['confidence']}")

            if data.get("message"):
                print(f"\n💬 메시지: {data['message']}")

    # 테스트 케이스 2: 정보 부족한 경우
    print("\n" + "=" * 50)
    print("테스트 2: 정보가 부족한 경우")
    print("=" * 50)

    results = await test_hscode_search("고기의 HSCode 알려줘")

    for result in results:
        if result.get("type") == "hscode_result":
            data = result.get("data", {})
            if data.get("needs_more_info"):
                print(f"\n⚠️  추가 정보 필요!")
                print(f"부족한 정보: {', '.join(data.get('missing_info', []))}")
                print(f"메시지: {data.get('message')}")

    # 테스트 케이스 3: 일반 채팅 (HSCode 아님)
    print("\n" + "=" * 50)
    print("테스트 3: 일반 채팅 (HSCode 아님)")
    print("=" * 50)

    results = await test_hscode_search("안녕하세요, 오늘 날씨가 어떤가요?")

    for result in results:
        if result.get("type") == "token":
            print(
                "💬 일반 채팅 응답:", result.get("data", {}).get("content", ""), end=""
            )
        elif result.get("type") == "finish":
            print("\n✅ 스트림 종료")


if __name__ == "__main__":
    print(
        """
    ⚠️  실행 전 확인사항:
    1. .env 파일에 필요한 API 키가 설정되어 있는지 확인
       - ANTHROPIC_API_KEY
       - VOYAGE_API_KEY
       - TAVILY_API_KEY
    
    2. PostgreSQL이 실행 중이고 pgvector 확장이 설치되어 있는지 확인
    
    3. FastAPI 서버가 실행 중인지 확인 (python main.py)
    """
    )

    input("계속하려면 Enter를 누르세요...")

    asyncio.run(main())
