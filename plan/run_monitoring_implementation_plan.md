### **`/run-monitoring` 엔드포인트 상세 구현 계획서**

**문서 버전:** v1.0
**작성일:** 2024-07-26
**기준 문서:**
1.  `구현계획.md` (vFinal)
2.  `docs/Redis 데이터 구조.md` (v6.2)

---

### **1. 기능 목표 (The 'Why')**

`POST /run-monitoring` 엔드포인트는 **Spring Boot 스케줄러에 의해 주기적으로 호출**되는 **백그라운드 작업 전용 API**다. 이 엔드포인트의 핵심 목표는 사용자가 북마크한 항목(`HSCode`, 규제 등)에 대해 최신 변경 사항을 능동적으로 감지하고, **유의미한 업데이트가 발생했을 때 사용자에게 알림을 보낼 수 있도록** 시스템에 기록을 남기는 것이다.

이 과정은 1) 데이터베이스에서 모니터링이 활성화된 북마크 조회, 2) AI 웹 검색을 통한 최신 정보 확인, 3) 변경점 요약 및 데이터베이스 저장, 4) Redis를 이용한 비동기 알림 큐잉의 4단계로 구성된다.

### **2. 기술 아키텍처 및 데이터 흐름**

```mermaid
sequenceDiagram
    participant Spring as Spring Scheduler
    participant FastAPI as /run-monitoring
    participant LangChain as LangChain Service
    participant Claude as Anthropic API
    participant PostgreSQL as DB
    participant Redis as Cache/Queue

    Spring->>+FastAPI: 1. POST /run-monitoring (작업 트리거)

    par "작업 동시 실행 방지"
        FastAPI->>Redis: 2. SET monitoring:job:lock "in_progress" NX EX 3600
        alt 락 획득 실패
            Redis-->>FastAPI: (nil)
            FastAPI-->>-Spring: 429 Too Many Requests (이미 작업 진행 중)
        end
    end
    Redis-->>FastAPI: OK (락 획득 성공)

    FastAPI->>+PostgreSQL: 3. SELECT * FROM bookmarks WHERE monitoring_active = true
    PostgreSQL-->>-FastAPI: [Bookmark(1), Bookmark(2), ...]

    loop 각 Bookmark 순회
        FastAPI->>+LangChain: 4. "{bookmark.target_keyword} 최신 정보 요약해줘"
        LangChain->>+Claude: 5. 웹 검색 기반 프롬프트 실행
        Claude-->>-LangChain: 6. 검색 결과 및 요약 반환
        LangChain-->>-FastAPI: 7. 최종 요약 텍스트

        FastAPI->>FastAPI: 8. 기존 정보와 비교하여 '유의미한' 업데이트인지 판단
        alt 유의미한 업데이트 발생
            FastAPI->>+PostgreSQL: 9. INSERT INTO update_feeds (user_id, bookmark_id, ...)
            PostgreSQL-->>-FastAPI: new_feed_id 반환

            FastAPI->>+Redis: 10. HSET daily_notification:detail:{uuid} message "..."
            Redis-->>-FastAPI: OK
            FastAPI->>+Redis: 11. LPUSH daily_notification:queue:EMAIL {uuid}
            Redis-->>-FastAPI: (integer) 1
        end
    end

    FastAPI->>Redis: 12. DEL monitoring:job:lock (작업 완료 후 락 해제)
    FastAPI-->>-Spring: 200 OK ({"monitored": 10, "updates": 2})
```

### **3. Step-by-Step 구현 상세**

**파일 위치:** `app/api/v1/endpoints/monitoring.py`

#### **3.1. 의존성 및 초기 설정**

-   **FastAPI:** `APIRouter`, `Depends`, `BackgroundTasks`
-   **SQLAlchemy:** `Session`
-   **Redis:** `Redis` 클라이언트 인스턴스
-   **서비스:** `LangChainService`
-   **CRUD:** `crud.bookmark`, `crud.update_feed`
-   **Pydantic 모델:** `MonitoringResponse`

#### **3.2. 엔드포인트 시그니처 정의**

```python
# app/api/v1/endpoints/monitoring.py

router = APIRouter()

class MonitoringResponse(BaseModel):
    status: str
    monitored_bookmarks: int
    updates_found: int

@router.post("/run-monitoring", response_model=MonitoringResponse)
async def run_monitoring(
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    langchain_service: LangChainService = Depends(get_langchain_service)
):
    # ... 구현 ...
```

#### **3.3. (Step 2) 작업 동시 실행 방지 (Job Lock)**

-   Redis의 `SET...NX`를 사용하여 원자적으로 락(Lock)을 설정한다.
-   **키 형식:** `monitoring:job:lock`
-   **값:** `in_progress` 또는 현재 시간의 타임스탬프
-   **TTL:** 예상 최대 실행 시간보다 길게 설정 (예: 1시간 = 3600초)
-   만약 락 획득에 실패하면(`set` 명령이 `None` 또는 `0`을 반환), 다른 프로세스가 이미 작업을 수행 중이라는 의미이므로 `HTTP 429 Too Many Requests` 예외를 즉시 발생시킨다.
-   `try...finally` 블록을 사용하여 작업이 성공하든 실패하든 반드시 락을 해제(`DEL`)하도록 보장한다.

#### **3.4. (Step 3) 모니터링 대상 북마크 조회**

-   `crud.bookmark.get_active_bookmarks(db: Session)` 함수를 호출한다.
-   이 CRUD 함수는 내부적으로 `db.query(Bookmark).filter(Bookmark.monitoring_active == True).all()`을 실행하여 모든 활성 북마크 객체의 리스트를 반환한다.
-   조회된 북마크가 없으면, 락을 해제하고 즉시 성공 응답(`{"status": "success", "monitored_bookmarks": 0, "updates_found": 0}`)을 반환한다.

#### **3.5. (Step 4-8) 북마크 순회 및 정보 업데이트 처리**

-   `for bookmark in active_bookmarks:` 루프를 실행한다.
-   각 루프 내부는 `try...except` 블록으로 감싸 특정 북마크 처리 실패가 전체 작업에 영향을 주지 않도록 격리한다.

    1.  **AI 서비스 호출 (정보 수집):**
        -   `langchain_service.get_latest_info_for_keyword(keyword=bookmark.target_keyword)`를 호출한다.
        -   이 서비스는 내부에 "키워드 관련 최신 정보/규제 변경사항을 웹에서 검색하고 요약해줘" 같은 프롬프트를 포함한다.
        -   `timeout`과 `retry` 로직을 서비스 내에 구현하여 안정성을 높인다.

    2.  **'유의미한 변경' 판단:**
        -   **1차 필터링:** AI가 반환한 `summary`가 비어있거나, "변경 사항 없음"과 같은 미리 정의된 무의미한 응답인지 확인한다.
        -   **2차 필터링 (중복 방지):** `summary` 내용의 해시(예: SHA256)를 계산하여, `update_feeds` 테이블에 해당 `bookmark_id`로 동일한 콘텐츠 해시가 이미 존재하는지 확인한다. 이는 동일한 업데이트에 대해 중복 알림을 방지하는 핵심 로직이다.
        -   `crud.update_feed.get_by_bookmark_and_content_hash(db, bookmark_id, content_hash)` 와 같은 함수가 필요하다.

    3.  **DB 저장 (UpdateFeed 생성):**
        -   유의미한 변경이라고 판단되면, `crud.update_feed.create()`를 호출하여 `update_feeds` 테이블에 새로운 레코드를 삽입한다.
        -   저장될 데이터: `bookmark_id`, `user_id` (bookmark 객체에서 파생), `summary`, `content_hash`, `source_url` (AI가 제공했다면) 등.

#### **3.6. (Step 9-11) 비동기 알림 큐잉**

-   `update_feeds` 레코드 생성이 성공적으로 완료되면, **즉시** 사용자에게 알림을 보내는 것이 아니라 **Redis 큐에 작업을 넣는다.** 이는 알림 발송 실패가 모니터링 작업 전체를 중단시키지 않도록 분리하는 설계다.

    1.  **알림 내용 생성 및 저장 (Hash):**
        -   `uuid`를 사용하여 고유한 알림 ID를 생성한다.
        -   **키:** `daily_notification:detail:{uuid}`
        -   **데이터 (Hash):** `user_id`, `message` (예: `'{bookmark.name}'에 새로운 업데이트가 있습니다!`), `type` (`EMAIL` 또는 `SMS`), `update_feed_id` 등 알림 발송에 필요한 모든 정보를 저장한다.
        -   `redis_client.hset(f"daily_notification:detail:{uuid}", mapping={...})`

    2.  **알림 큐에 ID 추가 (List):**
        -   사용자의 알림 설정(`user.notification_preference`)을 확인하여 `EMAIL` 또는 `SMS` 큐를 결정한다.
        -   **키:** `daily_notification:queue:EMAIL` 또는 `daily_notification:queue:SMS`
        -   `redis_client.lpush(queue_name, uuid)` 명령으로 큐의 왼쪽에 작업 ID를 추가한다.

#### **3.7. (Step 12) 작업 완료 및 응답**

-   루프가 모두 끝나면, `finally` 블록에서 Redis 락을 해제한다.
-   총 처리한 북마크 수(`monitored_count`)와 업데이트를 발견하여 `update_feeds`에 저장한 수(`updates_found_count`)를 집계하여 최종 `MonitoringResponse` 모델에 담아 반환한다.

### **4. 오류 처리 전략**

-   **개별 북마크 오류:** 루프 내의 `try...except` 블록에서 `logger.error(...)`로 실패 사실(어떤 북마크인지, 이유는 무엇인지)을 기록하고, `continue`를 통해 다음 북마크 처리를 계속 진행한다.
-   **AI 서비스 오류:** LangChain 서비스 호출 시 `httpx.TimeoutException` 등 네트워크 오류나 API 키 오류가 발생할 수 있다. 이를 개별 북마크 오류로 처리하고 로깅한다.
-   **DB 오류:** `update_feeds` 저장 실패 시, 해당 트랜잭션을 롤백하고 오류를 로깅한다. Redis 큐잉은 시도하지 않는다.
-   **Redis 오류:** Redis 연결 실패는 심각한 문제다. 작업 시작 시점에 연결을 확인하고, 실패 시 즉시 작업을 중단하고 관리자에게 알릴 수 있는 로깅(레벨: `CRITICAL`)을 남긴다. `update_feeds` 저장 후 Redis 큐잉만 실패했다면, "데이터는 저장됐으나 알림 발송은 실패함"을 명확히 로깅하여 수동 조치가 가능하게 한다.

### **5. 결론**

이 계획은 `구현계획.md`의 상위 아키텍처를 따르면서, `Redis 데이터 구조.md`의 신뢰성 높은 큐 패턴을 결합하여 **안정적이고 확장 가능한 백그라운드 모니터링 시스템**을 구현하는 구체적인 청사진이다. 각 단계의 책임을 명확히 하고 오류 처리 방안을 구체화하여 고품질의 코드를 작성하는 기반을 제공한다. 