#!/usr/bin/env python3
"""
간단한 스웨거 문서 추출기
최소한의 의존성으로 OpenAPI 스키마를 JSON 형태로 추출
"""
import json
import sys
import os
import asyncio
from pathlib import Path

# Windows에서 psycopg 호환성을 위한 이벤트 루프 정책 설정
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

try:
    # 의존성 체크
    print("의존성 체크 중...")

    from app.main import app
    print("✅ FastAPI 앱 로드 성공")

    # OpenAPI 스키마 추출
    print("OpenAPI 스키마 추출 중...")
    schema = app.openapi()

    # docs 디렉토리 생성
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)

    # JSON 파일로 저장
    json_file = docs_dir / "swagger_schema.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)

    print(f"✅ JSON 스키마 저장됨: {json_file}")

    # 기본 정보 출력
    print("\n=== API 정보 ===")
    info = schema.get('info', {})
    print(f"제목: {info.get('title', 'N/A')}")
    print(f"버전: {info.get('version', 'N/A')}")

    # 엔드포인트 목록 출력
    paths = schema.get('paths', {})
    print(f"\n=== 엔드포인트 ({len(paths)}개) ===")
    for path, methods in paths.items():
        for method in methods.keys():
            if method in ['get', 'post', 'put', 'delete', 'patch']:
                method_info = methods[method]
                summary = method_info.get('summary', '설명 없음')
                tags = ', '.join(method_info.get('tags', []))
                print(f"{method.upper():6} {path:30} [{tags}] {summary}")

    # 스키마 목록 출력
    components = schema.get('components', {})
    schemas = components.get('schemas', {})
    print(f"\n=== 데이터 스키마 ({len(schemas)}개) ===")
    for schema_name in schemas.keys():
        print(f"- {schema_name}")

    print(f"\n✅ 스웨거 문서 추출 완료!")
    print(f"📁 JSON 파일: {json_file.absolute()}")

except ImportError as e:
    print(f"❌ 임포트 에러: {e}")
    print("의존성 설치가 필요할 수 있습니다.")
except Exception as e:
    print(f"❌ 에러 발생: {e}")
    import traceback
    traceback.print_exc()
