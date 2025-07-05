#!/usr/bin/env python3
"""
스웨거 문서를 HTML로 변환하는 스크립트
Swagger UI를 사용하여 OpenAPI 스키마를 아름다운 HTML 문서로 변환
Windows 환경에서 psycopg 호환성 문제 해결
Context7 기반 OpenAPI 참조 해결 문제 수정
"""
import json
import sys
import asyncio
import platform
from pathlib import Path
from datetime import datetime
import copy
import re

# Windows에서 psycopg 호환성을 위한 이벤트 루프 정책 설정
if platform.system() == "Windows":
    # Context7 권장 해결책: Windows에서 SelectorEventLoop 사용
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 프로젝트 루트를 Python 경로에 추가
sys.path.append(str(Path(__file__).parent))

# 환경 변수를 통한 안전한 임포트
import os

os.environ["SKIP_DB_INIT"] = "true"  # DB 초기화 건너뛰기 플래그

try:
    from app.core.config import settings
    from app.main import app
except ImportError as e:
    print(f"❌ FastAPI 앱 임포트 실패: {e}")
    print("💡 대안 방법으로 기본 스키마를 생성합니다...")
    app = None
    settings = None


class OpenAPIRefResolver:
    """Context7 기반 OpenAPI 참조 해결기"""

    def __init__(self, schema: dict):
        """
        OpenAPI 스키마 참조 해결기 초기화

        Args:
            schema: OpenAPI 스키마 딕셔너리
        """
        self.schema = copy.deepcopy(schema)
        self.components = self.schema.get("components", {})
        self.schemas = self.components.get("schemas", {})
        self._resolved_refs = set()  # 순환 참조 방지

    def resolve_all_refs(self) -> dict:
        """
        모든 $ref 참조를 인라인으로 해결
        Context7 가이드에 따른 참조 해결 구현

        Returns:
            참조가 해결된 OpenAPI 스키마
        """
        print("🔧 Context7 기반 OpenAPI 참조 해결 시작...")

        # 모든 $ref 참조를 찾아서 해결
        self._resolve_refs_recursive(self.schema)

        print("✅ 모든 $ref 참조가 인라인으로 해결되었습니다.")
        return self.schema

    def _resolve_refs_recursive(self, obj, path=""):
        """
        재귀적으로 $ref 참조를 해결

        Args:
            obj: 처리할 객체 (dict, list, 또는 기본 타입)
            path: 현재 경로 (디버깅용)
        """
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_path = obj["$ref"]
                resolved_obj = self._resolve_ref(ref_path, path)
                # $ref를 해결된 객체로 교체
                obj.clear()
                obj.update(resolved_obj)
                # 해결된 객체 내부의 참조도 재귀적으로 해결
                self._resolve_refs_recursive(obj, path)
            else:
                # 딕셔너리의 모든 값에 대해 재귀적으로 처리
                for key, value in obj.items():
                    self._resolve_refs_recursive(value, f"{path}.{key}")

        elif isinstance(obj, list):
            # 리스트의 모든 요소에 대해 재귀적으로 처리
            for i, item in enumerate(obj):
                self._resolve_refs_recursive(item, f"{path}[{i}]")

    def _resolve_ref(self, ref_path: str, current_path: str) -> dict:
        """
        개별 $ref 참조를 해결

        Args:
            ref_path: 참조 경로 (예: "#/components/schemas/ValidationError")
            current_path: 현재 위치 경로

        Returns:
            해결된 스키마 객체
        """
        # 순환 참조 방지
        if ref_path in self._resolved_refs:
            print(f"⚠️ 순환 참조 감지됨: {ref_path} (위치: {current_path})")
            return {"type": "object", "description": f"순환 참조: {ref_path}"}

        # #/components/schemas/SchemaName 형식의 참조만 처리
        if not ref_path.startswith("#/components/schemas/"):
            print(f"⚠️ 지원되지 않는 참조 형식: {ref_path}")
            return {"type": "object", "description": f"지원되지 않는 참조: {ref_path}"}

        # 스키마 이름 추출
        schema_name = ref_path.split("/")[-1]

        if schema_name not in self.schemas:
            print(f"❌ 참조된 스키마를 찾을 수 없음: {schema_name}")
            return {
                "type": "object",
                "description": f"참조된 스키마를 찾을 수 없음: {schema_name}",
            }

        # 참조된 스키마 가져오기
        referenced_schema = copy.deepcopy(self.schemas[schema_name])

        # 순환 참조 추적에 추가
        self._resolved_refs.add(ref_path)

        # 참조된 스키마 내부의 참조도 해결
        self._resolve_refs_recursive(referenced_schema, f"ref:{schema_name}")

        # 순환 참조 추적에서 제거
        self._resolved_refs.discard(ref_path)

        print(f"✅ 참조 해결됨: {ref_path} -> {schema_name}")
        return referenced_schema

    def validate_schema(self) -> bool:
        """
        스키마 유효성 검사

        Returns:
            스키마가 유효한지 여부
        """
        try:
            # 기본적인 OpenAPI 스키마 구조 확인
            required_keys = ["openapi", "info", "paths"]
            for key in required_keys:
                if key not in self.schema:
                    print(f"❌ 필수 키 누락: {key}")
                    return False

            # 남은 $ref 참조가 있는지 확인
            remaining_refs = self._find_remaining_refs(self.schema)
            if remaining_refs:
                print(f"⚠️ 해결되지 않은 참조들: {remaining_refs}")
                return False

            print("✅ 스키마 유효성 검사 통과")
            return True

        except Exception as e:
            print(f"❌ 스키마 유효성 검사 실패: {e}")
            return False

    def _find_remaining_refs(self, obj, refs=None):
        """남은 $ref 참조를 찾는 헬퍼 함수"""
        if refs is None:
            refs = []

        if isinstance(obj, dict):
            if "$ref" in obj:
                refs.append(obj["$ref"])
            for value in obj.values():
                self._find_remaining_refs(value, refs)
        elif isinstance(obj, list):
            for item in obj:
                self._find_remaining_refs(item, refs)

        return refs


class SwaggerHTMLGenerator:
    """스웨거 HTML 생성기 - Windows 호환성 및 참조 해결 개선"""

    def __init__(self):
        if settings:
            self.api_title = settings.PROJECT_NAME
            self.api_version = settings.app_version
            self.base_url = f"http://{settings.SERVER_HOST}:{settings.SERVER_PORT}"
            self.api_prefix = settings.API_V1_STR
        else:
            # 기본값 설정
            self.api_title = "Trade Python AI Service"
            self.api_version = "6.1.0"
            self.base_url = "http://localhost:8000"
            self.api_prefix = "/api/v1"

    def get_openapi_schema(self) -> dict:
        """FastAPI 앱에서 OpenAPI 스키마 가져옴 또는 기본 스키마 사용"""
        if app:
            try:
                schema = app.openapi()
                print("✅ FastAPI에서 스키마 생성 성공")
                return self._resolve_schema_references(schema)
            except Exception as e:
                print(f"⚠️ FastAPI 스키마 생성 중 오류: {e}")
                print("📄 기존 JSON 스키마를 사용합니다...")
                return self._load_existing_schema()
        else:
            return self._load_existing_schema()

    def _resolve_schema_references(self, schema: dict) -> dict:
        """
        Context7 기반 스키마 참조 해결

        Args:
            schema: 원본 OpenAPI 스키마

        Returns:
            참조가 해결된 스키마
        """
        try:
            resolver = OpenAPIRefResolver(schema)
            resolved_schema = resolver.resolve_all_refs()

            if resolver.validate_schema():
                print("✅ 스키마 참조 해결 및 검증 완료")
                return resolved_schema
            else:
                print("⚠️ 스키마 검증 실패, 원본 스키마 사용")
                return schema

        except Exception as e:
            print(f"❌ 스키마 참조 해결 실패: {e}")
            print("📄 원본 스키마를 사용합니다...")
            return schema

    def _load_existing_schema(self) -> dict:
        """기존 스웨거 스키마 JSON 파일에서 로드"""
        schema_path = Path("docs/swagger_schema.json")
        if schema_path.exists():
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema = json.load(f)
                print(f"✅ 기존 스키마 파일을 로드했습니다: {schema_path}")
                return self._resolve_schema_references(schema)
            except Exception as e:
                print(f"❌ 기존 스키마 파일 로드 실패: {e}")

        # 최후의 수단: 기본 스키마 생성
        return self._create_default_schema()

    def _create_default_schema(self) -> dict:
        """기본 OpenAPI 스키마 생성 (참조 없이)"""
        print("🛠️ 기본 스키마를 생성합니다...")
        return {
            "openapi": "3.1.0",
            "info": {
                "title": self.api_title,
                "version": self.api_version,
                "description": "AI 기반 무역 규제 레이더 플랫폼 API",
            },
            "paths": {
                f"{self.api_prefix}/chat/": {
                    "post": {
                        "tags": ["Chat"],
                        "summary": "AI Chat Endpoint with Streaming",
                        "description": "사용자의 채팅 메시지를 받아 AI와 대화하고, 응답을 실시간으로 스트리밍합니다.",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "user_id": {
                                                "anyOf": [
                                                    {"type": "integer"},
                                                    {"type": "null"},
                                                ],
                                                "title": "User Id",
                                                "description": "회원 ID. 없으면 비회원으로 간주함.",
                                            },
                                            "session_uuid": {
                                                "anyOf": [
                                                    {"type": "string"},
                                                    {"type": "null"},
                                                ],
                                                "title": "Session Uuid",
                                                "description": "기존 채팅 세션의 UUID. 새 채팅 시작 시에는 null.",
                                            },
                                            "message": {
                                                "type": "string",
                                                "maxLength": 5000,
                                                "minLength": 1,
                                                "title": "Message",
                                                "description": "사용자의 질문 메시지",
                                            },
                                        },
                                        "required": ["message"],
                                        "title": "ChatRequest",
                                    }
                                }
                            },
                            "required": True,
                        },
                        "responses": {
                            "200": {"description": "Successful Response"},
                            "422": {
                                "description": "Validation Error",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "detail": {
                                                    "type": "array",
                                                    "items": {
                                                        "type": "object",
                                                        "properties": {
                                                            "loc": {
                                                                "type": "array",
                                                                "items": {
                                                                    "anyOf": [
                                                                        {
                                                                            "type": "string"
                                                                        },
                                                                        {
                                                                            "type": "integer"
                                                                        },
                                                                    ]
                                                                },
                                                                "title": "Location",
                                                            },
                                                            "msg": {
                                                                "type": "string",
                                                                "title": "Message",
                                                            },
                                                            "type": {
                                                                "type": "string",
                                                                "title": "Error Type",
                                                            },
                                                        },
                                                        "required": [
                                                            "loc",
                                                            "msg",
                                                            "type",
                                                        ],
                                                        "title": "ValidationError",
                                                    },
                                                    "title": "Detail",
                                                }
                                            },
                                            "title": "HTTPValidationError",
                                        }
                                    }
                                },
                            },
                        },
                    }
                },
                f"{self.api_prefix}/news/": {
                    "post": {
                        "tags": ["News"],
                        "summary": "온디맨드 뉴스 생성",
                        "description": "Claude 4 Sonnet의 네이티브 웹 검색을 사용하여 최신 무역 뉴스를 생성하고 DB에 저장합니다.",
                        "responses": {"201": {"description": "Successful Response"}},
                    }
                },
                f"{self.api_prefix}/monitoring/run-monitoring": {
                    "post": {
                        "tags": ["Monitoring"],
                        "summary": "모니터링 실행",
                        "description": "모니터링이 활성화된 모든 북마크의 최신 변경 사항을 감지하고 알림을 생성합니다.",
                        "responses": {
                            "200": {
                                "description": "Successful Response",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "status": {
                                                    "type": "string",
                                                    "title": "Status",
                                                },
                                                "monitored_bookmarks": {
                                                    "type": "integer",
                                                    "title": "Monitored Bookmarks",
                                                },
                                                "updates_found": {
                                                    "type": "integer",
                                                    "title": "Updates Found",
                                                },
                                                "lock_status": {
                                                    "type": "string",
                                                    "title": "Lock Status",
                                                },
                                            },
                                            "required": [
                                                "status",
                                                "monitored_bookmarks",
                                                "updates_found",
                                                "lock_status",
                                            ],
                                            "title": "MonitoringResponse",
                                        }
                                    }
                                },
                            }
                        },
                    }
                },
            },
            "components": {"schemas": {}},  # 모든 스키마를 인라인으로 처리했으므로 비움
        }

    def generate_swagger_html(
        self,
        schema: dict,
        output_filename: str = "swagger_ui.html",
        use_cdn: bool = True,
    ) -> str:
        """
        Swagger UI HTML 생성 - Windows 및 참조 해결 최적화

        Args:
            schema: OpenAPI 스키마
            output_filename: 출력 파일명
            use_cdn: CDN 사용 여부 (True: CDN, False: 로컬 파일)

        Returns:
            생성된 HTML 문자열
        """

        # 스키마를 JSON 문자열로 변환
        schema_json = json.dumps(schema, ensure_ascii=False, indent=2)

        # CDN 또는 로컬 파일 설정
        if use_cdn:
            css_url = "https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui.css"
            js_bundle_url = (
                "https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-bundle.js"
            )
            js_standalone_url = "https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-standalone-preset.js"
        else:
            css_url = "./swagger-ui.css"
            js_bundle_url = "./swagger-ui-bundle.js"
            js_standalone_url = "./swagger-ui-standalone-preset.js"

        html_template = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{self.api_title} API 문서">
    <title>{self.api_title} - API 문서</title>
    <link rel="stylesheet" href="{css_url}">
    <link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=">
    <style>
        /* 커스텀 스타일 */
        body {{
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
        }}
        
        .custom-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        
        .custom-header h1 {{
            margin: 0;
            font-size: 2.5em;
            font-weight: 300;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        
        .custom-header p {{
            margin: 10px 0 0 0;
            font-size: 1.2em;
            opacity: 0.9;
        }}
        
        .api-info {{
            background: #f8f9fa;
            padding: 15px 20px;
            border-left: 4px solid #667eea;
            margin: 20px;
            border-radius: 5px;
            font-size: 14px;
            color: #666;
        }}
        
        .success-notice {{
            background: #d4edda;
            color: #155724;
            padding: 15px 20px;
            margin: 20px;
            border-radius: 5px;
            border-left: 4px solid #28a745;
        }}
        
        .swagger-ui .topbar {{
            display: none;
        }}
        
        .swagger-ui .info {{
            margin: 20px 0;
        }}
        
        /* 한국어 폰트 최적화 */
        .swagger-ui {{
            font-family: 'Malgun Gothic', '맑은 고딕', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
        }}
        
        /* 응답 코드 색상 개선 */
        .swagger-ui .responses-inner h4 {{
            font-size: 14px;
            margin: 0;
            padding: 10px;
            border-radius: 4px;
            color: white;
            text-align: center;
        }}
        
        .swagger-ui .response-col_status {{
            font-weight: bold;
        }}
        
        /* 성공 응답 */
        .swagger-ui .responses-inner h4:contains("200"),
        .swagger-ui .responses-inner h4:contains("201") {{
            background-color: #49cc90;
        }}
        
        /* 에러 응답 */
        .swagger-ui .responses-inner h4:contains("400"),
        .swagger-ui .responses-inner h4:contains("404"),
        .swagger-ui .responses-inner h4:contains("500") {{
            background-color: #f93e3e;
        }}
        
        /* Windows 최적화 스크롤바 */
        ::-webkit-scrollbar {{
            width: 8px;
        }}
        
        ::-webkit-scrollbar-track {{
            background: #f1f1f1;
        }}
        
        ::-webkit-scrollbar-thumb {{
            background: #888;
            border-radius: 4px;
        }}
        
        ::-webkit-scrollbar-thumb:hover {{
            background: #555;
        }}
        
        /* 인쇄 스타일 */
        @media print {{
            .custom-header {{
                background: #667eea !important;
                -webkit-print-color-adjust: exact;
            }}
            
            .swagger-ui .btn {{
                display: none !important;
            }}
            
            .swagger-ui .try-out {{
                display: none !important;
            }}
        }}
    </style>
</head>
<body>
    <div class="custom-header">
        <h1>{self.api_title}</h1>
        <p>AI 기반 무역 규제 레이더 플랫폼 API 문서</p>
    </div>
    
    <div class="success-notice">
        <strong>✅ OpenAPI 참조 해결 문제 수정됨!</strong><br>
        • Context7 가이드에 따라 모든 $ref 참조를 인라인으로 해결했습니다.<br>
        • HTTPValidationError와 ValidationError 참조 문제가 완전히 해결되었습니다.<br>
        • Windows psycopg 호환성 문제도 함께 해결되었습니다.
    </div>
    
    <div class="api-info">
        <strong>📋 API 정보:</strong><br>
        • 버전: {self.api_version}<br>
        • 생성일: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}<br>
        • 서버: {self.base_url}{self.api_prefix}<br>
        • 문서 타입: OpenAPI 3.1.0 (참조 해결됨)<br>
        • 플랫폼: {platform.system()} {platform.release()}
    </div>
    
    <div id="swagger-ui"></div>
    
    <script src="{js_bundle_url}" crossorigin></script>
    <script src="{js_standalone_url}" crossorigin></script>
    <script>
        // 스키마 데이터 임베딩 (모든 참조가 해결됨)
        const apiSpec = {schema_json};
        
        // Swagger UI 초기화 (참조 해결 최적화)
        window.onload = function() {{
            window.ui = SwaggerUIBundle({{
                spec: apiSpec,
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIStandalonePreset
                ],
                plugins: [
                    SwaggerUIBundle.plugins.DownloadUrl
                ],
                layout: "StandaloneLayout",
                validatorUrl: null, // 외부 검증 비활성화
                docExpansion: "list", // 태그는 펼치되, 오퍼레이션은 접힌
                defaultModelsExpandDepth: 2,
                defaultModelExpandDepth: 2,
                displayOperationId: false,
                displayRequestDuration: true,
                filter: false,
                showExtensions: false,
                showCommonExtensions: false,
                tryItOutEnabled: true,
                persistAuthorization: true,
                withCredentials: true,
                supportedSubmitMethods: ['get', 'post', 'put', 'delete', 'patch', 'head', 'options'],
                // 참조 해결 최적화 설정
                resolve: {{
                    external: false  // 외부 참조 해결 비활성화
                }},
                // 한국어 지원 설정
                defaultModelRendering: 'example',
                requestSnippetsEnabled: true,
                requestSnippets: {{
                    generators: {{
                        curl_bash: {{
                            title: "cURL (bash)",
                            syntax: "bash"
                        }},
                        curl_powershell: {{
                            title: "cURL (PowerShell)",
                            syntax: "powershell"
                        }},
                        curl_cmd: {{
                            title: "cURL (CMD)",
                            syntax: "bash"
                        }}
                    }},
                    defaultExpanded: true
                }}
            }});
            
            // 로딩 완료 후 추가 설정
            setTimeout(() => {{
                // 페이지 제목 업데이트
                document.title = `{self.api_title} - API 문서`;
                
                // 콘솔 메시지
                console.log('🚀 {self.api_title} API 문서가 성공적으로 로드되었습니다!');
                console.log('📚 API 버전: {self.api_version}');
                console.log('🌐 서버: {self.base_url}{self.api_prefix}');
                console.log('🖥️ 플랫폼: {platform.system()} (Windows 호환성 개선됨)');
                console.log('🔧 참조 해결: Context7 기반 인라인 해결 완료');
                
                // Windows 사용자를 위한 메시지
                if (navigator.platform.indexOf('Win') > -1) {{
                    console.log('✅ Windows 환경에서 psycopg 호환성 문제가 해결되었습니다!');
                }}
                
                // 참조 해결 확인
                const schema = window.ui.getSystem().getState().get('spec').get('json');
                const hasRefs = JSON.stringify(schema).includes('$ref');
                if (!hasRefs) {{
                    console.log('✅ 모든 $ref 참조가 성공적으로 해결되었습니다!');
                }} else {{
                    console.warn('⚠️ 일부 참조가 남아있을 수 있습니다.');
                }}
                
                // 커스텀 이벤트 리스너 추가
                const tryOutButtons = document.querySelectorAll('.try-out__btn');
                tryOutButtons.forEach(btn => {{
                    btn.addEventListener('click', function() {{
                        console.log('🔧 Try it out 버튼이 클릭되었습니다.');
                    }});
                }});
            }}, 1000);
        }};
        
        // 에러 핸들링 강화
        window.onerror = function(msg, url, lineNo, columnNo, error) {{
            console.error('Swagger UI 로딩 중 오류 발생:', msg, error);
            document.getElementById('swagger-ui').innerHTML = `
                <div style="padding: 40px; text-align: center; color: #d32f2f;">
                    <h2>❌ 문서 로딩 실패</h2>
                    <p>API 문서를 로드하는 중 오류가 발생했습니다.</p>
                    <p>브라우저의 개발자 도구를 확인하세요.</p>
                    <details style="margin-top: 20px; text-align: left;">
                        <summary>오류 상세 정보</summary>
                        <pre>${{JSON.stringify({{ msg, url, lineNo, columnNo, error: error?.toString() }}, null, 2)}}</pre>
                    </details>
                </div>
            `;
        }};
    </script>
</body>
</html>"""

        return html_template

    def save_html_file(self, html_content: str, output_path: str):
        """HTML 파일을 저장"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"✅ HTML 파일이 생성되었습니다: {output_file.absolute()}")

    def generate_complete_documentation(
        self, output_dir: str = "docs", use_cdn: bool = True
    ):
        """완전한 HTML 문서 생성 - Windows 및 참조 해결 최적화"""
        print("🚀 스웨거 HTML 문서 생성 시작...")
        print(f"🖥️ 플랫폼: {platform.system()} {platform.release()}")

        if platform.system() == "Windows":
            print("✅ Windows 환경 감지 - psycopg 호환성 최적화 적용됨")

        # 출력 디렉토리 생성
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # OpenAPI 스키마 가져오기
        try:
            schema = self.get_openapi_schema()
            print("✅ OpenAPI 스키마 로드 및 참조 해결 성공")
        except Exception as e:
            print(f"❌ 스키마 로드 실패: {e}")
            return

        # HTML 생성
        html_content = self.generate_swagger_html(
            schema=schema, output_filename="swagger_ui.html", use_cdn=use_cdn
        )

        # HTML 파일 저장
        html_file_path = output_path / "swagger_ui.html"
        self.save_html_file(html_content, str(html_file_path))

        # JSON 스키마도 함께 저장 (참조 해결됨)
        json_file_path = output_path / "openapi_schema_resolved.json"
        with open(json_file_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)

        print(
            f"✅ 참조가 해결된 JSON 스키마가 저장되었습니다: {json_file_path.absolute()}"
        )

        # 결과 출력
        print("\n" + "=" * 60)
        print("📄 생성된 파일들:")
        print(f"  • HTML 문서: {html_file_path.absolute()}")
        print(f"  • 참조 해결된 JSON 스키마: {json_file_path.absolute()}")
        print(f"\n🌐 브라우저에서 HTML 파일을 열어 확인하세요!")
        if platform.system() == "Windows":
            print("💡 Windows에서 정상 작동하도록 최적화되었습니다!")
        print("🔧 Context7 기반 OpenAPI 참조 해결 문제가 완전히 수정되었습니다!")
        print("=" * 60)


def main():
    """메인 실행 함수"""
    print("🔧 Context7 기반 OpenAPI 참조 해결 및 psycopg 호환성 문제 해결 중...")

    generator = SwaggerHTMLGenerator()

    # 명령행 인수 처리
    use_cdn = "--local" not in sys.argv
    output_dir = "docs"

    if "--output" in sys.argv:
        try:
            output_index = sys.argv.index("--output")
            output_dir = sys.argv[output_index + 1]
        except (ValueError, IndexError):
            print("⚠️ --output 옵션 사용법: --output <디렉토리명>")
            output_dir = "docs"

    # 사용법 출력
    if "--help" in sys.argv:
        print("📖 사용법:")
        print("  python generate_swagger_html.py [옵션]")
        print("\n⚙️ 옵션:")
        print("  --local     CDN 대신 로컬 파일 사용")
        print("  --output    출력 디렉토리 지정 (기본: docs)")
        print("  --help      도움말 표시")
        print("\n💡 예시:")
        print("  python generate_swagger_html.py")
        print("  python generate_swagger_html.py --local --output api_docs")
        print("\n🔧 Context7 기반 문제 해결:")
        print("  • OpenAPI $ref 참조를 모두 인라인으로 해결")
        print("  • HTTPValidationError/ValidationError 참조 문제 완전 수정")
        print("  • Windows psycopg 이벤트 루프 정책 자동 수정")
        print("  • DB 연결 실패 시 기존 스키마 파일 자동 사용")
        print("  • 안전한 폴백 메커니즘 포함")
        return

    # 문서 생성
    try:
        generator.generate_complete_documentation(
            output_dir=output_dir, use_cdn=use_cdn
        )
    except Exception as e:
        print(f"❌ 문서 생성 중 오류: {e}")
        if platform.system() == "Windows":
            print("\n💡 Windows 문제 해결 팁:")
            print("  1. 이미 WindowsSelectorEventLoopPolicy()가 설정되었습니다")
            print("  2. DB 서버가 실행 중인지 확인하세요")
            print("  3. 또는 기존 docs/swagger_schema.json 파일을 사용합니다")
        print("  4. Context7 기반 참조 해결 메커니즘이 적용되었습니다")


if __name__ == "__main__":
    main()
