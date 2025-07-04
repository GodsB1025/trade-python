#!/usr/bin/env python3
"""
스웨거 문서 자동 추출 및 변환 스크립트
FastAPI 애플리케이션의 OpenAPI 스키마를 마크다운 문서로 변환
"""
from app.core.config import settings
from app.main import app
import json
import asyncio
import sys
from pathlib import Path
from typing import Dict, Any
import httpx
from datetime import datetime

# 프로젝트 루트를 Python 경로에 추가
sys.path.append(str(Path(__file__).parent))


class SwaggerDocGenerator:
    """스웨거 문서 생성기"""

    def __init__(self):
        self.base_url = f"http://{settings.SERVER_HOST}:{settings.SERVER_PORT}"
        self.api_prefix = settings.API_V1_STR

    def get_openapi_schema(self) -> Dict[str, Any]:
        """FastAPI 앱에서 직접 OpenAPI 스키마 가져옴"""
        return app.openapi()

    async def get_openapi_from_server(self) -> Dict[str, Any]:
        """실행 중인 서버에서 OpenAPI 스키마 가져옴"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}{self.api_prefix}/openapi.json")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"서버에서 스키마를 가져올 수 없음: {e}")
            print("앱에서 직접 스키마를 가져옴...")
            return self.get_openapi_schema()

    def convert_to_markdown(self, schema: Dict[str, Any]) -> str:
        """OpenAPI 스키마를 마크다운으로 변환"""
        md_content = []

        # 헤더
        md_content.append(
            f"# {schema.get('info', {}).get('title', '스웨거 API 문서')}")
        md_content.append(
            f"**생성일**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        md_content.append("")

        # 정보 섹션
        info = schema.get('info', {})
        if info.get('description'):
            md_content.append(f"## 설명")
            md_content.append(info['description'])
            md_content.append("")

        if info.get('version'):
            md_content.append(f"**버전**: {info['version']}")
            md_content.append("")

        # 서버 정보
        servers = schema.get('servers', [])
        if servers:
            md_content.append("## 서버")
            for server in servers:
                url = server.get('url', '')
                description = server.get('description', '')
                md_content.append(f"- **URL**: `{url}`")
                if description:
                    md_content.append(f"  - {description}")
            md_content.append("")

        # 엔드포인트 섹션
        paths = schema.get('paths', {})
        if paths:
            md_content.append("## API 엔드포인트")
            md_content.append("")

            # 태그별로 정리
            tags_endpoints = {}

            for path, methods in paths.items():
                for method, details in methods.items():
                    if method in ['get', 'post', 'put', 'delete', 'patch']:
                        tags = details.get('tags', ['기타'])
                        for tag in tags:
                            if tag not in tags_endpoints:
                                tags_endpoints[tag] = []
                            tags_endpoints[tag].append({
                                'path': path,
                                'method': method.upper(),
                                'details': details
                            })

            # 태그별로 출력
            for tag, endpoints in tags_endpoints.items():
                md_content.append(f"### {tag}")
                md_content.append("")

                for endpoint in endpoints:
                    path = endpoint['path']
                    method = endpoint['method']
                    details = endpoint['details']

                    summary = details.get('summary', path)
                    description = details.get('description', '')

                    md_content.append(f"#### `{method} {path}`")
                    md_content.append(f"**요약**: {summary}")

                    if description:
                        md_content.append(f"**설명**: {description}")

                    # 파라미터
                    parameters = details.get('parameters', [])
                    if parameters:
                        md_content.append("**파라미터**:")
                        for param in parameters:
                            name = param.get('name', '')
                            param_in = param.get('in', '')
                            required = " (필수)" if param.get(
                                'required', False) else " (선택)"
                            param_type = param.get(
                                'schema', {}).get('type', 'string')
                            param_desc = param.get('description', '')

                            md_content.append(
                                f"- `{name}` ({param_in}){required}: {param_type}")
                            if param_desc:
                                md_content.append(f"  - {param_desc}")

                    # 요청 본문
                    request_body = details.get('requestBody', {})
                    if request_body:
                        md_content.append("**요청 본문**:")
                        content = request_body.get('content', {})
                        for content_type, content_details in content.items():
                            md_content.append(
                                f"- Content-Type: `{content_type}`")
                            schema_ref = content_details.get('schema', {})
                            if '$ref' in schema_ref:
                                ref_name = schema_ref['$ref'].split('/')[-1]
                                md_content.append(f"  - 스키마: `{ref_name}`")

                    # 응답
                    responses = details.get('responses', {})
                    if responses:
                        md_content.append("**응답**:")
                        for status_code, response_details in responses.items():
                            description = response_details.get(
                                'description', '')
                            md_content.append(
                                f"- `{status_code}`: {description}")

                            content = response_details.get('content', {})
                            for content_type, content_details in content.items():
                                md_content.append(
                                    f"  - Content-Type: `{content_type}`")
                                schema_ref = content_details.get('schema', {})
                                if '$ref' in schema_ref:
                                    ref_name = schema_ref['$ref'].split(
                                        '/')[-1]
                                    md_content.append(
                                        f"    - 스키마: `{ref_name}`")

                    md_content.append("")

                md_content.append("---")
                md_content.append("")

        # 스키마 정의
        components = schema.get('components', {})
        schemas = components.get('schemas', {})
        if schemas:
            md_content.append("## 데이터 스키마")
            md_content.append("")

            for schema_name, schema_details in schemas.items():
                md_content.append(f"### {schema_name}")

                schema_type = schema_details.get('type', '')
                if schema_type:
                    md_content.append(f"**타입**: {schema_type}")

                description = schema_details.get('description', '')
                if description:
                    md_content.append(f"**설명**: {description}")

                properties = schema_details.get('properties', {})
                if properties:
                    md_content.append("**속성**:")
                    required_fields = schema_details.get('required', [])

                    for prop_name, prop_details in properties.items():
                        prop_type = prop_details.get('type', 'string')
                        prop_desc = prop_details.get('description', '')
                        is_required = " (필수)" if prop_name in required_fields else " (선택)"

                        md_content.append(
                            f"- `{prop_name}`{is_required}: {prop_type}")
                        if prop_desc:
                            md_content.append(f"  - {prop_desc}")

                md_content.append("")

        return "\n".join(md_content)

    def save_json_schema(self, schema: Dict[str, Any], filename: str = "swagger_schema.json"):
        """JSON 스키마를 파일로 저장"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        print(f"JSON 스키마 저장됨: {filename}")

    def save_markdown_docs(self, content: str, filename: str = "swagger_docs.md"):
        """마크다운 문서를 파일로 저장"""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"마크다운 문서 저장됨: {filename}")

    async def generate_docs(self, from_server: bool = False):
        """스웨거 문서 생성 메인 함수"""
        print("스웨거 문서 생성 시작...")

        # OpenAPI 스키마 가져오기
        if from_server:
            schema = await self.get_openapi_from_server()
        else:
            schema = self.get_openapi_schema()

        # JSON 파일로 저장
        self.save_json_schema(schema, "docs/swagger_schema.json")

        # 마크다운으로 변환하여 저장
        markdown_content = self.convert_to_markdown(schema)
        self.save_markdown_docs(markdown_content, "docs/swagger_docs.md")

        print("스웨거 문서 생성 완료!")


async def main():
    """메인 실행 함수"""
    generator = SwaggerDocGenerator()

    # docs 디렉토리 생성
    Path("docs").mkdir(exist_ok=True)

    # 명령행 인수에 따라 서버에서 가져올지 결정
    from_server = len(sys.argv) > 1 and sys.argv[1] == "--from-server"

    if from_server:
        print("실행 중인 서버에서 스키마를 가져옵니다...")
        print(f"서버 주소: http://{settings.SERVER_HOST}:{settings.SERVER_PORT}")
        print("서버가 실행 중인지 확인하세요!")

    await generator.generate_docs(from_server=from_server)


if __name__ == "__main__":
    asyncio.run(main())
