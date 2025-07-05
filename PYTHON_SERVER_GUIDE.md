
### **Python AI 서비스 허브: 기술 아키텍처 및 개발 가이드**

**문서 버전:** 1.0
**최종 업데이트:** 2025-07-04

---

### **1. 개요 (Overview)**

이 문서는 "무역 규제 레이더 플랫폼"의 Python AI 서비스 허브에 대한 포괄적인 기술 아키텍처, 상세 설계, 그리고 운영 가이드를 제공합니다.

#### **1.1. 시스템의 목적 (The 'Why')**

본 Python 서버는 전체 플랫폼의 **AI 두뇌** 역할을 수행하는 **온디맨드 서비스 허브(On-Demand Service Hub)** 입니다. 자체적으로 스케줄링이나 사용자 인증 같은 제어 로직을 갖지 않고, 오직 외부 시스템(Spring Boot Control Tower)의 명시적인 API 요청에만 응답하여 다음과 같은 AI 기반 중작업(Heavy-lifting)을 전담합니다.

-   **대화형 AI:** 사용자와의 실시간 채팅을 통해 HSCode 정보, 규제, 무역 관련 질문에 답변합니다.
-   **데이터 수집 및 가공:** 웹 검색을 통해 최신 무역 뉴스를 수집하고 AI를 통해 요약/분류합니다.
-   **능동적 정보 모니터링:** 사용자가 북마크한 항목에 대한 최신 변경 사항을 웹에서 감지하고 요약합니다.

이러한 책임 분리는 각 서버가 자신의 전문 분야에만 집중하게 하여, 시스템 전체의 복잡도를 낮추고 유지보수성과 확장성을 극대화합니다.

#### **1.2. 핵심 설계 철학**

-   **외부 제어(Externally Controlled):** 모든 백그라운드 작업(뉴스 생성, 북마크 모니터링)은 Spring Boot 스케줄러에 의해 트리거됩니다. Python 서버는 독립적으로 작업을 시작하지 않습니다.
-   **상태 비저장 지향(Stateless-Oriented):** 각 API 요청은 가능한 한 독립적으로 처리됩니다. 대화의 맥락 유지가 필요한 채팅 기능의 경우, 상태(대화 기록)를 외부 데이터베이스(PostgreSQL)에 저장하여 서버 자체는 상태를 가지지 않도록 설계되었습니다.
-   **비동기 처리(Asynchronous):** `FastAPI`와 `asyncio`를 기반으로 모든 I/O(DB 접근, 외부 API 호출)를 비동기/논블로킹 방식으로 처리하여, 적은 리소스로 높은 동시성을 확보합니다.

---

### **2. 기술 스택 (Technology Stack)**

| 분야                       | 기술                     | 도입 사유                                                                                                                                   |
| -------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **웹 프레임워크**          | `FastAPI`                | ASGI 기반 고성능 비동기 처리, Pydantic을 통한 자동 데이터 유효성 검사 및 API 문서 생성으로 개발 생산성 극대화.                              |
| **LLM 오케스트레이션**     | `LangChain`              | RAG, 대화 메모리, 프롬프트 관리 등 복잡한 LLM 애플리케이션 로직을 표준화된 인터페이스(`Runnable`)로 모듈화하여 재사용성 및 유지보수성 향상. |
| **데이터베이스 ORM**       | `SQLAlchemy 2.0 (Async)` | 파이썬 표준 ORM으로, 비동기 쿼리를 지원하여 I/O 병목을 최소화하고, 파이썬 코드로 DB 스키마와 상호작용의 일관성을 유지.                      |
| **LLM Provider**           | `Anthropic Claude 3`     | 강력한 웹 검색(Tool-use) 기능, 한국어 처리 능력, 그리고 구조화된 데이터(JSON) 생성 능력을 바탕으로 프로젝트의 핵심 요구사항을 만족.         |
| **인메모리 데이터 저장소** | `Redis`                  | 분산 락(Distributed Lock)을 통한 작업 동시성 제어 및 신뢰성 높은 알림 큐(Reliable Queue) 시스템 구현에 필수적.                              |
| **데이터 검증**            | `Pydantic`               | API 요청/응답 본문 및 LLM의 구조화된 출력까지, 애플리케이션의 모든 데이터 계층에서 엄격한 타입 및 형식 검증을 보장.                         |

---

### **3. 프로젝트 구조 (Project Structure)**

```
app/
├── api/                  # API 엔드포인트 및 라우팅 정의
│   └── v1/
│       ├── endpoints/      # 기능별 엔드포인트 구현 (chat.py, news.py, monitoring.py)
│       ├── __init__.py
│       └── api.py          # v1 API 라우터 집계
├── chains/               # (Legacy) LangChain 체인 관련 모듈 (현재는 services 계층에 통합)
├── core/                 # 애플리케이션의 핵심 설정
│   ├── middleware/       # FastAPI 미들웨어 (로깅 등)
│   ├── config.py         # 환경변수 및 설정 관리
│   ├── llm_provider.py   # LLM 인스턴스 생성 및 설정 (재시도, 모델 바인딩 등)
│   └── logging_config.py # 중앙 로깅 설정
├── db/                   # 데이터베이스 관련 로직
│   ├── crud.py           # SQLAlchemy를 사용한 CRUD 함수 집합
│   └── session.py        # 비동기 DB 세션 관리
├── models/               # 데이터 모델 정의
│   ├── chat_models.py    # 채팅 관련 Pydantic 모델
│   ├── db_models.py      # SQLAlchemy 테이블 모델 (스키마 정의)
│   ├── monitoring_models.py # 모니터링 관련 Pydantic 모델
│   └── schemas.py        # API 요청/응답을 위한 Pydantic 스키마
├── services/             # 비즈니스 로직
│   ├── chat_history_service.py # DB 기반 대화 기록 저장/조회 로직
│   ├── chat_service.py   # 채팅 비즈니스 로직 (LangChain 체인 오케스트레이션)
│   ├── langchain_service.py # 실제 LangChain Runnable 체인 구성
│   └── news_service.py   # 뉴스 생성 비즈니스 로직
├── utils/                # 유틸리티 함수
│   └── llm_response_parser.py # LLM 응답 파싱 유틸리티
├── vector_stores/        # 벡터 저장소 및 Retriever 관련 모듈
│   └── hscode_retriever.py # HSCode Vector DB Retriever
└── main.py               # FastAPI 애플리케이션 생성 및 초기화 (진입점)
```

---

### **4. API 엔드포인트 상세 명세 (API Endpoints Deep Dive)**

#### **4.1. `POST /api/v1/chat/` - 대화형 AI 엔드포인트**

-   **파일:** `app/api/v1/endpoints/chat.py`
-   **책임:** 사용자의 질문을 SSE(Server-Sent Events) 스트림으로 실시간 처리하여 응답. 모든 복잡한 로직은 `ChatService`에 위임.
-   **데이터 흐름:**
    ```mermaid
    sequenceDiagram
        participant Client
        participant FastAPI as /chat
        participant ChatService
        participant LangChainService
        participant DB

        Client->>+FastAPI: 1. POST /chat (message, user_id?, session_uuid?)
        FastAPI->>+ChatService: 2. stream_chat_response() 호출
        ChatService->>+DB: 3. 회원인 경우, 채팅 세션 조회/생성
        ChatService->>+LangChainService: 4. 체인(.astream) 호출
        LangChainService-->>-ChatService: 5. AI 토큰 스트림 반환
        ChatService-->>-FastAPI: 6. SSE 형식으로 변환하여 yield
        FastAPI-->>-Client: 7. 실시간 스트림 전송
        Note over ChatService, DB: 대화 종료 후<br/>백그라운드로 대화 기록 저장
    ```
-   **핵심 로직 (`LangChainService`):**
    1.  **HSCode 질문 판별:** 정규식(`\d{4}\.\d{2}`)을 사용해 질문 유형을 판별.
    2.  **(분기) HSCode 질문:**
        -   **RAG 시도:** `hscode_retriever`로 내부 VectorDB 검색.
        -   **내부 분기:**
            -   **성공:** 검색된 문서를 컨텍스트로 사용해 답변 생성.
            -   **실패:** Claude의 네이티브 웹 검색 기능으로 폴백(Fallback)하여 답변 생성. 이때, 검색 결과는 `BackgroundTasks`를 통해 비동기적으로 VectorDB에 저장되어 시스템의 지식을 점진적으로 확장(Self-correction).
    3.  **(분기) 일반 질문:** 웹 검색 없이 일반 대화 모델로 답변 생성.

#### **4.2. `POST /api/v1/monitoring/run-monitoring` - 북마크 모니터링**

-   **파일:** `app/api/v1/endpoints/monitoring.py`
-   **책임:** Spring Boot 스케줄러에 의해 호출되어, 모니터링이 활성화된 모든 북마크의 최신 정보를 AI로 확인하고, 변경 시 `update_feeds` 테이블에 기록 및 Redis에 알림 작업을 큐잉.
-   **데이터 흐름:**
    ```mermaid
    flowchart TD
        A[POST /run-monitoring] --> B(Redis에 분산 락 설정);
        B --> C{락 획득 성공?};
        C -- No --> D[429 에러 반환];
        C -- Yes --> E[DB: active=true인 북마크 조회];
        E --> F[For each bookmark...];
        F --> G[LangChain: 웹 검색으로 최신 정보 요약];
        G --> H{유의미한 업데이트 발견?};
        H -- Yes --> I[DB: update_feeds에 저장];
        I --> J[Redis: 알림 큐에 작업 Push];
        H -- No --> K[다음 북마크로];
        J --> K;
        F -- 완료 --> L(Redis 락 해제);
        L --> M[200 OK 응답 반환];
    ```
-   **핵심 기술:**
    -   **분산 락 (`Redis SET NX`):** 여러 서버 인스턴스가 동시에 실행되는 것을 방지하여 데이터 정합성 보장.
    -   **신뢰성 큐 패턴:**
        1.  `update_feeds`에 변경 내역을 먼저 DB에 저장 (Source of Truth).
        2.  `HSET`으로 알림 상세 정보를 Redis Hash에 저장.
        3.  `LPUSH`로 처리할 작업 ID를 Redis List(대기 큐)에 추가. 이로써 알림 발송 시스템(Consumer) 장애가 모니터링 작업(Producer)에 영향을 주지 않도록 격리.

#### **4.3. `POST /api/v1/news/` - 온디맨드 뉴스 생성**

-   **파일:** `app/api/v1/endpoints/news.py`
-   **책임:** Spring Boot 스케줄러에 의해 호출되어, AI 웹 검색을 통해 최신 무역 뉴스를 생성하고 DB에 저장.
-   **핵심 로직:** `NewsService`를 통해 `LangChain` 체인을 호출하여 웹에서 뉴스를 검색, 요약, 분류하고 그 결과를 `trade_news` 테이블의 스키마에 맞게 구조화하여 DB에 저장.

---

### **5. 데이터베이스 및 Redis 전략**

#### **5.1. PostgreSQL (SQLAlchemy)**

-   **스키마 관리:** `app/models/db_models.py` 파일이 SQLAlchemy 모델을 통해 DB 스키마를 코드로 정의 (Code-as-Schema). 이는 `docs/스키마.md`의 DDL과 동기화되어야 함.
-   **주요 테이블:**
    -   `chat_sessions`, `chat_messages`: 회원 채팅 기록 저장. `user_id`와 `session_uuid`로 관리.
    -   `bookmarks`: 사용자가 모니터링을 원하는 항목. `monitoring_active` 컬럼으로 활성화 여부 제어.
    -   `update_feeds`: 모니터링을 통해 발견된 업데이트 내역 저장.
    -   `trade_news`: 온디맨드 뉴스 생성 결과 저장.
    -   `hscode_vectors` / `documents`: RAG를 위한 임베딩 벡터 및 원본 텍스트 저장.

#### **5.2. Redis**

-   **역할:** 데이터의 영구 저장이 아닌, **시스템의 신뢰성과 동시성 제어**를 위한 보조 역할.
-   **주요 패턴 (`docs/Redis 데이터 구조.md` 기반):**
    -   **분산 락:** `monitoring:job:lock` 키 (String 타입)를 `SET NX`로 설정하여 모니터링 작업의 동시 실행 방지.
    -   **신뢰성 알림 큐:**
        -   `daily_notification:detail:{uuid}` (Hash): 알림 발송에 필요한 상세 정보(수신자, 내용 등) 저장.
        -   `daily_notification:queue:{TYPE}` (List): 처리해야 할 알림 작업의 `uuid`를 저장하는 대기열. 외부 Consumer(Spring)는 이 큐를 `BLMOVE`와 같은 명령어로 안전하게 처리.

---

### **6. 설치 및 실행 가이드**

1.  **환경 설정:**
    - 프로젝트 루트에 `.env` 파일을 생성하고 `app/core/config.py`에 정의된 환경 변수들을 설정합니다. (DB 접속 정보, Anthropic API 키 등)

    ```bash
    # .env 예시
    PROJECT_NAME="Trade AI Service"
    API_V1_STR="/api/v1"
    
    # Database
    POSTGRES_SERVER=localhost
    POSTGRES_USER=your_user
    POSTGRES_PASSWORD=your_password
    POSTGRES_DB=trade_db
    
    # LLM
    ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
    ```

2.  **의존성 설치:**
    - `uv` (혹은 `pip`)를 사용하여 `pyproject.toml`에 명시된 의존성을 설치합니다.

    ```bash
    uv pip install -r requirements.txt 
    # 혹은 poetry, pdm 등 프로젝트에서 사용하는 패키지 매니저 사용
    ```

3.  **애플리케이션 실행:**
    - `uvicorn`을 사용하여 FastAPI 애플리케이션을 실행합니다.

    ```bash
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    ```

4.  **API 문서 확인:**
    - 서버 실행 후, 브라우저에서 `http://localhost:8000/api/v1/docs`로 접속하면 자동 생성된 Swagger UI 문서를 확인할 수 있습니다. 