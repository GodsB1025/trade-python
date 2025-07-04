# Trade Python AI Service
**생성일**: 2025-07-04 20:37:32

## 목차
- [API 정보](#api-정보)
- [엔드포인트](#엔드포인트)
- [데이터 스키마](#데이터-스키마)

## API 정보

**버전**: 0.1.0

## 엔드포인트

### Chat

#### `POST /api/v1/chat/`

**요약**: AI Chat Endpoint with Streaming

**설명**: 사용자의 채팅 메시지를 받아 AI와 대화하고, 응답을 실시간으로 스트리밍합니다.

- **요청 본문:** `ChatRequest` 모델 참조
    - `user_id`: 회원 식별자 (없으면 비회원)
    - `session_uuid`: 기존 대화의 UUID
    - `message`: 사용자 메시지
- **응답:**
    - `StreamingResponse`: `text/event-stream` 형식의 SSE 스트림.
    - 각 이벤트는 JSON 형식이며, `type`과 `data` 필드를 포함합니다.
      - `type: 'session_id'`: 새 채팅 세션이 시작될 때 반환되는 세션 UUID
      - `type: 'token'`: AI가 생성하는 응답 토큰
      - `type: 'finish'`: 스트림 종료
      - `type: 'error'`: 오류 발생

**요청 본문**:

- **Content-Type**: `application/json`
  - **스키마**: [`ChatRequest`](#datatype-chatrequest)

**응답**:

| 상태 코드 | 설명                           | Content-Type       | 스키마                                                 |
| --------- | ------------------------------ | ------------------ | ------------------------------------------------------ |
| `200`     | Successful Response            | `application/json` |                                                        |
| `404`     | 채팅 엔드포인트를 찾을 수 없음 | -                  | -                                                      |
| `500`     | 서버 내부 오류                 | -                  | -                                                      |
| `422`     | Validation Error               | `application/json` | [`HTTPValidationError`](#datatype-httpvalidationerror) |

---

### News

#### `POST /api/v1/news/`

**요약**: 온디맨드 뉴스 생성

**설명**: Spring Boot 스케줄러에 의해 호출되는 온디맨드 뉴스 생성 엔드포인트.
Claude 4 Sonnet의 네이티브 웹 검색을 사용하여 최신 무역 뉴스를 생성하고 DB에 저장합니다.

**응답**:

| 상태 코드 | 설명                           | Content-Type       | 스키마                                   |
| --------- | ------------------------------ | ------------------ | ---------------------------------------- |
| `201`     | Successful Response            | `application/json` | [`NewsResponse`](#datatype-newsresponse) |
| `404`     | 뉴스 엔드포인트를 찾을 수 없음 | -                  | -                                        |
| `500`     | 서버 내부 오류                 | -                  | -                                        |

---

### Monitoring

#### `POST /api/v1/monitoring/run-monitoring`

**요약**: Run Monitoring

**설명**: 모니터링이 활성화된 모든 북마크의 최신 변경 사항을 주기적으로 감지하고, 유의미한 업데이트 발생 시 알림 생성 작업을 Redis에 큐잉하는 백그라운드 엔드포인트입니다.

<details>
<summary>I. Producer (생산자: FastAPI) 로직</summary>

> 이 엔드포인트는 알림 작업을 생성하는 '생산자' 역할을 수행합니다.

**주요 처리 순서:**
1.  **분산 락 (Distributed Lock):** Redis (`SET NX`)를 사용하여 여러 인스턴스의 동시 실행을 방지합니다.
2.  **북마크 조회:** `monitoring_active=True`인 모든 북마크를 DB에서 조회합니다.
3.  **병렬 및 속도 제어 처리:**
    -   `asyncio.Semaphore`: LangChain 서비스에 대한 동시 요청 수를 제한하여 과부하를 방지합니다.
    -   `Aiolimiter`: 분당 요청 수를 제어하여 외부 API의 속도 제한(Rate Limit)을 준수합니다.
    -   `Tenacity`: API 호출 실패 시 지수 백오프(Exponential Backoff)를 적용하여 자동으로 재시도합니다.
4.  **업데이트 처리 및 Redis 큐잉 (신뢰성 큐 패턴):**
    -   **DB 저장:** 변경 사항 발견 시, `update_feeds` 테이블에 업데이트 내역을 저장합니다.
    -   **Redis 큐잉:**
        1.  **알림 상세 정보 (Hash):** `HSET` 명령어를 사용하여 `daily_notification:detail:{uuid}` 키에 알림 상세 내용을 저장합니다.
            -   `HSET`: Hash 데이터 구조(Key-Value 맵과 유사)에 여러 필드-값 쌍을 저장하는 명령어입니다.
        2.  **알림 작업 큐 (List):** `LPUSH` 명령어를 사용하여 `daily_notification:queue:{TYPE}` (예: `...:EMAIL`) 키에 처리할 작업의 `uuid`를 추가합니다.
            -   `LPUSH`: List 데이터 구조(Array 또는 LinkedList와 유사)의 맨 앞에 요소를 추가하는 명령어입니다.
</details>

<details>
<summary>II. Consumer (소비자: Spring Boot) 구현 가이드</summary>

> Redis 큐에 쌓인 작업은 Spring Boot와 같은 별도의 워커(Worker) 프로세스가 처리해야 합니다.

**권장 처리 순서 (신뢰성 보장):**
1.  **작업 원자적으로 이동 (`BLMOVE`):** '대기 큐'에서 '처리 중 큐'로 작업을 안전하게 이동시킵니다.
2.  **상세 정보 조회 (`HGETALL`):** 이동시킨 작업 `uuid`를 사용하여 상세 정보를 가져옵니다.
3.  **비즈니스 로직 수행:** 실제 이메일 발송 등 알림 처리를 수행합니다.
4.  **작업 완료 처리 (`LREM`):** 작업이 성공하면 '처리 중 큐'에서 해당 작업을 제거합니다.
5.  **예외 처리:** 오류 발생 시 작업을 '처리 중 큐'에 남겨두어 데이터 유실을 방지합니다.
</details>

<details>
<summary>III. 핵심 Redis 명령어 및 Spring Data Redis 타입 매핑</summary>

> Spring Boot (`RedisTemplate`) 사용 시 각 Redis 명령어와 매핑되는 Java 타입을 명시합니다.

#### **1. `BLMOVE`**
-   **설명:** 리스트의 마지막 요소를 다른 리스트의 첫 번째 요소로 **원자적으로 이동**시키고, 만약 원본 리스트가 비어있으면 지정된 시간 동안 새로운 요소가 추가되기를 기다리는(Blocking) 명령어입니다.
-   **핵심 역할:** 워커가 여러 개 실행되어도 **단 하나의 워커만이 작업을 가져가도록 보장**하며(경쟁 상태 방지), 큐가 비었을 때 불필요한 CPU 사용을 막아줍니다. 작업 유실 방지의 핵심입니다.
-   **Java `RedisTemplate` 반환 타입:** `String`
    -   이동된 작업 `uuid`가 문자열로 반환됩니다. 큐가 비어 타임아웃이 발생하면 `null`이 반환됩니다.
    ```java
    String taskId = redisTemplate.opsForList().move(
        "daily_notification:queue:EMAIL", ListOperations.Direction.RIGHT,
        "daily_notification:processing_queue:EMAIL", ListOperations.Direction.LEFT,
        Duration.ofSeconds(10)
    );
    if (taskId != null) {
        // ... process task
    }
    ```

#### **2. `HGETALL`**
-   **설명:** Hash 데이터 구조에서 모든 필드와 값의 쌍을 가져오는 명령어입니다.
-   **핵심 역할:** 작업 `uuid`에 해당하는 모든 알림 상세 정보(수신자, 메시지 내용 등)를 한 번의 명령어로 조회합니다.
-   **Java `RedisTemplate` 반환 타입:** `Map<Object, Object>` 또는 `Map<String, String>`
    -   조회된 Hash의 필드-값 쌍들이 `Map`으로 반환됩니다. `RedisTemplate` 설정에 따라 타입을 명시적으로 지정할 수 있습니다.
    ```java
    Map<Object, Object> details = redisTemplate.opsForHash().entries("daily_notification:detail:" + taskId);
    String userId = (String) details.get("user_id");
    String message = (String) details.get("message");
    ```

#### **3. `LREM`**
-   **설명:** 리스트에서 지정된 값과 일치하는 요소를 **개수를 지정하여** 제거하는 명령어입니다.
-   **핵심 역할:** 알림 발송을 성공적으로 마친 작업을 '처리 중 큐'에서 **정확히 하나만 제거**하여, 동일한 작업이 중복 처리되는 것을 방지합니다.
-   **Java `RedisTemplate` 반환 타입:** `Long`
    -   제거된 요소의 개수가 반환됩니다. 보통 `1`이 반환되며, `0`이 반환되면 무언가 잘못된 상황(예: 이미 삭제됨)임을 인지할 수 있습니다.
    ```java
    // count: 1 > 앞에서부터 taskId와 일치하는 요소 1개만 제거
    Long removedCount = redisTemplate.opsForList().remove("daily_notification:processing_queue:EMAIL", 1, taskId);
    ```
</details>

**응답**:

| 상태 코드 | 설명                               | Content-Type       | 스키마                                               |
| --------- | ---------------------------------- | ------------------ | ---------------------------------------------------- |
| `200`     | Successful Response                | `application/json` | [`MonitoringResponse`](#datatype-monitoringresponse) |
| `404`     | 모니터링 엔드포인트를 찾을 수 없음 | -                  | -                                                    |
| `500`     | 서버 내부 오류                     | -                  | -                                                    |

---

## 데이터 스키마

### <a id="datatype-chatrequest"></a>ChatRequest

**타입**: `object`

**설명**: /api/v1/chat 엔드포인트에 대한 요청 스키마.
구현계획.md vFinal 및 chat_endpoint_implementation_plan.md v1.0 기준.

**속성**:

| 속성명         | 타입   | 필수 | 설명                                             |
| -------------- | ------ | ---- | ------------------------------------------------ |
| `user_id`      | string |      | 회원 ID. 없으면 비회원으로 간주함.               |
| `session_uuid` | string |      | 기존 채팅 세션의 UUID. 새 채팅 시작 시에는 null. |
| `message`      | string | ✓    | 사용자의 질문 메시지                             |

### <a id="datatype-httpvalidationerror"></a>HTTPValidationError

**타입**: `object`

**속성**:

| 속성명   | 타입                                                    | 필수 | 설명 |
| -------- | ------------------------------------------------------- | ---- | ---- |
| `detail` | Array of [`ValidationError`](#datatype-validationerror) |      |      |

### <a id="datatype-monitoringresponse"></a>MonitoringResponse

**타입**: `object`

**설명**: 모니터링 실행 결과 응답 모델

**속성**:

| 속성명                | 타입    | 필수 | 설명 |
| --------------------- | ------- | ---- | ---- |
| `status`              | string  | ✓    |      |
| `monitored_bookmarks` | integer | ✓    |      |
| `updates_found`       | integer | ✓    |      |
| `lock_status`         | string  | ✓    |      |

### <a id="datatype-newsresponse"></a>NewsResponse

**타입**: `object`

**설명**: 온디맨드 뉴스 생성 결과 응답 모델

**속성**:

| 속성명            | 타입    | 필수 | 설명                            |
| ----------------- | ------- | ---- | ------------------------------- |
| `status`          | string  | ✓    | 작업 성공 여부 (예: "success")  |
| `message`         | string  | ✓    | 처리 결과에 대한 설명 메시지    |
| `generated_count` | integer | ✓    | 생성 및 저장된 뉴스 아이템의 수 |

### <a id="datatype-validationerror"></a>ValidationError

**타입**: `object`

**속성**:

| 속성명 | 타입              | 필수 | 설명 |
| ------ | ----------------- | ---- | ---- |
| `loc`  | Array of `string` | ✓    |      |
| `msg`  | string            | ✓    |      |
| `type` | string            | ✓    |      |
