#!/usr/bin/env python3
"""
스웨거 JSON을 마크다운으로 변환하는 스크립트
OpenAPI JSON 스키마를 읽기 좋은 마크다운 문서로 변환
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any


class SwaggerMarkdownConverter:
    """스웨거 JSON을 마크다운으로 변환하는 클래스"""

    def __init__(self, json_file: str = "docs/swagger_schema.json"):
        self.json_file = Path(json_file)
        self.schema = self.load_schema()

    def load_schema(self) -> Dict[str, Any]:
        """JSON 스키마 파일 로드"""
        if not self.json_file.exists():
            raise FileNotFoundError(f"스키마 파일을 찾을 수 없음: {self.json_file}")

        with open(self.json_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def convert_to_markdown(self) -> str:
        """OpenAPI 스키마를 마크다운으로 변환"""
        md_content = []

        # 헤더
        info = self.schema.get('info', {})
        title = info.get('title', '스웨거 API 문서')
        md_content.append(f"# {title}")
        md_content.append(
            f"**생성일**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        md_content.append("")

        # 목차
        md_content.append("## 목차")
        md_content.append("- [API 정보](#api-정보)")
        md_content.append("- [엔드포인트](#엔드포인트)")
        md_content.append("- [데이터 스키마](#데이터-스키마)")
        md_content.append("")

        # API 정보 섹션
        md_content.extend(self._generate_info_section())

        # 엔드포인트 섹션
        md_content.extend(self._generate_endpoints_section())

        # 스키마 섹션
        md_content.extend(self._generate_schemas_section())

        return "\n".join(md_content)

    def _generate_info_section(self) -> list:
        """API 정보 섹션 생성"""
        content = []
        info = self.schema.get('info', {})

        content.append("## API 정보")
        content.append("")

        if info.get('description'):
            content.append(f"**설명**: {info['description']}")
            content.append("")

        if info.get('version'):
            content.append(f"**버전**: {info['version']}")
            content.append("")

        # 서버 정보
        servers = self.schema.get('servers', [])
        if servers:
            content.append("### 서버")
            for server in servers:
                url = server.get('url', '')
                description = server.get('description', '')
                content.append(f"- **URL**: `{url}`")
                if description:
                    content.append(f"  - {description}")
            content.append("")

        return content

    def _generate_endpoints_section(self) -> list:
        """엔드포인트 섹션 생성"""
        content = []
        content.append("## 엔드포인트")
        content.append("")

        paths = self.schema.get('paths', {})
        if not paths:
            content.append("엔드포인트가 없습니다.")
            content.append("")
            return content

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
            content.append(f"### {tag}")
            content.append("")

            for endpoint in endpoints:
                content.extend(self._generate_endpoint_details(endpoint))

            content.append("---")
            content.append("")

        return content

    def _generate_endpoint_details(self, endpoint: Dict[str, Any]) -> list:
        """개별 엔드포인트 상세 정보 생성"""
        content = []
        path = endpoint['path']
        method = endpoint['method']
        details = endpoint['details']

        summary = details.get('summary', path)
        description = details.get('description', '')

        content.append(f"#### `{method} {path}`")
        content.append("")
        content.append(f"**요약**: {summary}")
        content.append("")

        if description:
            content.append(f"**설명**: {description}")
            content.append("")

        # 파라미터
        parameters = details.get('parameters', [])
        if parameters:
            content.append("**파라미터**:")
            content.append("")
            content.append("| 이름 | 위치 | 타입 | 필수 | 설명 |")
            content.append("|------|------|------|------|------|")

            for param in parameters:
                name = param.get('name', '')
                param_in = param.get('in', '')
                required = "✓" if param.get('required', False) else ""
                param_type = param.get('schema', {}).get('type', 'string')
                param_desc = param.get('description', '')

                content.append(
                    f"| `{name}` | {param_in} | {param_type} | {required} | {param_desc} |")

            content.append("")

        # 요청 본문
        request_body = details.get('requestBody', {})
        if request_body:
            content.append("**요청 본문**:")
            content.append("")

            if request_body.get('description'):
                content.append(f"*{request_body['description']}*")
                content.append("")

            content_types = request_body.get('content', {})
            for content_type, content_details in content_types.items():
                content.append(f"- **Content-Type**: `{content_type}`")
                schema_ref = content_details.get('schema', {})
                if '$ref' in schema_ref:
                    ref_name = schema_ref['$ref'].split('/')[-1]
                    content.append(
                        f"  - **스키마**: [`{ref_name}`](#datatype-{ref_name.lower()})")
                elif 'type' in schema_ref:
                    content.append(f"  - **타입**: `{schema_ref['type']}`")
            content.append("")

        # 응답
        responses = details.get('responses', {})
        if responses:
            content.append("**응답**:")
            content.append("")
            content.append("| 상태 코드 | 설명 | Content-Type | 스키마 |")
            content.append("|-----------|------|--------------|--------|")

            for status_code, response_details in responses.items():
                description = response_details.get('description', '')

                response_content = response_details.get('content', {})
                if response_content:
                    for content_type, content_details in response_content.items():
                        schema_ref = content_details.get('schema', {})
                        schema_info = ""
                        if '$ref' in schema_ref:
                            ref_name = schema_ref['$ref'].split('/')[-1]
                            schema_info = f"[`{ref_name}`](#datatype-{ref_name.lower()})"
                        elif 'type' in schema_ref:
                            schema_info = f"`{schema_ref['type']}`"

                        content.append(
                            f"| `{status_code}` | {description} | `{content_type}` | {schema_info} |")
                else:
                    content.append(
                        f"| `{status_code}` | {description} | - | - |")

            content.append("")

        return content

    def _generate_schemas_section(self) -> list:
        """데이터 스키마 섹션 생성"""
        content = []
        content.append("## 데이터 스키마")
        content.append("")

        components = self.schema.get('components', {})
        schemas = components.get('schemas', {})

        if not schemas:
            content.append("데이터 스키마가 없습니다.")
            content.append("")
            return content

        for schema_name, schema_details in schemas.items():
            content.append(
                f"### <a id=\"datatype-{schema_name.lower()}\"></a>{schema_name}")
            content.append("")

            schema_type = schema_details.get('type', '')
            if schema_type:
                content.append(f"**타입**: `{schema_type}`")
                content.append("")

            description = schema_details.get('description', '')
            if description:
                content.append(f"**설명**: {description}")
                content.append("")

            # Enum 값들
            enum_values = schema_details.get('enum', [])
            if enum_values:
                content.append("**가능한 값**:")
                for value in enum_values:
                    content.append(f"- `{value}`")
                content.append("")

            # 속성들
            properties = schema_details.get('properties', {})
            if properties:
                content.append("**속성**:")
                content.append("")
                content.append("| 속성명 | 타입 | 필수 | 설명 |")
                content.append("|--------|------|------|------|")

                required_fields = schema_details.get('required', [])

                for prop_name, prop_details in properties.items():
                    prop_type = prop_details.get('type', 'string')

                    # 참조 타입인 경우
                    if '$ref' in prop_details:
                        ref_name = prop_details['$ref'].split('/')[-1]
                        prop_type = f"[`{ref_name}`](#datatype-{ref_name.lower()})"
                    elif 'items' in prop_details and '$ref' in prop_details['items']:
                        ref_name = prop_details['items']['$ref'].split('/')[-1]
                        prop_type = f"Array of [`{ref_name}`](#datatype-{ref_name.lower()})"
                    elif 'items' in prop_details:
                        item_type = prop_details['items'].get('type', 'string')
                        prop_type = f"Array of `{item_type}`"

                    prop_desc = prop_details.get('description', '')
                    is_required = "✓" if prop_name in required_fields else ""

                    content.append(
                        f"| `{prop_name}` | {prop_type} | {is_required} | {prop_desc} |")

                content.append("")

            # anyOf, oneOf 등의 복합 타입
            if 'anyOf' in schema_details:
                content.append("**다음 중 하나**:")
                for i, sub_schema in enumerate(schema_details['anyOf']):
                    if '$ref' in sub_schema:
                        ref_name = sub_schema['$ref'].split('/')[-1]
                        content.append(
                            f"{i+1}. [`{ref_name}`](#datatype-{ref_name.lower()})")
                    else:
                        content.append(
                            f"{i+1}. `{sub_schema.get('type', 'unknown')}`")
                content.append("")

        return content

    def save_markdown(self, output_file: str = "docs/swagger_documentation.md"):
        """마크다운 파일로 저장"""
        markdown_content = self.convert_to_markdown()

        output_path = Path(output_file)
        output_path.parent.mkdir(exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        print(f"✅ 마크다운 문서 생성됨: {output_path.absolute()}")
        return output_path


def main():
    """메인 실행 함수"""
    try:
        converter = SwaggerMarkdownConverter()
        output_file = converter.save_markdown()

        print("\n=== 생성된 문서 ===")
        print(f"📁 JSON 스키마: {converter.json_file.absolute()}")
        print(f"📄 마크다운 문서: {output_file.absolute()}")

        print("\n=== 사용 방법 ===")
        print("1. JSON 파일을 다른 도구로 import")
        print("2. 마크다운 파일을 문서로 사용")
        print("3. 스웨거 UI에서 JSON 파일 로드")

    except FileNotFoundError as e:
        print(f"❌ {e}")
        print("먼저 simple_swagger_extractor.py를 실행하여 JSON 스키마를 생성하세요.")
    except Exception as e:
        print(f"❌ 에러 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
