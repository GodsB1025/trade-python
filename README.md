# Trade Python AI Service

LangChain + Claude + FastAPI 기반 웹 검색 AI 서비스

## 🚀 주요 기능

- **Claude 4 Sonnet 모델** 기반 AI 응답
- **Anthropic 공식 웹 검색 도구** 활용
- **다중 웹 검색** 수행 (general, news, academic, technical)
- **Prompt Chaining** 메커니즘
- **대화 상태 관리** 및 세션 유지
- **구조화된 JSON 응답** (Spring Boot 연동)
- **FastAPI** 기반 REST API

## 🏗️ 아키텍처

```
┌─────────────────┐    HTTP/JSON    ┌─────────────────┐
│   Spring Boot   │ ────────────── │   FastAPI       │
│   (Frontend)    │                │   (Python)      │
└─────────────────┘                └─────────────────┘
                                            │
                                            ▼
                                   ┌─────────────────┐
                                   │   LangChain     │
                                   │   Service       │
                                   └─────────────────┘
                                            │
                                            ▼
                                   ┌─────────────────┐
                                   │   Claude 4      │
                                   │   Sonnet        │
                                   │   + Web Search  │
                                   └─────────────────┘
```

## 📁 프로젝트 구조

```
trade-python/
├── app/
│   ├── main.py              # FastAPI 메인 애플리케이션
│   │   ├── schemas.py       # Pydantic 스키마 정의
│   │   └── chat_models.py   # 대화 상태 관리 모델
│   ├── services/
│   │   ├── anthropic_service.py   # Claude API 서비스
│   │   └── langchain_service.py   # LangChain 통합 서비스
│   ├── chains/
│   │   └── prompt_chains.py       # 프롬프트 체이닝 로직
│   └── utils/
│       └── config.py              # 설정 관리
├── main.py                  # 엔트리포인트
├── pyproject.toml          # 의존성 관리
└── .env.example           # 환경 변수 예시
```

## 🛠️ 설치 및 실행

### 1. 프로젝트 클론

```bash
git clone <repository-url>
cd trade-python
```

### 2. 환경 설정

```bash
# .env 파일 생성
cp .env.example .env

# Anthropic API 키 설정 (필수)
# .env 파일에서 ANTHROPIC_API_KEY 값을 실제 API 키로 변경
```

### 3. 의존성 설치

```bash
# uv 사용 (권장)
uv install

# 또는 pip 사용
pip install -e .
```

### 4. 서비스 실행

```bash
# 개발 모드
python main.py

# 또는 직접 uvicorn 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 📡 API 엔드포인트

### 1. 채팅 API (Spring Boot 연동용)

```http
POST /api/chat
Content-Type: application/json

{
  "message": "사용자 메시지",
  "session_id": "optional-session-id",
  "enable_web_search": true,
  "search_types": ["general", "news"]
}
```

**응답 예시:**
```json
{
  "message": "AI 응답 메시지",
  "session_id": "session-uuid",
  "ai_response": {
    "content": "상세 응답 내용",
    "confidence_score": 0.95,
    "sources_used": ["http://example.com"],
    "reasoning_steps": ["1단계", "2단계"],
    "metadata": {}
  },
  "web_search_results": {
    "query": "검색 쿼리",
    "total_results": 5,
    "results": [...],
    "search_duration_ms": 1500
  },
  "conversation_history": [...],
  "processing_time_ms": 2000,
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### 2. 웹 검색 전용 API

```http
POST /api/search
Content-Type: application/json

{
  "query": "검색할 내용",
  "search_types": ["general", "academic"],
  "max_results_per_search": 5
}
```

### 3. 헬스체크

```http
GET /health
```

### 4. 세션 관리

```http
# 세션 정보 조회
GET /api/session/{session_id}

# 세션 삭제
DELETE /api/session/{session_id}
```

## 🔧 주요 설정

### 환경 변수

| 변수명                | 설명                    | 기본값                     |
| --------------------- | ----------------------- | -------------------------- |
| `ANTHROPIC_API_KEY`   | Anthropic API 키 (필수) | -                          |
| `ANTHROPIC_MODEL`     | 사용할 Claude 모델      | `claude-3-5-sonnet-latest` |
| `WEB_SEARCH_MAX_USES` | 웹 검색 최대 횟수       | `5`                        |
| `DEBUG`               | 디버그 모드             | `false`                    |
| `CORS_ORIGINS`        | CORS 허용 도메인        | Spring Boot 기본 포트      |

## 🔍 프롬프트 체이닝

1. **쿼리 분석**: 사용자 질문 분석 및 검색 전략 수립
2. **다중 검색**: 타입별 웹 검색 수행
3. **결과 종합**: 검색 결과 분석 및 중간 답변 생성
4. **최종 합성**: 모든 정보를 종합한 최종 응답 생성

## 🤝 Spring Boot 연동 예시

### Spring Boot RestTemplate 사용

```java
@Service
public class PythonAIService {
    
    @Autowired
    private RestTemplate restTemplate;
    
    @Value("${python.ai.url:http://localhost:8000}")
    private String pythonAiUrl;
    
    public ChatResponse sendMessage(ChatRequest request) {
        return restTemplate.postForObject(
            pythonAiUrl + "/api/chat",
            request,
            ChatResponse.class
        );
    }
}
```

### Spring Boot WebClient 사용 (비동기)

```java
@Service
public class PythonAIService {
    
    private final WebClient webClient;
    
    public PythonAIService() {
        this.webClient = WebClient.builder()
            .baseUrl("http://localhost:8000")
            .build();
    }
    
    public Mono<ChatResponse> sendMessageAsync(ChatRequest request) {
        return webClient.post()
            .uri("/api/chat")
            .bodyValue(request)
            .retrieve()
            .bodyToMono(ChatResponse.class);
    }
}
```

## 🧪 테스트

```bash
# 헬스체크 테스트
curl http://localhost:8000/health

# 채팅 테스트
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "최신 AI 뉴스를 알려줘",
    "enable_web_search": true,
    "search_types": ["news"]
  }'
```

## 📝 개발 노트

### 구현된 기능

- ✅ Claude 4 Sonnet 통합
- ✅ Anthropic 웹 검색 도구
- ✅ 다중 검색 타입 지원
- ✅ 프롬프트 체이닝
- ✅ 대화 상태 관리
- ✅ 구조화된 JSON 응답
- ✅ FastAPI REST API
- ✅ Spring Boot 연동 준비

### 향후 개선 사항

- [ ] 검색 결과 캐싱
- [ ] 대화 내용 영구 저장
- [ ] 더 정교한 프롬프트 체이닝
- [ ] 모니터링 및 로깅 강화
- [ ] 부하 테스트 및 성능 최적화

## �� 라이선스

MIT License
