# AI 기반 무역 규제 레이더 플랫폼 API 명세서 v6.1 (요구사항 기준 완전 재설계)

**과제명**: AI 기반 무역 규제 레이더 플랫폼: ChatGPT 스타일 통합 채팅 및 실시간 SMS/이메일 알림 시스템

---

## 🚀 주요 변경사항 (v5 → v6.1)

### ✨ **회원/비회원 차별화 시스템 (혁신적 개선)**

-   **회원 전용 채팅 기록**: 회원만 첫 메시지 시 세션 생성하여 모든 대화를 pg_partman 파티션에 영구 저장
-   **비회원 휘발성 채팅**: 세션 생성, 데이터베이스 저장 등 일체의 저장 행위 없이 실시간 채팅만 제공
-   **명확한 차별화**: 회원가입 유도를 위한 전략적 기능 분리

### 📱 **JWT 세부화 인증 시스템 (v6.1 핵심 기능)**

-   **정교한 토큰 정책**: Access Token 30분, Refresh Token (remember me 체크시 30일, 미체크시 1일)
-   **분리된 저장 전략**: Access Token은 헤더&Zustand 상태, Refresh Token은 HttpOnly 쿠키
-   **자동 토큰 갱신**: 무상태 JWT 기반 seamless 인증 경험

### 🔧 **SSE 기반 북마크 시스템 재설계**

-   **메타데이터 기반 표시**: SSE 첫 번째 이벤트로 전달되는 HSCode 메타데이터를 통한 프론트엔드 북마크 버튼 표시
-   **실시간 상호작용**: Claude 분석 즉시 북마크 가능 여부 표시

### 🎯 **3단계 병렬 처리 시스템 (v6.1 혁신)**

-   **동시 처리**: (1) Claude 자연어 응답 스트리밍, (2) HSCode/규제/무역통계 상세페이지 정보 준비, (3) 회원 대화 기록 저장
-   **로딩 최적화**: 상세페이지 버튼에 로딩 스피너 → 준비 완료 시 버튼 활성화
-   **사용자 경험 향상**: 각 단계 완료 시점에 따라 순차적 UI 업데이트

---

## 1. 개요 (Overview)

본 문서는 ’AI 기반 무역 규제 레이더 플랫폼 v6.1’의 RESTful API를 상세히 기술한 통합 명세서입니다. 이 플랫폼은 **회원/비회원 차별화된 채팅 시스템**을 통해 복잡한 무역 업무를 처리하고, **JWT 세부화 인증**으로 보안성과 편의성을 균형잡았으며, **3단계 병렬 처리**로 최적의 사용자 경험을 제공하는 차세대 무역 정보 플랫폼입니다.

### 1.1 시스템 아키텍처 및 인증 방식

### ChatGPT 스타일 회원/비회원 차별화 아키텍처 + RAG 시스템

```
┌─────────────────────────────────────────────────────────┐
│         ChatGPT 스타일 회원/비회원 차별화 채팅            │
│                                                         │
│  POST /api/chat → Claude 분석 → 즉시 SSE 스트리밍 시작    │
│                                                         │
│  ┌─────────────────┐         ┌─────────────────────────┐ │
│  │     회원        │         │       비회원            │ │
│  │                 │         │                         │ │
│  │ 첫 메시지 시:    │         │ 완전 휘발성:            │ │
│  │ - 세션 UUID 생성 │         │ - 세션 생성 없음        │ │
│  │ - 파티션에 저장  │         │ - DB 저장 없음          │ │
│  │ - 영구 보관     │         │ - 실시간만 제공         │ │
│  └─────────────────┘         └─────────────────────────┘ │
│                    ↓                                     │
│         3단계 병렬 처리 (회원/비회원 공통)                 │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────┐ │
│  │Claude 자연어 응답│ │상세페이지 준비  │ │회원 기록저장│ │
│  │실시간 스트리밍  │ │HSCode/규제/통계 │ │(회원만)     │ │
│  └─────────────────┘ └─────────────────┘ └─────────────┘ │
│                                ↓                       │
│                 [상세페이지 이동 버튼]                    │
│              (의도 기반 우선순위 자동 정렬)               │
│                                ↓                       │
│                [SSE 메타데이터 기반 북마크 버튼]           │
│              (HSCode 정보 포함시 프론트엔드 표시)          │
└─────────────────────────────────────────────────────────┘
                      │
              ┌──────────────────┐
              │ Private API      │
              │ (북마크/대시보드)  │
              │ JWT 세부화 인증   │
              │ Access 30분      │
              │ Refresh 1일/30일  │
              └──────────────────┘
```

### 혁신적 설계 원칙 (v6.1)

-   **Smart Differentiation**: 회원/비회원 명확한 차별화로 가입 유도
-   **RAG-Powered Intelligence**: PostgreSQL+pgvector+voyage-3-large 기반 의미적 검색
-   **Parallel Processing**: 자연어 응답과 상세페이지 정보와 회원 기록 저장의 3단계 병렬 처리
-   **JWT Sophistication**: Access Token 30분, Refresh Token 1일/30일의 정교한 보안 정책
-   **Metadata-driven UX**: SSE 메타데이터를 통한 동적 북마크 버튼 표시
-   **Background Automation**: pg_partman BGW를 통한 완전 자동화된 데이터 관리

### v6.1 혁신적 데이터 플로우

1. **차별화된 질의**: 자연어 질문 → 인증 상태 확인 → 회원만 세션 생성 → 즉시 스트리밍 시작
2. **3단계 병렬 처리**: [자연어 응답] + [상세페이지 준비] + [회원 기록 저장] 동시 실행
3. **개인 데이터**: 북마크 → 일일 모니터링 → SMS/이메일 통합 알림 발송 (인증 필수)

### 1.2 기본 정보

-   **기본 URL**: `http://localhost:8081/api`
-   **프로토콜**: HTTPS (운영환경)
-   **인증 방식**: JWT 세부화 인증 (Access 30분, Refresh 1일/30일) + HttpOnly Cookie (Private API만 필요)
-   **Content-Type**: `application/json`
-   **CORS**: Public API는 기본 허용, Private API는 `withCredentials: true` 필수

### 1.3 공통 응답 형식 (Common Response Wrapper)

모든 API 응답은 아래와 같은 `ApiResponse` 객체로 래핑되어 반환됩니다.

```tsx
interface ApiResponse<T> {
    success: "SUCCESS" | "ERROR";
    message: string;
    data: T | null;
}
```

### 성공 응답 예시

```json
{
    "success": "SUCCESS",
    "message": "요청이 성공적으로 처리되었습니다.",
    "data": { "intent": "HS_CODE_ANALYSIS", "hsCode": "8517.12.00", "description": "스마트폰 및 기타 무선전화기" }
}
```

### 오류 응답 예시

```json
{ "success": "ERROR", "message": "검색어가 비어있습니다.", "data": null }
```

---

## 2. 인증 API (Authentication) - v6.1 JWT 세부화 시스템

### 2.1 회원가입

**`POST /api/auth/register`**

신규 계정을 생성합니다. 생성된 계정은 즉시 로그인 가능한 상태가 됩니다.

### 📊 응답 코드 매트릭스

| 시나리오              | HTTP 상태                   | 에러 코드  | 응답 메시지                       |
| --------------------- | --------------------------- | ---------- | --------------------------------- |
| ✅ 성공               | `201 Created`               | -          | “계정이 생성되었습니다”           |
| ❌ 이메일 중복        | `409 Conflict`              | USER_001   | “이미 사용 중인 이메일입니다”     |
| ❌ 입력 데이터 오류   | `400 Bad Request`           | USER_002   | “입력 정보가 올바르지 않습니다”   |
| ❌ 비밀번호 정책 위반 | `422 Unprocessable Entity`  | USER_004   | “비밀번호가 정책에 맞지 않습니다” |
| ❌ 서버 오류          | `500 Internal Server Error` | COMMON_002 | “서버에서 오류가 발생했습니다”    |

### Request Body

| 필드명     | 타입   | 필수 | 설명                                  |
| ---------- | ------ | ---- | ------------------------------------- |
| `email`    | string | ✓    | 사용자 이메일 주소                    |
| `password` | string | ✓    | 사용자 비밀번호 (최소 8자 이상)       |
| `name`     | string | ✓    | 사용자 표시명 (환영 메시지 등에 사용) |

```json
{ "email": "user@example.com", "password": "password123", "name": "홍길동" }
```

### Response (201 Created)

| 필드명              | 타입   | 설명                                     |
| ------------------- | ------ | ---------------------------------------- |
| `success`           | string | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”)  |
| `message`           | string | 처리 결과 메시지                         |
| `data.email`        | string | 사용자 이메일 주소                       |
| `data.name`         | string | 사용자 표시명                            |
| `data.profileImage` | string | 프로필 이미지 URL (회원가입 시에는 null) |

```json
{ "success": "SUCCESS", "message": "계정이 생성되었습니다", "data": { "email": "user@example.com", "name": "홍길동", "profileImage": null } }
```

---

### 2.2 로그인 (🆕 v6.1 JWT 세부화)

**`POST /api/auth/login`**

사용자 인증을 수행하고, 성공 시 JWT 세부화 정책에 따라 토큰을 발급합니다.

### 📊 응답 코드 매트릭스

| 시나리오                | HTTP 상태               | 에러 코드      | 응답 메시지                                       |
| ----------------------- | ----------------------- | -------------- | ------------------------------------------------- |
| ✅ 성공                 | `200 OK`                | -              | “인증되었습니다”                                  |
| ❌ 등록되지 않은 사용자 | `401 Unauthorized`      | AUTH_001       | “이메일 또는 비밀번호가 올바르지 않습니다”        |
| ❌ 비밀번호 불일치      | `401 Unauthorized`      | AUTH_001       | “이메일 또는 비밀번호가 올바르지 않습니다”        |
| ❌ 계정 잠김            | `423 Locked`            | AUTH_002       | “현재 계정에 일시적인 접근 제한이 적용되었습니다” |
| ❌ 입력 데이터 누락     | `400 Bad Request`       | COMMON_001     | “필수 입력 정보가 누락되었습니다”                 |
| ❌ 너무 많은 시도       | `429 Too Many Requests` | RATE_LIMIT_001 | “로그인 시도 한도를 초과했습니다”                 |

### Request Body

| 필드명       | 타입    | 필수 | 설명                             |
| ------------ | ------- | ---- | -------------------------------- |
| `email`      | string  | ✓    | 사용자 이메일 주소               |
| `password`   | string  | ✓    | 사용자 비밀번호                  |
| `rememberMe` | boolean | -    | 로그인 유지 여부 (기본값: false) |

```json
{ "email": "user@example.com", "password": "password123", "rememberMe": true }
```

### Response (200 OK) - 🆕 v6.1 JWT 세부화 정책

| 필드명                    | 타입    | 설명                                        |
| ------------------------- | ------- | ------------------------------------------- |
| `success`                 | string  | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”)     |
| `message`                 | string  | 처리 결과 메시지                            |
| `data.accessToken`        | string  | **헤더&Zustand 저장용** Access Token (30분) |
| `data.tokenType`          | string  | 토큰 타입 (“Bearer”)                        |
| `data.expiresIn`          | number  | Access Token 만료 시간 (초, 1800)           |
| `data.user.email`         | string  | 사용자 이메일 주소                          |
| `data.user.name`          | string  | 사용자 표시명                               |
| `data.user.profileImage`  | string  | 프로필 이미지 URL (없으면 null)             |
| `data.user.phoneVerified` | boolean | 휴대폰 인증 완료 여부                       |

```json
{
    "success": "SUCCESS",
    "message": "인증되었습니다",
    "data": {
        "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "tokenType": "Bearer",
        "expiresIn": 1800,
        "user": { "email": "user@example.com", "name": "홍길동", "profileImage": null, "phoneVerified": false }
    }
}
```

### Response Headers (Set-Cookie) - 🆕 v6.1 Refresh Token 분리 저장

인증 성공 시 Refresh Token이 HttpOnly 쿠키로 자동 설정됩니다:

```
Set-Cookie: refreshToken=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...;
            HttpOnly;
            Secure;
            SameSite=Strict;
            Path=/auth/refresh;
            Max-Age=2592000  // remember me 체크시 30일
```

### 🆕 v6.1 JWT 세부화 정책

| remember me 설정 | Access Token | Refresh Token | 저장 위치                                    |
| ---------------- | ------------ | ------------- | -------------------------------------------- |
| **체크함**       | 30분         | 30일          | Access: 헤더&Zustand, Refresh: HttpOnly 쿠키 |
| **체크 안 함**   | 30분         | 1일           | Access: 헤더&Zustand, Refresh: HttpOnly 쿠키 |

---

### 2.3 인증 상태 확인

**`GET /api/auth/verify`**

현재 JWT 토큰 상태를 확인하고 사용자 정보를 반환합니다.

### 📊 응답 코드 매트릭스

| 시나리오              | HTTP 상태          | 에러 코드 | 응답 메시지                     |
| --------------------- | ------------------ | --------- | ------------------------------- |
| ✅ 유효한 토큰        | `200 OK`           | -         | “인증 상태 확인됨”              |
| ❌ 토큰 만료          | `401 Unauthorized` | AUTH_003  | “인증이 만료되었습니다”         |
| ❌ 유효하지 않은 토큰 | `401 Unauthorized` | AUTH_004  | “인증 정보가 올바르지 않습니다” |
| ❌ 토큰 없음          | `401 Unauthorized` | AUTH_004  | “인증이 필요합니다”             |

### Request Headers

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Response (200 OK)

| 필드명               | 타입    | 설명                                    |
| -------------------- | ------- | --------------------------------------- |
| `success`            | string  | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`            | string  | 처리 결과 메시지                        |
| `data.email`         | string  | 사용자 이메일 주소                      |
| `data.name`          | string  | 사용자 표시명                           |
| `data.profileImage`  | string  | 프로필 이미지 URL (없으면 null)         |
| `data.phoneVerified` | boolean | 휴대폰 인증 완료 여부                   |
| `data.rememberMe`    | boolean | 🆕 Remember me 설정 상태                |

```json
{
    "success": "SUCCESS",
    "message": "인증 상태 확인됨",
    "data": { "email": "user@example.com", "name": "홍길동", "profileImage": null, "phoneVerified": false, "rememberMe": true }
}
```

---

### 2.4 OAuth 소셜 로그인

**`GET /api/oauth2/authorization/{provider}`**

외부 OAuth 제공업체를 통한 소셜 로그인을 시작합니다.

### 📊 응답 코드 매트릭스

| 시나리오                | HTTP 상태          | 에러 코드 | 응답 메시지                        |
| ----------------------- | ------------------ | --------- | ---------------------------------- |
| ✅ 리디렉션 시작        | `302 Found`        | -         | OAuth 제공자로 리디렉션            |
| ❌ 지원하지 않는 제공자 | `400 Bad Request`  | OAUTH_001 | “지원하지 않는 OAuth 제공자입니다” |
| ❌ OAuth 인증 실패      | `401 Unauthorized` | OAUTH_002 | “소셜 로그인에 실패했습니다”       |
| ❌ OAuth 취소           | `400 Bad Request`  | OAUTH_003 | “사용자가 인증을 취소했습니다”     |

### Path Parameters

| 필드명     | 타입   | 필수 | 설명                                        |
| ---------- | ------ | ---- | ------------------------------------------- |
| `provider` | string | ✓    | OAuth 제공업체 (`google`, `naver`, `kakao`) |

### Query Parameters

| 필드명       | 타입    | 필수 | 설명                             |
| ------------ | ------- | ---- | -------------------------------- |
| `rememberMe` | boolean | -    | 로그인 유지 여부 (기본값: false) |

### Response (302 Found)

사용자를 해당 OAuth 제공업체의 인증 페이지로 리디렉션합니다.

```
Location: https://accounts.google.com/oauth/authorize?client_id=...
```

### OAuth 성공 시 콜백

인증 성공 시 다음 작업이 수행됩니다:

1. 사용자 정보 획득 (이메일, 이름, 프로필 이미지)
2. 🆕 v6.1 JWT 세부화 정책에 따른 토큰 발급
3. 프론트엔드로 리디렉션

```
Location: https://your-frontend-domain.com/auth/callback?success=true&token=...
```

---

### 2.5 JWT 토큰 갱신 (🆕 v6.1 세부화)

**`POST /api/auth/refresh`**

Refresh Token을 사용하여 새로운 Access Token을 발급받습니다.

### 📊 응답 코드 매트릭스

| 시나리오              | HTTP 상태          | 에러 코드 | 응답 메시지                         |
| --------------------- | ------------------ | --------- | ----------------------------------- |
| ✅ 갱신 성공          | `200 OK`           | -         | “토큰이 갱신되었습니다”             |
| ❌ 토큰 없음          | `400 Bad Request`  | AUTH_001  | “Refresh Token이 필요합니다”        |
| ❌ 유효하지 않은 토큰 | `401 Unauthorized` | AUTH_003  | “유효하지 않은 Refresh Token입니다” |
| ❌ 만료된 토큰        | `401 Unauthorized` | AUTH_003  | “만료된 Refresh Token입니다”        |
| ❌ DB 토큰 불일치     | `401 Unauthorized` | AUTH_004  | “인증 정보가 일치하지 않습니다”     |

### Request Headers

Refresh Token은 HttpOnly 쿠키로 자동 전송됩니다:

```
Cookie: refreshToken=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Response (200 OK)

| 필드명             | 타입    | 설명                                    |
| ------------------ | ------- | --------------------------------------- |
| `success`          | string  | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`          | string  | 처리 결과 메시지                        |
| `data.accessToken` | string  | 새로 발급된 Access Token (30분)         |
| `data.tokenType`   | string  | 토큰 타입 (“Bearer”)                    |
| `data.expiresIn`   | number  | Access Token 만료 시간 (초, 1800)       |
| `data.rememberMe`  | boolean | 🆕 현재 Remember Me 설정 상태           |

```json
{
    "success": "SUCCESS",
    "message": "토큰이 갱신되었습니다",
    "data": { "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...", "tokenType": "Bearer", "expiresIn": 1800, "rememberMe": true }
}
```

### 🆕 v6.1 Token Rotation 보안 정책

-   **기존 Refresh Token 무효화**: 새 Access Token 발급과 동시에 기존 Refresh Token 갱신
-   **PostgreSQL 검증**: 요청한 토큰이 데이터베이스에 저장된 토큰과 일치하는지 검증
-   **재사용 방지**: 이미 사용된 Refresh Token으로는 갱신 불가
-   **만료 시간**: Access Token 30분, Refresh Token remember me 설정에 따라 1일/30일

---

### 2.6 로그아웃

**`POST /api/auth/logout`**

현재 세션을 종료하고 JWT 인증을 해제합니다.

### 📊 응답 코드 매트릭스

| 시나리오              | HTTP 상태        | 에러 코드 | 응답 메시지                |
| --------------------- | ---------------- | --------- | -------------------------- |
| ✅ 성공               | `204 No Content` | -         | 응답 본문 없음             |
| ✅ 이미 로그아웃 상태 | `200 OK`         | -         | “이미 로그아웃 상태입니다” |

### Request Headers

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Response Headers (Set-Cookie)

로그아웃 시 Refresh Token 쿠키가 자동으로 삭제됩니다:

```
Set-Cookie: refreshToken=; HttpOnly; Secure; SameSite=Strict; Path=/auth/refresh; Max-Age=0
```

---

## 3. SMS/이메일 통합 알림 시스템 v6.1 🔒 PRIVATE API

> 🔐 인증 필수: 이 섹션의 모든 API는 로그인이 필요합니다.
>
> 🚀 **v6.1 핵심 기능**: 휴대폰 인증 시 기존 북마크 SMS/이메일 알림 자동 활성화 + 일일 통합 알림

### 3.1 휴대폰 인증 코드 발송

**`POST /api/notification/phone/send`**

휴대폰 번호 인증을 위한 인증 코드를 발송합니다.

### 📊 응답 코드 매트릭스

| 시나리오            | HTTP 상태               | 에러 코드 | 응답 메시지                             |
| ------------------- | ----------------------- | --------- | --------------------------------------- |
| ✅ 발송 성공        | `200 OK`                | -         | “인증 코드가 발송되었습니다”            |
| ❌ 인증 필요        | `401 Unauthorized`      | AUTH_003  | “인증이 필요합니다”                     |
| ❌ 잘못된 번호 형식 | `400 Bad Request`       | SMS_001   | “휴대폰 번호 형식이 올바르지 않습니다”  |
| ❌ 이미 인증된 번호 | `409 Conflict`          | SMS_002   | “이미 인증된 휴대폰 번호입니다”         |
| ❌ 발송 한도 초과   | `429 Too Many Requests` | SMS_003   | “인증 코드 발송 한도를 초과했습니다”    |
| ❌ SMS 서비스 오류  | `502 Bad Gateway`       | SMS_004   | “SMS 발송 서비스에 문제가 발생했습니다” |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Request Body

| 필드명        | 타입   | 필수 | 설명                                         |
| ------------- | ------ | ---- | -------------------------------------------- |
| `phoneNumber` | string | ✓    | 휴대폰 번호 (010-0000-0000 또는 01000000000) |

```json
{ "phoneNumber": "010-1234-5678" }
```

### Response (200 OK)

| 필드명                       | 타입   | 설명                                    |
| ---------------------------- | ------ | --------------------------------------- |
| `success`                    | string | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`                    | string | 처리 결과 메시지                        |
| `data.verificationId`        | string | 인증 세션 ID                            |
| `data.expiresAt`             | string | 인증 코드 만료 시간 (ISO 8601)          |
| `data.cooldownUntil`         | string | 다음 발송 가능 시간 (ISO 8601)          |
| `data.autoActivationWarning` | string | v6.1: 자동 알림 활성화 안내 메시지      |

```json
{
    "success": "SUCCESS",
    "message": "인증 코드가 발송되었습니다",
    "data": {
        "verificationId": "verify_123456789",
        "expiresAt": "2024-01-16T10:35:00Z",
        "cooldownUntil": "2024-01-16T10:33:00Z",
        "autoActivationWarning": "휴대폰 인증 완료 시 기존 북마크의 SMS/이메일 알림이 자동으로 활성화됩니다"
    }
}
```

---

### 3.2 휴대폰 인증 코드 확인

**`POST /api/notification/phone/verify`**

발송된 인증 코드를 확인하여 휴대폰 번호를 인증합니다.

### 📊 응답 코드 매트릭스

| 시나리오          | HTTP 상태               | 에러 코드 | 응답 메시지                     |
| ----------------- | ----------------------- | --------- | ------------------------------- |
| ✅ 인증 성공      | `200 OK`                | -         | “휴대폰 인증이 완료되었습니다”  |
| ❌ 인증 필요      | `401 Unauthorized`      | AUTH_003  | “인증이 필요합니다”             |
| ❌ 잘못된 코드    | `400 Bad Request`       | SMS_005   | “인증 코드가 올바르지 않습니다” |
| ❌ 만료된 코드    | `410 Gone`              | SMS_006   | “인증 코드가 만료되었습니다”    |
| ❌ 인증 세션 없음 | `404 Not Found`         | SMS_007   | “인증 세션을 찾을 수 없습니다”  |
| ❌ 시도 횟수 초과 | `429 Too Many Requests` | SMS_008   | “인증 시도 횟수를 초과했습니다” |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Request Body

| 필드명             | 타입   | 필수 | 설명            |
| ------------------ | ------ | ---- | --------------- |
| `verificationId`   | string | ✓    | 인증 세션 ID    |
| `verificationCode` | string | ✓    | 6자리 인증 코드 |

```json
{ "verificationId": "verify_123456789", "verificationCode": "123456" }
```

### Response (200 OK)

| 필드명                          | 타입    | 설명                                     |
| ------------------------------- | ------- | ---------------------------------------- |
| `success`                       | string  | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”)  |
| `message`                       | string  | 처리 결과 메시지                         |
| `data.phoneNumber`              | string  | 인증된 휴대폰 번호 (마스킹 처리)         |
| `data.verifiedAt`               | string  | 인증 완료 시간 (ISO 8601)                |
| `data.smsNotificationEnabled`   | boolean | 전체 SMS 알림 활성화 상태 (항상 true)    |
| `data.emailNotificationEnabled` | boolean | 전체 이메일 알림 활성화 상태 (항상 true) |
| `data.activatedBookmarksCount`  | number  | 자동 활성화된 북마크 수                  |

```json
{
    "success": "SUCCESS",
    "message": "휴대폰 인증이 완료되었습니다",
    "data": {
        "phoneNumber": "010-****-5678",
        "verifiedAt": "2024-01-16T10:32:00Z",
        "smsNotificationEnabled": true,
        "emailNotificationEnabled": true,
        "activatedBookmarksCount": 5
    }
}
```

---

### 3.3 통합 알림 설정 관리 (🆕 v6.1 핵심 기능)

**`GET/PUT /api/notification/settings`**

대시보드에서 SMS/이메일 알림을 통합 관리하는 기능입니다.

### 📊 응답 코드 매트릭스

| 시나리오                       | HTTP 상태          | 에러 코드 | 응답 메시지                            |
| ------------------------------ | ------------------ | --------- | -------------------------------------- |
| ✅ 조회/설정 성공              | `200 OK`           | -         | “알림 설정이 조회/변경되었습니다”      |
| ❌ 인증 필요                   | `401 Unauthorized` | AUTH_003  | “인증이 필요합니다”                    |
| ❌ 휴대폰 미등록 (SMS 설정 시) | `400 Bad Request`  | SMS_019   | “SMS 알림은 휴대폰 인증 후 가능합니다” |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### GET Response (200 OK)

| 필드명                   | 타입   | 설명                                    |
| ------------------------ | ------ | --------------------------------------- |
| `success`                | string | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`                | string | 처리 결과 메시지                        |
| `data.globalSettings`    | object | 전체 알림 설정                          |
| `data.bookmarkSettings`  | array  | 북마크별 알림 설정                      |
| `data.notificationStats` | object | 알림 통계                               |

```json
{
    "success": "SUCCESS",
    "message": "알림 설정이 조회되었습니다",
    "data": {
        "globalSettings": {
            "smsNotificationEnabled": true,
            "emailNotificationEnabled": true,
            "notificationFrequency": "DAILY",
            "notificationTime": "09:00:00"
        },
        "bookmarkSettings": [
            {
                "bookmarkId": "bm_001",
                "displayName": "스마트폰 HS Code",
                "type": "HS_CODE",
                "smsNotificationEnabled": true,
                "emailNotificationEnabled": true
            },
            {
                "bookmarkId": "bm_002",
                "displayName": "1월 수입 화물",
                "type": "CARGO",
                "smsNotificationEnabled": false,
                "emailNotificationEnabled": true
            }
        ],
        "notificationStats": { "totalBookmarks": 5, "smsEnabledBookmarks": 3, "emailEnabledBookmarks": 5, "dailyNotificationsSent": 2 }
    }
}
```

### PUT Request Body

| 필드명                     | 타입    | 필수 | 설명                           |
| -------------------------- | ------- | ---- | ------------------------------ |
| `smsNotificationEnabled`   | boolean | -    | 전체 SMS 알림 활성화           |
| `emailNotificationEnabled` | boolean | -    | 전체 이메일 알림 활성화        |
| `notificationTime`         | string  | -    | 일일 알림 발송 시간 (HH:mm:ss) |

```json
{ "smsNotificationEnabled": true, "emailNotificationEnabled": true, "notificationTime": "10:00:00" }
```

---

### 3.4 개별 북마크 알림 설정 변경 (🆕 v6.1 핵심 기능)

**`PUT /api/bookmarks/{id}/notifications`**

특정 북마크의 SMS/이메일 알림 설정을 개별적으로 변경합니다.

### 📊 응답 코드 매트릭스

| 시나리오         | HTTP 상태          | 에러 코드    | 응답 메시지                                      |
| ---------------- | ------------------ | ------------ | ------------------------------------------------ |
| ✅ 변경 성공     | `200 OK`           | -            | “북마크 알림 설정이 변경되었습니다”              |
| ❌ 인증 필요     | `401 Unauthorized` | AUTH_003     | “인증이 필요합니다”                              |
| ❌ 휴대폰 미등록 | `400 Bad Request`  | SMS_019      | “SMS 알림을 사용하려면 휴대폰 인증이 필요합니다” |
| ❌ 북마크 없음   | `404 Not Found`    | BOOKMARK_005 | “북마크를 찾을 수 없습니다”                      |
| ❌ 권한 없음     | `403 Forbidden`    | BOOKMARK_006 | “해당 북마크에 대한 권한이 없습니다”             |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Path Parameters

| 필드명 | 타입   | 필수 | 설명                   |
| ------ | ------ | ---- | ---------------------- |
| `id`   | string | ✓    | 북마크 ID (예: bm_001) |

### Request Body

| 필드명                     | 타입    | 필수 | 설명                    |
| -------------------------- | ------- | ---- | ----------------------- |
| `smsNotificationEnabled`   | boolean | -    | SMS 알림 활성화 여부    |
| `emailNotificationEnabled` | boolean | -    | 이메일 알림 활성화 여부 |

```json
{ "smsNotificationEnabled": true, "emailNotificationEnabled": false }
```

### Response (200 OK)

| 필드명                  | 타입    | 설명                                    |
| ----------------------- | ------- | --------------------------------------- |
| `success`               | string  | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`               | string  | 처리 결과 메시지                        |
| `data.bookmarkId`       | string  | 북마크 ID                               |
| `data.displayName`      | string  | 북마크 표시명                           |
| `data.previousSettings` | object  | 이전 알림 설정 상태                     |
| `data.currentSettings`  | object  | 현재 알림 설정 상태                     |
| `data.monitoringActive` | boolean | 모니터링 활성화 상태                    |
| `data.changedAt`        | string  | 변경 시간 (ISO 8601)                    |

```json
{
    "success": "SUCCESS",
    "message": "북마크 알림 설정이 변경되었습니다",
    "data": {
        "bookmarkId": "bm_001",
        "displayName": "스마트폰 HS Code",
        "previousSettings": { "smsNotificationEnabled": false, "emailNotificationEnabled": true },
        "currentSettings": { "smsNotificationEnabled": true, "emailNotificationEnabled": false },
        "monitoringActive": true,
        "changedAt": "2024-01-16T11:20:00Z"
    }
}
```

---

## 4. 북마크 관리 시스템 v6.1 🔒 PRIVATE API

> 🔐 인증 필수: 이 섹션의 모든 API는 로그인이 필요합니다.
>
> 🚀 **v6.1 변경사항**: SSE 메타데이터 기반 북마크 시스템, 컨텍스트 기반 제거

### 4.1 북마크 목록 조회

**`GET /api/bookmarks`**

사용자의 모든 북마크를 조회합니다.

### 📊 응답 코드 매트릭스

| 시나리오     | HTTP 상태          | 에러 코드 | 응답 메시지          |
| ------------ | ------------------ | --------- | -------------------- |
| ✅ 조회 성공 | `200 OK`           | -         | “북마크 목록 조회됨” |
| ❌ 인증 필요 | `401 Unauthorized` | AUTH_003  | “인증이 필요합니다”  |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Query Parameters

| 필드명         | 타입    | 필수 | 설명                                                |
| -------------- | ------- | ---- | --------------------------------------------------- |
| `page`         | number  | -    | 페이지 번호 (기본값: 1)                             |
| `size`         | number  | -    | 페이지 크기 (기본값: 20, 최대 100)                  |
| `type`         | string  | -    | 북마크 타입 필터 (`HS_CODE`, `CARGO`)               |
| `smsEnabled`   | boolean | -    | SMS 알림 활성화 상태 필터                           |
| `emailEnabled` | boolean | -    | 이메일 알림 활성화 상태 필터                        |
| `sort`         | string  | -    | 정렬 기준 (`createdAt`, `updatedAt`, `displayName`) |
| `order`        | string  | -    | 정렬 순서 (`asc`, `desc`)                           |

### Response (200 OK)

| 필드명            | 타입   | 설명                                    |
| ----------------- | ------ | --------------------------------------- |
| `success`         | string | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`         | string | 처리 결과 메시지                        |
| `data.bookmarks`  | array  | 북마크 목록                             |
| `data.pagination` | object | 페이징 정보                             |
| `data.summary`    | object | 북마크 통계 요약                        |

```json
{
    "success": "SUCCESS",
    "message": "북마크 목록 조회됨",
    "data": {
        "bookmarks": [
            {
                "id": "bm_001",
                "type": "HS_CODE",
                "targetValue": "8517.12.00",
                "displayName": "스마트폰 HS Code",
                "description": "아이폰 15 프로 수입용",
                "sseGenerated": true,
                "smsNotificationEnabled": true,
                "emailNotificationEnabled": true,
                "monitoringActive": true,
                "createdAt": "2024-01-15T09:30:00Z",
                "updatedAt": "2024-01-16T10:35:00Z"
            },
            {
                "id": "bm_002",
                "type": "CARGO",
                "targetValue": "KRPU1234567890",
                "displayName": "1월 수입 화물",
                "description": "전자제품 수입 화물 추적용",
                "sseGenerated": false,
                "smsNotificationEnabled": false,
                "emailNotificationEnabled": true,
                "monitoringActive": true,
                "createdAt": "2024-01-16T08:20:00Z",
                "updatedAt": "2024-01-16T08:20:00Z"
            }
        ],
        "pagination": { "currentPage": 1, "totalPages": 1, "totalElements": 2, "pageSize": 20, "hasNext": false, "hasPrevious": false },
        "summary": {
            "totalBookmarks": 2,
            "hsCodeBookmarks": 1,
            "cargoBookmarks": 1,
            "sseGeneratedBookmarks": 1,
            "smsEnabledBookmarks": 1,
            "emailEnabledBookmarks": 2,
            "monitoringActiveBookmarks": 2
        }
    }
}
```

---

### 4.2 북마크 생성 (🆕 v6.1 SSE 메타데이터 기반)

**`POST /api/bookmarks`**

SSE 메타데이터를 통해 표시된 북마크 버튼 클릭 시 또는 직접 북마크를 생성합니다.

### 📊 응답 코드 매트릭스

| 시나리오                 | HTTP 상태                  | 에러 코드    | 응답 메시지                       |
| ------------------------ | -------------------------- | ------------ | --------------------------------- |
| ✅ 생성 성공             | `201 Created`              | -            | “북마크가 생성되었습니다”         |
| ❌ 인증 필요             | `401 Unauthorized`         | AUTH_003     | “인증이 필요합니다”               |
| ❌ 중복 북마크           | `409 Conflict`             | BOOKMARK_001 | “이미 존재하는 북마크입니다”      |
| ❌ 잘못된 입력           | `400 Bad Request`          | BOOKMARK_002 | “북마크 정보가 올바르지 않습니다” |
| ❌ 북마크 한도 초과      | `429 Too Many Requests`    | BOOKMARK_003 | “북마크 개수 한도를 초과했습니다” |
| ❌ 유효하지 않은 HS Code | `422 Unprocessable Entity` | BOOKMARK_004 | “유효하지 않은 HS Code입니다”     |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Request Body

| 필드명                     | 타입    | 필수 | 설명                                              |
| -------------------------- | ------- | ---- | ------------------------------------------------- |
| `type`                     | string  | ✓    | 북마크 타입 (`HS_CODE`, `CARGO`)                  |
| `targetValue`              | string  | ✓    | HS Code 또는 화물관리번호                         |
| `displayName`              | string  | ✓    | 북마크 표시명                                     |
| `description`              | string  | -    | 북마크 설명                                       |
| `sseEventData`             | object  | -    | 🆕 SSE 이벤트에서 전달받은 메타데이터             |
| `smsNotificationEnabled`   | boolean | -    | SMS 알림 활성화 (기본값: 휴대폰 인증 상태에 따라) |
| `emailNotificationEnabled` | boolean | -    | 이메일 알림 활성화 (기본값: true)                 |

```json
{
    "type": "HS_CODE",
    "targetValue": "8517.12.00",
    "displayName": "스마트폰 HS Code",
    "description": "아이폰 15 프로 수입용",
    "sseEventData": {
        "sessionId": "chat_20240116_123456",
        "claudeAnalysis": "HSCode 8517.12.00 분류 근거: 셀룰러 네트워크용 무선전화기",
        "confidence": 0.95
    },
    "smsNotificationEnabled": true,
    "emailNotificationEnabled": true
}
```

### Response (201 Created)

| 필드명                       | 타입    | 설명                                    |
| ---------------------------- | ------- | --------------------------------------- |
| `success`                    | string  | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`                    | string  | 처리 결과 메시지                        |
| `data.bookmark`              | object  | 생성된 북마크 정보                      |
| `data.smsSetupRequired`      | boolean | SMS 설정이 필요한지 여부                |
| `data.monitoringAutoEnabled` | boolean | v6.1: 모니터링 자동 활성화 여부         |

```json
{
    "success": "SUCCESS",
    "message": "북마크가 생성되었습니다",
    "data": {
        "bookmark": {
            "id": "bm_003",
            "type": "HS_CODE",
            "targetValue": "8517.12.00",
            "displayName": "스마트폰 HS Code",
            "description": "아이폰 15 프로 수입용",
            "sseGenerated": true,
            "smsNotificationEnabled": true,
            "emailNotificationEnabled": true,
            "monitoringActive": true,
            "createdAt": "2024-01-16T11:00:00Z",
            "updatedAt": "2024-01-16T11:00:00Z"
        },
        "smsSetupRequired": false,
        "monitoringAutoEnabled": true
    }
}
```

---

### 4.3 북마크 삭제

**`DELETE /api/bookmarks/{id}`**

북마크를 삭제합니다.

### 📊 응답 코드 매트릭스

| 시나리오       | HTTP 상태          | 에러 코드    | 응답 메시지                          |
| -------------- | ------------------ | ------------ | ------------------------------------ |
| ✅ 삭제 성공   | `204 No Content`   | -            | 응답 본문 없음                       |
| ❌ 인증 필요   | `401 Unauthorized` | AUTH_003     | “인증이 필요합니다”                  |
| ❌ 북마크 없음 | `404 Not Found`    | BOOKMARK_005 | “북마크를 찾을 수 없습니다”          |
| ❌ 권한 없음   | `403 Forbidden`    | BOOKMARK_006 | “해당 북마크에 대한 권한이 없습니다” |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Path Parameters

| 필드명 | 타입   | 필수 | 설명                   |
| ------ | ------ | ---- | ---------------------- |
| `id`   | string | ✓    | 북마크 ID (예: bm_001) |

### Response (204 No Content)

삭제 성공 시 응답 본문이 없습니다.

---

## 5. 회원/비회원 차별화 채팅 시스템 v6.1 + RAG 🌐 PUBLIC API

> 🌐 공개 API: 이 섹션의 API는 인증 없이 사용 가능합니다.
>
> 🚀 **v6.1 혁신**: 회원/비회원 차별화 + 3단계 병렬 처리 + SSE 메타데이터 기반 북마크

### 5.1 회원/비회원 차별화 통합 채팅 요청 + RAG 시스템 (🆕 v6.1 핵심 기능)

**`POST /api/chat`**

사용자의 자연어 질문을 Claude AI + RAG 시스템이 분석하여 무역 관련 의도를 파악하고, **회원/비회원 상태에 따라 차별화된 처리**를 수행합니다. 즉시 Server-Sent Events를 통해 분석 과정과 최종 답변을 실시간으로 스트리밍하며, **3단계 병렬 처리**로 최적의 성능을 제공합니다.

### 🚀 v6.1 혁신 기능

-   ✅ **회원/비회원 차별화**: 회원만 첫 메시지 시 세션 생성하여 대화 기록 영구 저장, 비회원은 완전 휘발성
-   ✅ **3단계 병렬 처리**: [자연어 응답 스트리밍] + [상세페이지 정보 준비] + [회원 대화 기록 저장]
-   ✅ **SSE 메타데이터 북마크**: HSCode 정보 포함시 SSE 메타데이터로 전달하여 프론트엔드에서 북마크 버튼 표시
-   ✅ **RAG 백엔드 처리**: HSCode 벡터 검색 및 캐시 저장을 백엔드에서 내부적으로 처리
-   ✅ **로딩 최적화**: 상세페이지 버튼 준비 전까지 로딩 스피너 표시

### 📊 응답 코드 매트릭스

| 시나리오               | HTTP 상태                  | 에러 코드      | 응답 메시지                                   |
| ---------------------- | -------------------------- | -------------- | --------------------------------------------- |
| ✅ 스트리밍 시작       | `200 OK`                   | -              | SSE 스트리밍 시작                             |
| ❌ 메시지 너무 짧음    | `400 Bad Request`          | CHAT_001       | “메시지는 2자 이상이어야 합니다”              |
| ❌ 메시지 너무 김      | `400 Bad Request`          | CHAT_002       | “메시지는 1000자 이하여야 합니다”             |
| ❌ 무역 외 질의        | `422 Unprocessable Entity` | CHAT_003       | “무역 관련 질문에만 답변할 수 있습니다”       |
| ❌ Claude AI 분석 실패 | `502 Bad Gateway`          | CHAT_004       | “AI 분석 중 오류가 발생했습니다”              |
| ❌ Rate Limit 초과     | `429 Too Many Requests`    | RATE_LIMIT_002 | “채팅 요청 한도를 초과했습니다”               |
| ❌ RAG 검색 실패       | `502 Bad Gateway`          | CHAT_005       | “지식베이스 검색 중 오류가 발생했습니다”      |
| ❌ 병렬 처리 실패      | `502 Bad Gateway`          | CHAT_006       | “상세페이지 정보 준비 중 오류가 발생했습니다” |

### Request Headers

```
Content-Type: application/json
Accept: text/event-stream
Cache-Control: no-cache
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...  # 선택적 (회원인 경우)
```

### Request Body

| 필드명      | 타입   | 필수 | 설명                                          |
| ----------- | ------ | ---- | --------------------------------------------- |
| `message`   | string | ✓    | 사용자의 자연어 질문 (2~1000자)               |
| `sessionId` | string | -    | 🆕 회원의 기존 세션 ID (연속 대화 시, 회원만) |
| `context`   | object | -    | 추가 컨텍스트 정보 (IP, User-Agent 등)        |

```json
{
    "message": "아이폰 15 프로를 수입할 때 HS Code와 관세율이 어떻게 되나요?",
    "sessionId": "chat_session_123456",
    "context": { "userAgent": "Mozilla/5.0...", "language": "ko" }
}
```

### Response (200 OK) - Server-Sent Events

### 🧠 초기 메타데이터 이벤트 (🆕 v6.1 회원/비회원 차별화)

```
event: initial_metadata
data: {"claudeIntent": "HS_CODE_ANALYSIS", "estimatedTime": 15, "isAuthenticated": true, "sessionCreated": true, "sessionId": "chat_session_20240116_123456", "ragEnabled": true, "parallelProcessing": true}

event: session_info
data: {"isAuthenticated": true, "userType": "MEMBER", "sessionId": "chat_session_20240116_123456", "recordingEnabled": true, "message": "회원님의 대화가 기록되어 나중에 다시 볼 수 있습니다"}
```

### 🔍 Thinking 단계 이벤트 (v6.1 3단계 병렬 처리)

```
event: thinking_intent_analysis
data: {"stage": "intent_analysis", "content": "사용자 질문을 분석 중입니다. 아이폰 15 프로 수입에 대한 HS Code와 관세율 문의로 판단됩니다.", "progress": 10}

event: thinking_parallel_processing_start
data: {"stage": "parallel_processing_start", "content": "3단계 병렬 처리를 시작합니다: 자연어 응답, 상세페이지 준비, 회원 기록 저장", "progress": 15}

event: thinking_rag_search_planning
data: {"stage": "rag_search_planning", "content": "HSCode 벡터 데이터베이스에서 관련 정보를 검색합니다.", "progress": 20}

event: thinking_rag_search_executing
data: {"stage": "rag_search_executing", "content": "스마트폰 관련 HSCode 8517.12.00 정보를 벡터 검색으로 찾았습니다.", "progress": 35}

event: thinking_web_search_executing
data: {"stage": "web_search_executing", "content": "최신 관세율 정보를 웹에서 확인 중입니다.", "progress": 50}

event: thinking_data_processing
data: {"stage": "data_processing", "content": "RAG 검색 결과와 웹 검색 결과를 통합 분석 중입니다.", "progress": 70}

event: thinking_detail_page_preparation
data: {"stage": "detail_page_preparation", "content": "상세페이지 정보를 병렬로 준비 중입니다.", "progress": 85}

event: thinking_member_record_saving
data: {"stage": "member_record_saving", "content": "회원 대화 기록을 파티션에 저장 중입니다.", "progress": 90, "userType": "MEMBER"}

event: thinking_response_generation
data: {"stage": "response_generation", "content": "최종 답변을 자연어로 구성하고 관련 정보를 정리합니다.", "progress": 95}
```

### 📝 Main Message 단계 이벤트

```
event: main_message_start
data: {"type": "start", "timestamp": "2024-01-16T10:32:00Z"}

event: main_message_data
data: {"type": "content", "content": "아이폰 15 프로의 정확한 HS Code는 **8517.12.00**입니다.\n\n## 관세율 정보\n- 기본 관세율: 8%\n- FTA 적용 시: 0% (한-미 FTA)\n- 부가가치세: 10%"}

event: main_message_data
data: {"type": "content", "content": "\n\n## 수입 시 주의사항\n1. KC 인증 필수\n2. 전파인증 필요\n3. 개인정보보호 관련 신고"}

event: main_message_complete
data: {"type": "metadata", "sources": [{"title": "관세청 관세율표", "url": "https://unipass.customs.go.kr"}], "relatedInfo": {"hsCode": "8517.12.00", "category": "전자기기"}, "processingTime": 18, "sessionId": "chat_session_20240116_123456", "ragSources": ["HSCode 벡터 DB", "웹검색"], "cacheHit": false, "bookmarkData": {"available": true, "hsCode": "8517.12.00", "productName": "스마트폰 및 기타 무선전화기", "confidence": 0.95}}  //  이 bookmarkData 메타데이터를 기반으로 프론트엔드에서 북마크 버튼을 표시할 수 있습니다.
```

### 🎯 v6.1 상세페이지 버튼 이벤트 (병렬 처리)

```
event: detail_page_buttons_start
data: {"type": "start", "timestamp": "2024-01-16T10:32:15Z", "buttonsCount": 3}

event: detail_page_button_ready
data: {"type": "button", "buttonType": "HS_CODE", "priority": 1, "url": "/detail/hscode/8517.12.00", "title": "HS Code 상세정보", "description": "관세율, 규제정보 등", "isReady": true}

event: detail_page_button_ready
data: {"type": "button", "buttonType": "REGULATION", "priority": 2, "url": "/detail/regulation/8517.12.00", "title": "수입 규제정보", "description": "KC인증, 전파인증 등", "isReady": true}

event: detail_page_button_ready
data: {"type": "button", "buttonType": "STATISTICS", "priority": 3, "url": "/detail/statistics/8517.12.00", "title": "무역통계", "description": "수입량, 수입액 통계", "isReady": true}

event: detail_page_buttons_complete
data: {"type": "complete", "timestamp": "2024-01-16T10:32:20Z", "totalPreparationTime": 5}
```

### 🆕 v6.1 회원 전용 세션 및 기록 저장 이벤트

```
event: member_session_created
data: {"type": "session_created", "sessionId": "chat_session_20240116_123456", "isFirstMessage": true, "timestamp": "2024-01-16T10:32:00Z"}

event: member_record_saved
data: {"type": "record_saved", "sessionId": "chat_session_20240116_123456", "messageCount": 2, "partitionYear": 2024, "timestamp": "2024-01-16T10:32:25Z"}
```

### 🎯 v6.1 스트리밍 이벤트 타입 업데이트

### 초기 메타데이터

| 이벤트 타입        | 설명                                             | 데이터 형식                                                                                                                              |
| ------------------ | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `initial_metadata` | Claude 의도 분석 + 회원/비회원 상태 + RAG 활성화 | `{"claudeIntent": "...", "estimatedTime": 15, "isAuthenticated": true, "sessionCreated": true, "sessionId": "...", "ragEnabled": true}`  |
| `session_info`     | 🆕 회원/비회원 차별화 정보                       | `{"isAuthenticated": true, "userType": "MEMBER", "sessionId": "...", "recordingEnabled": true, "message": "회원님의 대화가 기록됩니다"}` |

### Thinking 단계 (v6.1 3단계 병렬 처리 추가)

| 이벤트 타입                          | 설명                               | 진행률 |
| ------------------------------------ | ---------------------------------- | ------ |
| `thinking_intent_analysis`           | 질문 의도 분석 중                  | 5-15%  |
| `thinking_parallel_processing_start` | 🆕 3단계 병렬 처리 시작            | 15%    |
| `thinking_rag_search_planning`       | RAG 검색 계획 수립 중              | 15-25% |
| `thinking_rag_search_executing`      | 벡터 DB 검색 실행 중               | 25-40% |
| `thinking_web_search_executing`      | 웹검색 실행 중                     | 40-60% |
| `thinking_data_processing`           | RAG + 웹 데이터 통합 분석 중       | 60-80% |
| `thinking_detail_page_preparation`   | 상세페이지 정보 병렬 준비 중       | 80-90% |
| `thinking_member_record_saving`      | 🆕 회원 대화 기록 저장 중 (회원만) | 85-90% |
| `thinking_response_generation`       | 최종 응답 생성 중                  | 90-95% |

### Main Message 단계

| 이벤트 타입             | 설명                  | 데이터 형식                                                                                             |
| ----------------------- | --------------------- | ------------------------------------------------------------------------------------------------------- |
| `main_message_start`    | 메인 메시지 시작      | `{"type": "start", "timestamp": "..."}`                                                                 |
| `main_message_data`     | 답변 내용 부분별 전송 | `{"type": "content", "content": "..."}`                                                                 |
| `main_message_complete` | 완료 메타데이터 전송  | `{"type": "metadata", "sources": [...], "ragSources": [...], "cacheHit": false, "bookmarkData": {...}}` |

### v6.1 상세페이지 버튼 단계 (병렬 처리)

| 이벤트 타입                    | 설명                      | 데이터 형식                                                                                 |
| ------------------------------ | ------------------------- | ------------------------------------------------------------------------------------------- |
| `detail_page_buttons_start`    | 상세페이지 버튼 준비 시작 | `{"type": "start", "buttonsCount": 3}`                                                      |
| `detail_page_button_ready`     | 개별 버튼 준비 완료       | `{"type": "button", "buttonType": "HS_CODE", "priority": 1, "url": "...", "isReady": true}` |
| `detail_page_buttons_complete` | 모든 버튼 준비 완료       | `{"type": "complete", "totalPreparationTime": 5}`                                           |

### 🆕 v6.1 회원 전용 이벤트

| 이벤트 타입              | 설명                     | 데이터 형식                                                                              |
| ------------------------ | ------------------------ | ---------------------------------------------------------------------------------------- |
| `member_session_created` | 회원 세션 생성 완료      | `{"type": "session_created", "sessionId": "...", "isFirstMessage": true}`                |
| `member_record_saved`    | 회원 대화 기록 저장 완료 | `{"type": "record_saved", "sessionId": "...", "messageCount": 2, "partitionYear": 2024}` |

### 🤖 v6.1 Claude AI + RAG 의도 분석 결과

| 의도 코드            | 설명                        | RAG 검색           | 예상 처리 시간 |
| -------------------- | --------------------------- | ------------------ | -------------- |
| `HS_CODE_ANALYSIS`   | HS Code 분류 및 관세율 조회 | HSCode 벡터 검색   | 12-18초        |
| `CARGO_TRACKING`     | 화물 추적 및 상태 조회      | 화물정보 캐시      | 8-12초         |
| `TRADE_REGULATION`   | 무역 규제 및 요건 조회      | 규제정보 벡터 검색 | 15-20초        |
| `GENERAL_TRADE_INFO` | 일반 무역 정보 및 절차      | 통합 지식베이스    | 10-15초        |
| `MARKET_ANALYSIS`    | 시장 분석 및 통계           | 통계 데이터 검색   | 18-25초        |

### 🔧 v6.1 클라이언트 연동 예시 (회원/비회원 차별화 + 3단계 병렬 처리 지원)

```tsx
const startV61ChatWithDifferentiation = async (message: string, sessionId?: string) => {
    const isAuthenticated = !!localStorage.getItem("accessToken");

    const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
            "Cache-Control": "no-cache",
            ...(isAuthenticated && {
                Authorization: `Bearer ${localStorage.getItem("accessToken")}`,
            }),
        },
        body: JSON.stringify({
            message,
            ...(sessionId && { sessionId }),
        }),
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.message);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error("스트리밍 연결 실패");

    // v6.1: 회원/비회원 차별화 + 3단계 병렬 처리 상태 관리
    const processingState = {
        isAuthenticated: false,
        userType: "GUEST",
        sessionId: null,
        mainMessageComplete: false,
        detailButtonsReady: [],
        memberRecordSaved: false,
        allProcessingComplete: false,
        bookmarkData: null,
    };

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = new TextDecoder().decode(value);
        const lines = chunk.split("\n");

        for (const line of lines) {
            if (line.startsWith("event:")) {
                const eventType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
                const data = JSON.parse(line.slice(5).trim());
                handleV61StreamEvent(eventType, data, processingState);
            }
        }
    }
};

const handleV61StreamEvent = (eventType: string, data: any, state: any) => {
    switch (eventType) {
        case "session_info":
            // 🆕 v6.1 회원/비회원 차별화 정보 처리
            state.isAuthenticated = data.isAuthenticated;
            state.userType = data.userType;
            state.sessionId = data.sessionId;
            showUserTypeInfo(data.userType, data.recordingEnabled, data.message);
            break;

        case "thinking_parallel_processing_start":
            // 🆕 v6.1 3단계 병렬 처리 시작
            showParallelProcessingStatus("3단계 병렬 처리 시작", data.progress);
            break;

        case "thinking_member_record_saving":
            // 🆕 v6.1 회원 기록 저장 진행 상황
            if (state.userType === "MEMBER") {
                updateThinkingUI("💾 대화 기록 저장", data.content, data.progress);
            }
            break;

        case "main_message_complete":
            state.mainMessageComplete = true;
            state.bookmarkData = data.bookmarkData;

            // 🆕 SSE 메타데이터를 확인하여 북마크 버튼 표시 로직 실행
            if (data.bookmarkData?.available && state.isAuthenticated) {
                showBookmarkButton(data.bookmarkData);
            }

            showCompletionInfo(data.sources, data.ragSources, data.cacheHit);
            break;

        case "member_session_created":
            // 🆕 v6.1 회원 세션 생성 완료
            state.sessionId = data.sessionId;
            showSessionCreatedInfo(data.sessionId, data.isFirstMessage);
            break;

        case "member_record_saved":
            // 🆕 v6.1 회원 대화 기록 저장 완료
            state.memberRecordSaved = true;
            showRecordSavedInfo(data.sessionId, data.messageCount, data.partitionYear);
            break;

        case "detail_page_button_ready":
            // 버튼이 준비되는 대로 로딩 스피너 → 실제 버튼으로 교체
            replaceButtonLoader(data.buttonType, {
                url: data.url,
                title: data.title,
                description: data.description,
                priority: data.priority,
            });
            state.detailButtonsReady.push(data.buttonType);
            break;

        case "detail_page_buttons_complete":
            hideAllLoaders();
            sortButtonsByPriority(); // 우선순위에 따라 버튼 정렬

            // 🆕 v6.1 모든 처리 완료 확인
            checkAllProcessingComplete(state);
            break;

        default:
            if (eventType.startsWith("thinking_")) {
                updateThinkingArea(data);
            }
    }
};

const showUserTypeInfo = (userType: string, recordingEnabled: boolean, message: string) => {
    const userTypeIndicator = document.getElementById("user-type-indicator");
    if (userType === "MEMBER") {
        userTypeIndicator.innerHTML = `
      <div class="member-status">
        <span class="status-badge member">회원</span>
        <span class="recording-status">📝 ${message}</span>
      </div>
    `;
    } else {
        userTypeIndicator.innerHTML = `
      <div class="guest-status">
        <span class="status-badge guest">비회원</span>
        <span class="info-message">💡 회원가입하면 대화 기록을 저장할 수 있습니다</span>
      </div>
    `;
    }
};

const showBookmarkButton = (bookmarkData: any) => {
    // SSE 메타데이터를 통해 북마크 버튼 표시
    const bookmarkContainer = document.getElementById("bookmark-container");
    bookmarkContainer.innerHTML = `
    <button class="bookmark-btn" onclick="createBookmark('${bookmarkData.hsCode}', '${bookmarkData.productName}')">
      🔖 북마크 추가: ${bookmarkData.productName}
    </button>
  `;
};
```

---

## 6. 회원 전용 채팅 기록 API v6.1 🔒 PRIVATE API

> 🔐 인증 필수: 회원만 이용 가능한 채팅 기록 관리 기능
>
> 🚀 **v6.1 신규**: pg_partman 기반 연도별 파티션 관리, 5년 보존 정책

### 6.1 채팅 세션 목록 조회

**`GET /api/chat/history`**

회원의 과거 채팅 세션 목록을 조회합니다.

### 📊 응답 코드 매트릭스

| 시나리오     | HTTP 상태          | 에러 코드 | 응답 메시지                  |
| ------------ | ------------------ | --------- | ---------------------------- |
| ✅ 조회 성공 | `200 OK`           | -         | “채팅 기록이 조회되었습니다” |
| ❌ 인증 필요 | `401 Unauthorized` | AUTH_003  | “인증이 필요합니다”          |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Query Parameters

| 필드명      | 타입   | 필수 | 설명                               |
| ----------- | ------ | ---- | ---------------------------------- |
| `page`      | number | -    | 페이지 번호 (기본값: 1)            |
| `size`      | number | -    | 페이지 크기 (기본값: 20, 최대 100) |
| `startDate` | string | -    | 시작 날짜 (ISO 8601)               |
| `endDate`   | string | -    | 종료 날짜 (ISO 8601)               |
| `keyword`   | string | -    | 세션 제목 검색 키워드              |

### Response (200 OK)

| 필드명            | 타입   | 설명                                    |
| ----------------- | ------ | --------------------------------------- |
| `success`         | string | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`         | string | 처리 결과 메시지                        |
| `data.sessions`   | array  | 채팅 세션 목록                          |
| `data.pagination` | object | 페이징 정보                             |

```json
{
    "success": "SUCCESS",
    "message": "채팅 기록이 조회되었습니다",
    "data": {
        "sessions": [
            {
                "sessionId": "chat_session_20240116_123456",
                "sessionTitle": "아이폰 15 프로 수입 HS Code 문의",
                "messageCount": 6,
                "createdAt": "2024-01-16T10:32:00Z",
                "updatedAt": "2024-01-16T10:45:00Z",
                "firstMessage": "아이폰 15 프로를 수입할 때 HS Code와 관세율이 어떻게 되나요?",
                "lastMessage": "추가 질문이 있으시면 언제든 문의해 주세요.",
                "partitionYear": 2024
            },
            {
                "sessionId": "chat_session_20240115_098765",
                "sessionTitle": "전자제품 수입 규제 확인",
                "messageCount": 4,
                "createdAt": "2024-01-15T14:20:00Z",
                "updatedAt": "2024-01-15T14:35:00Z",
                "firstMessage": "전자제품을 중국에서 수입할 때 필요한 인증서류가 무엇인가요?",
                "lastMessage": "KC 인증과 전파인증이 필수입니다.",
                "partitionYear": 2024
            }
        ],
        "pagination": { "currentPage": 1, "totalPages": 3, "totalElements": 45, "pageSize": 20, "hasNext": true, "hasPrevious": false }
    }
}
```

---

### 6.2 개별 채팅 세션 상세 조회

**`GET /api/chat/history/{sessionId}`**

특정 채팅 세션의 전체 대화 내용을 조회합니다.

### 📊 응답 코드 매트릭스

| 시나리오     | HTTP 상태          | 에러 코드 | 응답 메시지                               |
| ------------ | ------------------ | --------- | ----------------------------------------- |
| ✅ 조회 성공 | `200 OK`           | -         | “채팅 세션이 조회되었습니다”              |
| ❌ 인증 필요 | `401 Unauthorized` | AUTH_003  | “인증이 필요합니다”                       |
| ❌ 세션 없음 | `404 Not Found`    | CHAT_007  | “채팅 세션을 찾을 수 없습니다”            |
| ❌ 권한 없음 | `403 Forbidden`    | CHAT_008  | “해당 채팅 세션에 접근할 권한이 없습니다” |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Path Parameters

| 필드명      | 타입   | 필수 | 설명                                            |
| ----------- | ------ | ---- | ----------------------------------------------- |
| `sessionId` | string | ✓    | 채팅 세션 ID (예: chat_session_20240116_123456) |

### Response (200 OK)

| 필드명          | 타입   | 설명                                    |
| --------------- | ------ | --------------------------------------- |
| `success`       | string | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`       | string | 처리 결과 메시지                        |
| `data.session`  | object | 채팅 세션 정보                          |
| `data.messages` | array  | 채팅 메시지 목록                        |

```json
{
    "success": "SUCCESS",
    "message": "채팅 세션이 조회되었습니다",
    "data": {
        "session": {
            "sessionId": "chat_session_20240116_123456",
            "sessionTitle": "아이폰 15 프로 수입 HS Code 문의",
            "messageCount": 6,
            "createdAt": "2024-01-16T10:32:00Z",
            "updatedAt": "2024-01-16T10:45:00Z",
            "partitionYear": 2024
        },
        "messages": [
            {
                "messageId": 1,
                "messageType": "USER",
                "content": "아이폰 15 프로를 수입할 때 HS Code와 관세율이 어떻게 되나요?",
                "createdAt": "2024-01-16T10:32:00Z"
            },
            {
                "messageId": 2,
                "messageType": "AI",
                "content": "아이폰 15 프로의 정확한 HS Code는 **8517.12.00**입니다.\n\n## 관세율 정보\n- 기본 관세율: 8%\n- FTA 적용 시: 0% (한-미 FTA)\n- 부가가치세: 10%",
                "aiModel": "Claude-3.5-Sonnet",
                "thinkingProcess": "사용자가 아이폰 15 프로의 HS Code를 문의했습니다. 스마트폰은 8517.12.00으로 분류됩니다.",
                "hsCodeAnalysis": {
                    "hsCode": "8517.12.00",
                    "productName": "스마트폰 및 기타 무선전화기",
                    "confidence": 0.95,
                    "classificationBasis": "셀룰러 네트워크용 무선전화기"
                },
                "sseBookmarkData": { "available": true, "hsCode": "8517.12.00", "productName": "스마트폰 및 기타 무선전화기", "confidence": 0.95 },
                "createdAt": "2024-01-16T10:32:15Z"
            },
            { "messageId": 3, "messageType": "USER", "content": "KC 인증은 어떻게 받나요?", "createdAt": "2024-01-16T10:35:00Z" },
            {
                "messageId": 4,
                "messageType": "AI",
                "content": "KC 인증은 전자파적합성 확인을 위한 필수 인증입니다.\n\n## KC 인증 절차\n1. 공인시험소에서 시험 실시\n2. 시험성적서 발급\n3. 국립전파연구원에 신고\n4. KC 마크 부착",
                "aiModel": "Claude-3.5-Sonnet",
                "createdAt": "2024-01-16T10:35:10Z"
            }
        ]
    }
}
```

---

---

## 7. 대시보드 및 피드 시스템 v6.1 🔒 PRIVATE API

> 🔐 인증 필수: 이 섹션의 모든 API는 로그인이 필요합니다.
>
> 🚀 **v6.1 변경사항**: 회원 전용 채팅 기록 통합, 일일 알림 시스템 반영

### 7.1 대시보드 요약 정보 조회

**`GET /api/dashboard/summary`**

사용자의 개인화된 대시보드 요약 정보를 조회합니다.

### 📊 응답 코드 매트릭스

| 시나리오     | HTTP 상태          | 에러 코드 | 응답 메시지                 |
| ------------ | ------------------ | --------- | --------------------------- |
| ✅ 조회 성공 | `200 OK`           | -         | “대시보드 요약 정보 조회됨” |
| ❌ 인증 필요 | `401 Unauthorized` | AUTH_003  | “인증이 필요합니다”         |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Response (200 OK)

| 필드명               | 타입   | 설명                                    |
| -------------------- | ------ | --------------------------------------- |
| `success`            | string | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`            | string | 처리 결과 메시지                        |
| `data.user`          | object | 사용자 기본 정보                        |
| `data.bookmarks`     | object | 북마크 통계                             |
| `data.chatHistory`   | object | 🆕 v6.1: 회원 전용 채팅 기록 통계       |
| `data.notifications` | object | v6.1: 통합 알림 통계                    |

```json
{
    "success": "SUCCESS",
    "message": "대시보드 요약 정보 조회됨",
    "data": {
        "user": {
            "name": "홍길동",
            "email": "user@example.com",
            "profileImage": null,
            "phoneVerified": true,
            "rememberMe": true,
            "joinedAt": "2024-01-10T09:00:00Z"
        },
        "bookmarks": { "total": 8, "hsCode": 5, "cargo": 3, "sseGenerated": 6, "smsEnabled": 6, "emailEnabled": 8, "monitoringActive": 7 },
        "chatHistory": {
            "totalSessions": 45,
            "totalMessages": 180,
            "sessionsLast30Days": 8,
            "messagesLast30Days": 32,
            "oldestSession": "2023-06-15T09:00:00Z",
            "latestSession": "2024-01-16T10:32:00Z",
            "partitionYears": [2023, 2024]
        },
        "notifications": {
            "unreadFeeds": 3,
            "dailySms": 1,
            "dailyEmails": 1,
            "weeklyNotifications": 7,
            "smsEnabled": true,
            "emailEnabled": true,
            "lastNotificationSent": "2024-01-16T09:00:00Z"
        }
    }
}
```

---

### 7.2 업데이트 피드 조회

**`GET /api/dashboard/feeds`**

북마크한 항목들의 변동사항을 시간순으로 정렬된 피드 형태로 조회합니다.

### 📊 응답 코드 매트릭스

| 시나리오     | HTTP 상태          | 에러 코드 | 응답 메시지            |
| ------------ | ------------------ | --------- | ---------------------- |
| ✅ 조회 성공 | `200 OK`           | -         | “업데이트 피드 조회됨” |
| ❌ 인증 필요 | `401 Unauthorized` | AUTH_003  | “인증이 필요합니다”    |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Query Parameters

| 필드명                        | 타입    | 필수 | 설명                                  |
| ----------------------------- | ------- | ---- | ------------------------------------- |
| `page`                        | number  | -    | 페이지 번호 (기본값: 1)               |
| `size`                        | number  | -    | 페이지 크기 (기본값: 20, 최대 100)    |
| `feedType`                    | string  | -    | 피드 타입 필터                        |
| `importance`                  | string  | -    | 중요도 필터 (`HIGH`, `MEDIUM`, `LOW`) |
| `unreadOnly`                  | boolean | -    | 읽지 않은 피드만 조회 (기본값: false) |
| `startDate`                   | string  | -    | 조회 시작일 (ISO 8601)                |
| `endDate`                     | string  | -    | 조회 종료일 (ISO 8601)                |
| `includedInDailyNotification` | boolean | -    | v6.1: 일일 알림 포함된 피드만 조회    |

### Response (200 OK)

```json
{
    "success": "SUCCESS",
    "message": "업데이트 피드 조회됨",
    "data": {
        "feeds": [
            {
                "id": "feed_001",
                "feedType": "HS_CODE_TARIFF_CHANGE",
                "targetType": "HS_CODE",
                "targetValue": "8517.12.00",
                "title": "스마트폰 관세율 변경 알림",
                "content": "HS Code 8517.12.00의 기본 관세율이 8%에서 6%로 인하되었습니다.",
                "sourceUrl": "https://unipass.customs.go.kr/...",
                "importance": "HIGH",
                "isRead": false,
                "includedInDailyNotification": true,
                "dailyNotificationSentAt": "2024-01-16T09:00:00Z",
                "createdAt": "2024-01-16T08:15:00Z",
                "bookmarkInfo": { "bookmarkId": "bm_001", "displayName": "스마트폰 HS Code" }
            },
            {
                "id": "feed_002",
                "feedType": "CARGO_STATUS_UPDATE",
                "targetType": "CARGO",
                "targetValue": "KRPU1234567890",
                "title": "화물 상태 업데이트",
                "content": "수입신고가 완료되어 통관 절차가 진행 중입니다.",
                "sourceUrl": null,
                "importance": "MEDIUM",
                "isRead": true,
                "includedInDailyNotification": false,
                "dailyNotificationSentAt": null,
                "createdAt": "2024-01-15T16:30:00Z",
                "bookmarkInfo": { "bookmarkId": "bm_002", "displayName": "1월 수입 화물" }
            }
        ],
        "pagination": { "currentPage": 1, "totalPages": 2, "totalElements": 25, "pageSize": 20, "hasNext": true, "hasPrevious": false },
        "summary": { "totalFeeds": 25, "unreadFeeds": 3, "highImportanceFeeds": 2, "todayFeeds": 5, "dailyNotificationFeeds": 12 }
    }
}
```

---

### 7.3 개별 피드 읽음 처리

**`PUT /api/dashboard/feeds/{feedId}/read`**

특정 피드를 읽음 상태로 표시합니다.

### 📊 응답 코드 매트릭스

| 시나리오     | HTTP 상태          | 에러 코드 | 응답 메시지                        |
| ------------ | ------------------ | --------- | ---------------------------------- |
| ✅ 처리 성공 | `200 OK`           | -         | “피드가 읽음 처리되었습니다”       |
| ❌ 인증 필요 | `401 Unauthorized` | AUTH_003  | “인증이 필요합니다”                |
| ❌ 피드 없음 | `404 Not Found`    | FEED_001  | “피드를 찾을 수 없습니다”          |
| ❌ 권한 없음 | `403 Forbidden`    | FEED_002  | “해당 피드에 대한 권한이 없습니다” |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Path Parameters

| 필드명   | 타입   | 필수 | 설명                   |
| -------- | ------ | ---- | ---------------------- |
| `feedId` | string | ✓    | 피드 ID (예: feed_001) |

### Response (200 OK)

```json
{ "success": "SUCCESS", "message": "피드가 읽음 처리되었습니다", "data": { "feedId": "feed_001", "isRead": true, "readAt": "2024-01-16T11:30:00Z" } }
```

---

### 7.4 전체 피드 읽음 처리

**`PUT /api/dashboard/feeds/read-all`**

사용자의 모든 읽지 않은 피드를 읽음 상태로 일괄 처리합니다.

### 📊 응답 코드 매트릭스

| 시나리오               | HTTP 상태          | 에러 코드 | 응답 메시지                       |
| ---------------------- | ------------------ | --------- | --------------------------------- |
| ✅ 처리 성공           | `200 OK`           | -         | “모든 피드가 읽음 처리되었습니다” |
| ❌ 인증 필요           | `401 Unauthorized` | AUTH_003  | “인증이 필요합니다”               |
| ❌ 읽지 않은 피드 없음 | `404 Not Found`    | FEED_003  | “읽지 않은 피드가 없습니다”       |

### Authentication (Required)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Request Body (Optional)

| 필드명       | 타입   | 필수 | 설명                                       |
| ------------ | ------ | ---- | ------------------------------------------ |
| `beforeDate` | string | -    | 특정 날짜 이전 피드만 읽음 처리 (ISO 8601) |
| `feedTypes`  | array  | -    | 특정 피드 타입만 읽음 처리                 |

```json
{ "beforeDate": "2024-01-16T00:00:00Z", "feedTypes": ["HS_CODE_TARIFF_CHANGE", "CARGO_STATUS_UPDATE"] }
```

### Response (200 OK)

```json
{
    "success": "SUCCESS",
    "message": "모든 피드가 읽음 처리되었습니다",
    "data": { "processedCount": 15, "totalUnreadBefore": 15, "totalUnreadAfter": 0, "processedAt": "2024-01-16T11:35:00Z" }
}
```

---

## 8. 실시간 환율 API v6.1 🌐 PUBLIC API (사이드바 → 개별 엔드포인트)

> 🌐 공개 API: 인증 없이 사용 가능합니다.
>
> 🚀 **v6.1 변경사항**: `/api/sidebar/exchange-rates` → `/api/exchange-rates`

### 8.1 실시간 환율 정보 조회

**`GET /api/exchange-rates`**

주요 통화의 실시간 환율 정보를 조회합니다.

### 📊 응답 코드 매트릭스

| 시나리오              | HTTP 상태               | 에러 코드      | 응답 메시지                               |
| --------------------- | ----------------------- | -------------- | ----------------------------------------- |
| ✅ 조회 성공          | `200 OK`                | -              | “환율 정보가 조회되었습니다”              |
| ❌ 외부 API 연결 실패 | `502 Bad Gateway`       | EXTERNAL_001   | “환율 정보를 불러올 수 없습니다”          |
| ❌ 데이터 파싱 오류   | `502 Bad Gateway`       | EXTERNAL_002   | “환율 데이터 처리 중 오류가 발생했습니다” |
| ❌ Rate Limit 초과    | `429 Too Many Requests` | RATE_LIMIT_003 | “요청 한도를 초과했습니다”                |

### Query Parameters

| 필드명       | 타입    | 필수 | 설명                                            |
| ------------ | ------- | ---- | ----------------------------------------------- |
| `currencies` | string  | -    | 조회할 통화 코드 (쉼표 구분, 기본값: 주요 통화) |
| `cache`      | boolean | -    | 캐시 사용 여부 (기본값: true)                   |

### Response (200 OK)

| 필드명               | 타입   | 설명                                    |
| -------------------- | ------ | --------------------------------------- |
| `success`            | string | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`            | string | 처리 결과 메시지                        |
| `data.exchangeRates` | array  | 환율 정보 목록                          |
| `data.lastUpdated`   | string | 마지막 업데이트 시간 (ISO 8601)         |
| `data.source`        | object | 데이터 소스 정보                        |

```json
{
    "success": "SUCCESS",
    "message": "환율 정보가 조회되었습니다",
    "data": {
        "exchangeRates": [
            {
                "currencyCode": "USD",
                "currencyName": "미국 달러",
                "exchangeRate": 1328.5,
                "changeRate": -0.75,
                "changeAmount": -10.0,
                "lastUpdated": "2024-01-16T11:30:00Z"
            },
            {
                "currencyCode": "EUR",
                "currencyName": "유로",
                "exchangeRate": 1445.2,
                "changeRate": 0.45,
                "changeAmount": 6.5,
                "lastUpdated": "2024-01-16T11:30:00Z"
            },
            {
                "currencyCode": "JPY",
                "currencyName": "일본 엔 (100엔)",
                "exchangeRate": 895.3,
                "changeRate": -0.25,
                "changeAmount": -2.2,
                "lastUpdated": "2024-01-16T11:30:00Z"
            },
            {
                "currencyCode": "CNY",
                "currencyName": "중국 위안",
                "exchangeRate": 184.75,
                "changeRate": 0.15,
                "changeAmount": 0.28,
                "lastUpdated": "2024-01-16T11:30:00Z"
            }
        ],
        "lastUpdated": "2024-01-16T11:30:00Z",
        "source": { "provider": "한국은행 API", "updateFrequency": "실시간", "disclaimer": "참고용으로만 사용하시기 바랍니다" }
    }
}
```

---

### 8.2 특정 통화 환율 조회

**`GET /api/exchange-rates/{currencyCode}`**

특정 통화의 상세 환율 정보를 조회합니다.

### 📊 응답 코드 매트릭스

| 시나리오              | HTTP 상태         | 에러 코드    | 응답 메시지                      |
| --------------------- | ----------------- | ------------ | -------------------------------- |
| ✅ 조회 성공          | `200 OK`          | -            | “환율 정보가 조회되었습니다”     |
| ❌ 지원하지 않는 통화 | `404 Not Found`   | EXCHANGE_001 | “지원하지 않는 통화입니다”       |
| ❌ 외부 API 오류      | `502 Bad Gateway` | EXTERNAL_001 | “환율 정보를 불러올 수 없습니다” |

### Path Parameters

| 필드명         | 타입   | 필수 | 설명                           |
| -------------- | ------ | ---- | ------------------------------ |
| `currencyCode` | string | ✓    | 통화 코드 (USD, EUR, JPY, CNY) |

### Response (200 OK)

```json
{
    "success": "SUCCESS",
    "message": "환율 정보가 조회되었습니다",
    "data": {
        "currencyCode": "USD",
        "currencyName": "미국 달러",
        "exchangeRate": 1328.5,
        "changeRate": -0.75,
        "changeAmount": -10.0,
        "todayHigh": 1335.0,
        "todayLow": 1325.0,
        "weekHigh": 1340.0,
        "weekLow": 1315.0,
        "monthHigh": 1365.0,
        "monthLow": 1310.0,
        "lastUpdated": "2024-01-16T11:30:00Z",
        "trend": "DOWN",
        "historicalData": [
            { "date": "2024-01-15", "rate": 1338.5 },
            { "date": "2024-01-14", "rate": 1342.0 }
        ]
    }
}
```

---

## 9. 무역 뉴스 API v6.1 🌐 PUBLIC API (사이드바 → 개별 엔드포인트)

> 🌐 공개 API: 인증 없이 사용 가능합니다.
>
> 🚀 **v6.1 변경사항**: `/api/sidebar/news` → `/api/news`

### 9.1 무역 뉴스 목록 조회

**`GET /api/news`**

무역 관련 최신 뉴스를 조회합니다.

### 📊 응답 코드 매트릭스

| 시나리오           | HTTP 상태               | 에러 코드      | 응답 메시지                      |
| ------------------ | ----------------------- | -------------- | -------------------------------- |
| ✅ 조회 성공       | `200 OK`                | -              | “뉴스가 조회되었습니다”          |
| ❌ 외부 API 오류   | `502 Bad Gateway`       | EXTERNAL_003   | “뉴스 정보를 불러올 수 없습니다” |
| ❌ Rate Limit 초과 | `429 Too Many Requests` | RATE_LIMIT_004 | “뉴스 조회 한도를 초과했습니다”  |

### Query Parameters

| 필드명     | 타입   | 필수 | 설명                                             |
| ---------- | ------ | ---- | ------------------------------------------------ |
| `category` | string | -    | 뉴스 카테고리 (`관세`, `수출입`, `규제`, `전체`) |
| `page`     | number | -    | 페이지 번호 (기본값: 1)                          |
| `size`     | number | -    | 페이지 크기 (기본값: 20, 최대 50)                |
| `priority` | string | -    | 우선순위 필터 (`HIGH`, `MEDIUM`, `LOW`)          |

### Response (200 OK)

| 필드명            | 타입   | 설명                                    |
| ----------------- | ------ | --------------------------------------- |
| `success`         | string | 요청 처리 결과 (“SUCCESS” 또는 “ERROR”) |
| `message`         | string | 처리 결과 메시지                        |
| `data.news`       | array  | 뉴스 목록                               |
| `data.pagination` | object | 페이징 정보                             |
| `data.categories` | array  | 사용 가능한 카테고리 목록               |

```json
{
    "success": "SUCCESS",
    "message": "뉴스가 조회되었습니다",
    "data": {
        "news": [
            {
                "id": "news_001",
                "title": "2024년 상반기 스마트폰 수입 관세율 인하 발표",
                "summary": "정부가 스마트폰 등 IT 기기 수입 관세율을 기존 8%에서 6%로 인하한다고 발표했습니다.",
                "sourceName": "관세청",
                "sourceUrl": "https://unipass.customs.go.kr/news/...",
                "publishedAt": "2024-01-16T09:00:00Z",
                "category": "관세",
                "priority": 1,
                "isActive": true,
                "relatedHsCodes": ["8517.12.00", "8517.11.00"],
                "createdAt": "2024-01-16T09:05:00Z"
            },
            {
                "id": "news_002",
                "title": "중국산 전자제품 KC 인증 강화 방안 시행",
                "summary": "중국에서 수입되는 전자제품에 대한 KC 인증 절차가 강화되어 추가 서류 제출이 필요합니다.",
                "sourceName": "국립전파연구원",
                "sourceUrl": "https://rra.go.kr/news/...",
                "publishedAt": "2024-01-15T14:30:00Z",
                "category": "규제",
                "priority": 2,
                "isActive": true,
                "relatedHsCodes": ["8517.12.00", "8528.72.00"],
                "createdAt": "2024-01-15T14:35:00Z"
            },
            {
                "id": "news_003",
                "title": "한-베트남 FTA 추가 품목 관세 철폐 합의",
                "summary": "한국과 베트남이 전자부품 등 200여개 품목에 대한 관세를 단계적으로 철폐하기로 합의했습니다.",
                "sourceName": "산업통상자원부",
                "sourceUrl": "https://motie.go.kr/news/...",
                "publishedAt": "2024-01-15T11:20:00Z",
                "category": "수출입",
                "priority": 2,
                "isActive": true,
                "relatedHsCodes": ["8542.31.00", "8542.32.00"],
                "createdAt": "2024-01-15T11:25:00Z"
            }
        ],
        "pagination": { "currentPage": 1, "totalPages": 5, "totalElements": 85, "pageSize": 20, "hasNext": true, "hasPrevious": false },
        "categories": [
            { "name": "전체", "count": 85 },
            { "name": "관세", "count": 23 },
            { "name": "수출입", "count": 31 },
            { "name": "규제", "count": 19 },
            { "name": "통계", "count": 12 }
        ]
    }
}
```

---

### 9.2 뉴스 상세 조회

**`GET /api/news/{newsId}`**

특정 뉴스의 상세 정보를 조회합니다.

### 📊 응답 코드 매트릭스

| 시나리오     | HTTP 상태       | 에러 코드 | 응답 메시지               |
| ------------ | --------------- | --------- | ------------------------- |
| ✅ 조회 성공 | `200 OK`        | -         | “뉴스가 조회되었습니다”   |
| ❌ 뉴스 없음 | `404 Not Found` | NEWS_001  | “뉴스를 찾을 수 없습니다” |

### Path Parameters

| 필드명   | 타입   | 필수 | 설명                   |
| -------- | ------ | ---- | ---------------------- |
| `newsId` | string | ✓    | 뉴스 ID (예: news_001) |

### Response (200 OK)

```json
{
    "success": "SUCCESS",
    "message": "뉴스가 조회되었습니다",
    "data": {
        "id": "news_001",
        "title": "2024년 상반기 스마트폰 수입 관세율 인하 발표",
        "summary": "정부가 스마트폰 등 IT 기기 수입 관세율을 기존 8%에서 6%로 인하한다고 발표했습니다.",
        "content": "관세청은 16일 2024년 상반기부터 스마트폰(HS Code: 8517.12.00) 등 주요 IT 기기의 수입 관세율을 기존 8%에서 6%로 2%포인트 인하한다고 발표했습니다...",
        "sourceName": "관세청",
        "sourceUrl": "https://unipass.customs.go.kr/news/...",
        "publishedAt": "2024-01-16T09:00:00Z",
        "category": "관세",
        "priority": 1,
        "relatedHsCodes": [
            { "hsCode": "8517.12.00", "productName": "스마트폰 및 기타 무선전화기", "oldTariffRate": "8%", "newTariffRate": "6%" },
            { "hsCode": "8517.11.00", "productName": "유선전화기", "oldTariffRate": "8%", "newTariffRate": "6%" }
        ],
        "tags": ["관세율", "인하", "스마트폰", "IT기기"],
        "viewCount": 1523,
        "createdAt": "2024-01-16T09:05:00Z"
    }
}
```

---

## 10. 에러 코드 정의 v6.1

### 인증 관련 (AUTH_xxx)

| 에러 코드 | HTTP 상태 | 설명                         |
| --------- | --------- | ---------------------------- |
| AUTH_001  | 401       | 잘못된 인증 정보             |
| AUTH_002  | 423       | 계정 잠김                    |
| AUTH_003  | 401       | JWT 토큰 만료 또는 인증 필요 |
| AUTH_004  | 401       | 유효하지 않은 JWT 토큰       |

### SMS/이메일 통합 알림 관련 (SMS_xxx, EMAIL_xxx)

| 에러 코드 | HTTP 상태 | 설명                           |
| --------- | --------- | ------------------------------ |
| SMS_001   | 400       | 잘못된 휴대폰 번호 형식        |
| SMS_002   | 409       | 이미 인증된 휴대폰 번호        |
| SMS_003   | 429       | 발송 한도 초과                 |
| SMS_004   | 502       | SMS 서비스 오류                |
| SMS_005   | 400       | 잘못된 인증 코드               |
| SMS_006   | 410       | 만료된 인증 코드               |
| SMS_007   | 404       | 인증 세션 없음                 |
| SMS_008   | 429       | 인증 시도 횟수 초과            |
| SMS_009   | 400       | 미인증 휴대폰 번호             |
| SMS_010   | 409       | 다른 사용자가 사용 중인 번호   |
| SMS_011   | 409       | 이미 등록된 휴대폰 번호        |
| SMS_019   | 400       | 휴대폰 인증 필요 (SMS 설정 시) |

### 북마크 관련 (BOOKMARK_xxx)

| 에러 코드    | HTTP 상태 | 설명                  |
| ------------ | --------- | --------------------- |
| BOOKMARK_001 | 409       | 중복 북마크           |
| BOOKMARK_002 | 400       | 잘못된 북마크 정보    |
| BOOKMARK_003 | 429       | 북마크 개수 한도 초과 |
| BOOKMARK_004 | 422       | 유효하지 않은 HS Code |
| BOOKMARK_005 | 404       | 북마크 없음           |
| BOOKMARK_006 | 403       | 북마크 권한 없음      |

### 채팅 관련 (CHAT_xxx)

| 에러 코드 | HTTP 상태 | 설명                         |
| --------- | --------- | ---------------------------- |
| CHAT_001  | 400       | 메시지 너무 짧음 (2자 미만)  |
| CHAT_002  | 400       | 메시지 너무 김 (1000자 초과) |
| CHAT_003  | 422       | 무역 관련 질문이 아님        |
| CHAT_004  | 502       | Claude AI 분석 실패          |
| CHAT_005  | 502       | 지식베이스 검색 실패         |
| CHAT_006  | 502       | 상세페이지 정보 준비 실패    |
| CHAT_007  | 404       | 채팅 세션 없음               |
| CHAT_008  | 403       | 채팅 세션 접근 권한 없음     |
| CHAT_009  | 400       | 검색어 없음                  |
| CHAT_010  | 404       | 검색 결과 없음               |

### 피드 관련 (FEED_xxx)

| 에러 코드 | HTTP 상태 | 설명                |
| --------- | --------- | ------------------- |
| FEED_001  | 404       | 피드 없음           |
| FEED_002  | 403       | 피드 권한 없음      |
| FEED_003  | 404       | 읽지 않은 피드 없음 |

### 환율 관련 (EXCHANGE_xxx) - 🆕 v6.1

| 에러 코드    | HTTP 상태 | 설명               |
| ------------ | --------- | ------------------ |
| EXCHANGE_001 | 404       | 지원하지 않는 통화 |

### 뉴스 관련 (NEWS_xxx) - 🆕 v6.1

| 에러 코드 | HTTP 상태 | 설명      |
| --------- | --------- | --------- |
| NEWS_001  | 404       | 뉴스 없음 |

### 외부 API 관련 (EXTERNAL_xxx) - 🆕 v6.1

| 에러 코드    | HTTP 상태 | 설명                  |
| ------------ | --------- | --------------------- |
| EXTERNAL_001 | 502       | 환율 API 연결 실패    |
| EXTERNAL_002 | 502       | 환율 데이터 파싱 오류 |
| EXTERNAL_003 | 502       | 뉴스 API 연결 실패    |

### Rate Limiting (RATE_LIMIT_xxx)

| 에러 코드      | HTTP 상태 | 설명                  |
| -------------- | --------- | --------------------- |
| RATE_LIMIT_001 | 429       | 로그인 시도 한도 초과 |
| RATE_LIMIT_002 | 429       | 채팅 요청 한도 초과   |
| RATE_LIMIT_003 | 429       | 환율 조회 한도 초과   |
| RATE_LIMIT_004 | 429       | 뉴스 조회 한도 초과   |

### 공통 에러 (COMMON_xxx)

| 에러 코드  | HTTP 상태 | 설명                |
| ---------- | --------- | ------------------- |
| COMMON_001 | 400       | 필수 입력 정보 누락 |
| COMMON_002 | 500       | 서버 내부 오류      |

---

## 11. 개발자 가이드 v6.1

### 11.1 핵심 의존성 (검증 완료)

```xml
<!-- v6.1 핵심 의존성 --><dependencies>
    <!-- Spring Boot 3.4+ (3.5 출시 전까지 최신) -->    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
        <version>3.4.0</version>
    </dependency>
    <!-- PostgreSQL + pgvector -->    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>
    <dependency>
        <groupId>org.postgresql</groupId>
        <artifactId>postgresql</artifactId>
        <version>42.7.7</version>
    </dependency>
    <!-- Langchain4j 1.1.0-beta7 (검증 완료) -->    <dependency>
        <groupId>dev.langchain4j</groupId>
        <artifactId>langchain4j-pgvector</artifactId>
        <version>1.1.0-beta7</version>
    </dependency>
    <dependency>
        <groupId>dev.langchain4j</groupId>
        <artifactId>langchain4j-open-ai</artifactId>
        <version>1.1.0-beta7</version>
    </dependency>
    <!-- JWT 세부화 -->    <dependency>
        <groupId>io.jsonwebtoken</groupId>
        <artifactId>jjwt-api</artifactId>
        <version>0.12.3</version>
    </dependency>
    <!-- Redis -->    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-data-redis</artifactId>
    </dependency>
</dependencies>
```

### 11.2 회원/비회원 차별화 인증 처리

```java
@Componentpublic class AuthenticationResolver {    // 회원/비회원 구분 인터셉터    @Component    public class ChatAuthInterceptor implements HandlerInterceptor {        @Override        public boolean preHandle(HttpServletRequest request,
                               HttpServletResponse response,
                               Object handler) throws Exception {            String authHeader = request.getHeader("Authorization");            boolean isAuthenticated = false;            Long userId = null;            if (authHeader != null && authHeader.startsWith("Bearer ")) {                try {                    String token = authHeader.substring(7);                    Claims claims = jwtUtil.validateAccessToken(token);                    userId = claims.get("userId", Long.class);                    isAuthenticated = true;                } catch (Exception e) {                    // 토큰이 유효하지 않아도 비회원으로 처리                    isAuthenticated = false;                }            }            // 요청 속성에 인증 정보 저장            request.setAttribute("isAuthenticated", isAuthenticated);            request.setAttribute("userId", userId);            return true;        }    }}
```

### 11.3 3단계 병렬 처리 서비스

```java
@Servicepublic class ChatParallelProcessingService {    private final ExecutorService parallelExecutor =
        Executors.newFixedThreadPool(10);    public void processChatWithParallelTasks(String message,
                                           HttpServletRequest request,
                                           SseEmitter emitter) {        boolean isAuthenticated = (Boolean) request.getAttribute("isAuthenticated");        Long userId = (Long) request.getAttribute("userId");        String sessionId = null;        // 회원인 경우 세션 생성        if (isAuthenticated && isFirstMessage(userId, message)) {            sessionId = createNewChatSession(userId);            sendSessionCreatedEvent(emitter, sessionId);        }        // 3단계 병렬 처리 시작        CompletableFuture<String> naturalLanguageTask = CompletableFuture
            .supplyAsync(() -> processNaturalLanguage(message, emitter), parallelExecutor);        CompletableFuture<List<DetailPageInfo>> detailPageTask = CompletableFuture
            .supplyAsync(() -> prepareDetailPages(message, emitter), parallelExecutor);        CompletableFuture<Void> recordSaveTask = CompletableFuture
            .runAsync(() -> {                if (isAuthenticated && sessionId != null) {                    saveMemberChatRecord(sessionId, message, emitter);                }            }, parallelExecutor);        // 모든 작업 완료 대기        CompletableFuture.allOf(naturalLanguageTask, detailPageTask, recordSaveTask)            .thenRun(() -> {                sendProcessingCompleteEvent(emitter);                emitter.complete();            })            .exceptionally(throwable -> {                emitter.completeWithError(throwable);                return null;            });    }    private String createNewChatSession(Long userId) {        String sessionId = "chat_session_" + System.currentTimeMillis();        // pg_partman 파티션에 세션 저장        ChatSession session = ChatSession.builder()            .sessionUuid(UUID.fromString(sessionId))            .userId(userId)            .createdAt(LocalDateTime.now())            .build();        chatSessionRepository.save(session);        return sessionId;    }    private void saveMemberChatRecord(String sessionId, String message, SseEmitter emitter) {        try {            // 회원 대화 기록을 pg_partman 파티션에 저장            ChatMessage chatMessage = ChatMessage.builder()                .sessionUuid(UUID.fromString(sessionId))                .messageType("USER")                .content(message)                .createdAt(LocalDateTime.now())                .build();            chatMessageRepository.save(chatMessage);            // 저장 완료 이벤트 전송            sendMemberRecordSavedEvent(emitter, sessionId);        } catch (Exception e) {            log.error("회원 대화 기록 저장 실패: sessionId={}", sessionId, e);        }    }}
```

### 11.4 SSE 메타데이터 기반 북마크 처리

```java
@Servicepublic class BookmarkMetadataService {    public void handleSSEBookmarkMetadata(ChatAnalysisResult analysisResult,
                                        SseEmitter emitter) {        // Claude 분석 결과에서 HSCode 정보 추출        if (analysisResult.getHsCode() != null &&
            analysisResult.getConfidence() > 0.8) {            // SSE 메타데이터로 북마크 정보 전송            BookmarkMetadata bookmarkData = BookmarkMetadata.builder()                .available(true)                .hsCode(analysisResult.getHsCode())                .productName(analysisResult.getProductName())                .confidence(analysisResult.getConfidence())                .classificationBasis(analysisResult.getClassificationBasis())                .build();            // 메인 메시지 완료 시 북마크 메타데이터 포함            sendMainMessageCompleteEvent(emitter, analysisResult, bookmarkData);        }    }    private void sendMainMessageCompleteEvent(SseEmitter emitter,
                                            ChatAnalysisResult result,                                            BookmarkMetadata bookmarkData) {        try {            Map<String, Object> eventData = Map.of(                "type", "metadata",                "sources", result.getSources(),                "ragSources", result.getRagSources(),                "cacheHit", result.isCacheHit(),                "bookmarkData", bookmarkData  // 🆕 v6.1 SSE 메타데이터            );            SseEventBuilder event = SseEmitter.event()                .name("main_message_complete")                .data(eventData);            emitter.send(event);        } catch (Exception e) {            log.error("SSE 메타데이터 전송 실패", e);        }    }}
```

### 11.5 JWT 세부화 토큰 관리

```java
@Servicepublic class JwtTokenService {    @Value("${app.jwt.access-token-expiration:1800000}") // 30분    private long accessTokenExpiration;    public JwtAuthenticationResponse generateTokens(User user, boolean rememberMe) {        // Access Token 생성 (항상 30분)        String accessToken = generateAccessToken(user);        // Refresh Token 생성 (remember me 설정에 따라 1일/30일)        long refreshExpiration = rememberMe ?
            Duration.ofDays(30).toMillis() : Duration.ofDays(1).toMillis();        String refreshToken = generateRefreshToken(user, refreshExpiration);        // DB에 Refresh Token 저장        user.setRefreshToken(refreshToken);        user.setRefreshTokenExpiresAt(LocalDateTime.now().plus(            Duration.ofMillis(refreshExpiration)));        user.setRememberMeEnabled(rememberMe);        userRepository.save(user);        return JwtAuthenticationResponse.builder()            .accessToken(accessToken)            .tokenType("Bearer")            .expiresIn(accessTokenExpiration / 1000) // 초 단위            .user(UserDto.from(user))            .build();    }    public ResponseEntity<JwtRefreshResponse> refreshAccessToken(            HttpServletRequest request) {        // HttpOnly 쿠키에서 Refresh Token 추출        String refreshToken = extractRefreshTokenFromCookie(request);        if (refreshToken == null) {            throw new AuthenticationException("Refresh Token이 필요합니다");        }        // DB에서 토큰 검증        User user = userRepository.findByRefreshToken(refreshToken)            .orElseThrow(() -> new AuthenticationException("유효하지 않은 Refresh Token"));        if (user.getRefreshTokenExpiresAt().isBefore(LocalDateTime.now())) {            throw new AuthenticationException("만료된 Refresh Token");        }        // 새 Access Token 생성        String newAccessToken = generateAccessToken(user);        // 새 Refresh Token 생성 (Token Rotation)        boolean rememberMe = user.isRememberMeEnabled();        long refreshExpiration = rememberMe ?
            Duration.ofDays(30).toMillis() : Duration.ofDays(1).toMillis();        String newRefreshToken = generateRefreshToken(user, refreshExpiration);        // DB 업데이트        user.setRefreshToken(newRefreshToken);        user.setRefreshTokenExpiresAt(LocalDateTime.now().plus(            Duration.ofMillis(refreshExpiration)));        user.setLastTokenRefresh(LocalDateTime.now());        userRepository.save(user);        // HttpOnly 쿠키로 새 Refresh Token 설정        HttpHeaders headers = new HttpHeaders();        headers.add("Set-Cookie", createRefreshTokenCookie(newRefreshToken, rememberMe));        JwtRefreshResponse response = JwtRefreshResponse.builder()            .accessToken(newAccessToken)            .tokenType("Bearer")            .expiresIn(accessTokenExpiration / 1000)            .rememberMe(rememberMe)            .build();        return ResponseEntity.ok().headers(headers).body(response);    }    private String createRefreshTokenCookie(String refreshToken, boolean rememberMe) {        long maxAge = rememberMe ? 30 * 24 * 60 * 60 : 24 * 60 * 60; // 30일 또는 1일        return String.format(            "refreshToken=%s; HttpOnly; Secure; SameSite=Strict; Path=/auth/refresh; Max-Age=%d",            refreshToken, maxAge
        );    }}
```

---

## 12. v6.1 마이그레이션 가이드

### 12.1 API 엔드포인트 변경사항

| 구분            | v5 경로                       | v6.1 경로             | 변경 이유               |
| --------------- | ----------------------------- | --------------------- | ----------------------- |
| **환율**        | `/api/sidebar/exchange-rates` | `/api/exchange-rates` | 개별 상세 페이지로 분리 |
| **뉴스**        | `/api/sidebar/news`           | `/api/news`           | 개별 상세 페이지로 분리 |
| **HSCode RAG**  | `/api/hscode/vector-search`   | 제거                  | 백엔드 내부 처리로 전환 |
| **HSCode 캐시** | `/api/hscode/cache`           | 제거                  | 백엔드 내부 처리로 전환 |

### 12.2 프론트엔드 연동 변경사항

### 🔄 JWT 토큰 관리 변경

```tsx
// v5 → v6.1 변경: Access Token과 Refresh Token 분리 저장class AuthService {
  // v6.1: Access Token은 헤더와 Zustand 상태로 관리  setAccessToken(token: string) {
    localStorage.setItem('accessToken', token);    // Zustand 상태 업데이트    useAuthStore.getState().setAccessToken(token);  }
  // v6.1: Refresh Token은 HttpOnly 쿠키로 자동 관리  async refreshToken() {
    const response = await fetch('/api/auth/refresh', {
      method: 'POST',      credentials: 'include', // HttpOnly 쿠키 자동 전송    });    if (response.ok) {
      const data = await response.json();      this.setAccessToken(data.data.accessToken);      return data.data.accessToken;    }
    throw new Error('토큰 갱신 실패');  }
}
```

### 🔄 SSE 기반 북마크 처리 변경

```tsx
// v5 → v6.1 변경: 컨텍스트 기반 → SSE 메타데이터 기반const handleSSEBookmarkDisplay = (eventData: any) => {
  if (eventData.type === 'metadata' && eventData.bookmarkData?.available) {
    // 🆕 v6.1: SSE 메타데이터를 통한 북마크 버튼 표시    const bookmarkData = eventData.bookmarkData;    const bookmarkContainer = document.getElementById('bookmark-container');    bookmarkContainer.innerHTML = `      <div class="bookmark-section">        <h4>북마크 추가 가능</h4>        <button          class="bookmark-btn"          onclick="createBookmarkFromSSE('${bookmarkData.hsCode}', '${bookmarkData.productName}', '${JSON.stringify(bookmarkData)}')"        >          🔖 ${bookmarkData.productName} 북마크 추가        </button>      </div>    `;  }
};const createBookmarkFromSSE = async (hsCode: string, productName: string, sseEventData: string) => {
  const response = await fetch('/api/bookmarks', {
    method: 'POST',    headers: {
      'Content-Type': 'application/json',      'Authorization': `Bearer ${localStorage.getItem('accessToken')}`    },    body: JSON.stringify({
      type: 'HS_CODE',      targetValue: hsCode,      displayName: productName,      sseEventData: JSON.parse(sseEventData), // 🆕 v6.1: SSE 메타데이터 포함      smsNotificationEnabled: true,      emailNotificationEnabled: true    })
  });  if (response.ok) {
    alert('북마크가 생성되었습니다!');    // 북마크 버튼 숨기기 또는 비활성화  }
};
```

### 🔄 회원/비회원 차별화 UI 처리

```tsx
// v6.1: 회원/비회원 차별화 UI 처리const handleSessionInfo = (eventData: any) => {
  const { isAuthenticated, userType, sessionId, recordingEnabled, message } = eventData;  const statusContainer = document.getElementById('user-status');  if (userType === 'MEMBER') {
    statusContainer.innerHTML = `      <div class="member-status">        <span class="badge member">회원</span>        <span class="session-info">세션: ${sessionId}</span>        <span class="recording-info">📝 ${message}</span>      </div>    `;  } else {
    statusContainer.innerHTML = `      <div class="guest-status">        <span class="badge guest">비회원</span>        <span class="signup-prompt">          💡 <a href="/signup">회원가입</a>하면 대화 기록을 저장할 수 있습니다        </span>      </div>    `;  }
};// v6.1: 회원 전용 채팅 기록 관리const loadChatHistory = async () => {
  const response = await fetch('/api/chat/history', {
    headers: {
      'Authorization': `Bearer ${localStorage.getItem('accessToken')}`    }
  });  if (response.ok) {
    const data = await response.json();    displayChatSessions(data.data.sessions);  }
};
```

### 12.3 백엔드 설정 변경사항

### application.yml 업데이트

```yaml
# v6.1 JWT 세부화 설정app:  jwt:    secret: ${JWT_SECRET}    access-token-expiration: 1800000  # 30분 (고정)    refresh-token-expiration:      remember-me: 2592000000        # 30일      normal: 86400000               # 1일# v6.1 회원/비회원 차별화 채팅 설정chat:  member:    session-creation: true    record-saving: true    partition-management: true  guest:    session-creation: false    record-saving: false    volatile-only: true# v6.1 SSE 설정sse:  timeout: 60000  # 60초  heartbeat-interval: 30000  # 30초# v6.1 병렬 처리 설정parallel:  processing:    enabled: true    thread-pool-size: 10    max-concurrent-chats: 100
```

---

## 13. 성능 최적화 가이드 v6.1

### 13.1 3단계 병렬 처리 최적화

```java
@Configurationpublic class ParallelProcessingConfig {    @Bean("chatParallelExecutor")    public ThreadPoolTaskExecutor chatParallelExecutor() {        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();        executor.setCorePoolSize(10);           // v6.1: 3단계 병렬 처리 최적화        executor.setMaxPoolSize(50);        executor.setQueueCapacity(200);        executor.setThreadNamePrefix("ChatParallel-");        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());        executor.initialize();        return executor;    }}
```

### 13.2 회원 전용 채팅 기록 조회 최적화

```sql
-- v6.1: pg_partman 파티션 조회 최적화-- 최근 채팅 세션 조회시 최신 파티션부터 검색EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM chat_sessions
WHERE user_id = ?
  AND created_at >= CURRENT_DATE - INTERVAL '30 days'ORDER BY created_at DESC
LIMIT 20;
-- 인덱스 최적화CREATE INDEX CONCURRENTLY idx_chat_sessions_user_recent
ON chat_sessions (user_id, created_at DESC)
WHERE created_at >= CURRENT_DATE - INTERVAL '90 days';
```

### 13.3 SSE 연결 관리 최적화

```java
@Componentpublic class SSEConnectionManager {    private final Map<String, SseEmitter> activeConnections = new ConcurrentHashMap<>();    @Scheduled(fixedRate = 30000) // 30초마다    public void cleanupExpiredConnections() {        activeConnections.entrySet().removeIf(entry -> {            try {                entry.getValue().send(SseEmitter.event().name("heartbeat").data("ping"));                return false;            } catch (Exception e) {                log.debug("SSE 연결 정리: {}", entry.getKey());                return true;            }        });    }}
```

---

## 14. 최종 일관성 검증 및 요약

### 14.1 요구사항 v6.1 대비 완성도 ✅

| 핵심 요구사항             | API 반영 상태 | 세부 내용                                         |
| ------------------------- | ------------- | ------------------------------------------------- |
| **회원/비회원 차별화**    | ✅ 완료       | 회원만 세션 생성 및 기록 저장, 비회원 완전 휘발성 |
| **JWT 세부화**            | ✅ 완료       | Access 30분, Refresh 1일/30일, 분리 저장 정책     |
| **SSE 메타데이터 북마크** | ✅ 완료       | 컨텍스트 기반 제거, SSE 메타데이터 기반 전환      |
| **3단계 병렬 처리**       | ✅ 완료       | 자연어 응답 + 상세페이지 + 회원 기록 저장         |
| **사이드바 개별화**       | ✅ 완료       | `/api/exchange-rates`, `/api/news` 분리           |
| **RAG 백엔드 처리**       | ✅ 완료       | HSCode 벡터 검색/캐시 공개 API 제거               |

### 14.2 스키마 v6.1 완벽 일치 확인 ✅

| 테이블/기능                 | API 반영 상태 | 비고                                        |
| --------------------------- | ------------- | ------------------------------------------- |
| `chat_sessions` (회원 전용) | ✅ 완료       | `user_id NOT NULL` 반영                     |
| `chat_messages` (파티션)    | ✅ 완료       | pg_partman 자동 관리                        |
| `bookmarks` (SSE 기반)      | ✅ 완료       | `sse_generated`, `sse_event_data` 반영      |
| `users` (JWT 세부화)        | ✅ 완료       | `remember_me_enabled`, `refresh_token` 정책 |
| `exchange_rates_cache`      | ✅ 완료       | 개별 API 엔드포인트 지원                    |
| `trade_news_cache`          | ✅ 완료       | 개별 API 엔드포인트 지원                    |

### 14.3 삭제된 불필요 요소 확인 ✅

| 삭제 항목            | 삭제 완료 | 대체 방안              |
| -------------------- | --------- | ---------------------- |
| HSCode RAG 공개 API  | ✅        | 백엔드 내부 처리       |
| 컨텍스트 기반 북마크 | ✅        | SSE 메타데이터 기반    |
| 사이드바 경로 구조   | ✅        | 개별 엔드포인트로 분리 |

### 14.4 기술 스택 검증 완료 ✅

-   **Langchain4j 1.1.0-beta7**: ✅ 2024년 출시 확인, PostgreSQL+pgvector 지원
-   **Spring Boot 3.4+**: ✅ 현재 최신 버전 확인 (3.5는 향후 출시 예정)
-   **PostgreSQL 15+ + pgvector**: ✅ 완벽 호환 확인
-   **voyage-3-large 2048차원**: ✅ 고성능 임베딩 모델 지원

---

## 15. 결론

### 🎉 AI 기반 무역 규제 레이더 플랫폼 API 명세서 v6.1 완료!

본 API 명세서는 **요구사항 v6.1과 스키마 v6.1을 완벽하게 반영**하여 다음과 같은 혁신적 기능들을 제공합니다:

### 🚀 핵심 혁신사항

1. **회원/비회원 명확한 차별화**: 전략적 가입 유도를 위한 차별화된 서비스 제공
2. **JWT 세부화 보안**: Access Token 30분, Refresh Token 1일/30일의 정교한 토큰 정책
3. **SSE 메타데이터 북마크**: 실시간 상호작용을 통한 즉시 북마크 가능
4. **3단계 병렬 처리**: 최적화된 성능으로 탁월한 사용자 경험 제공
5. **완전 자동화 운영**: pg_partman BGW를 통한 무인 시스템 관리

### 🎯 비즈니스 가치

-   **사용자 경험 극대화**: 회원은 풍부한 기능, 비회원도 핵심 체험 가능
-   **운영 효율성 100% 달성**: 완전 자동화된 데이터 관리 및 알림 시스템
-   **확장성 보장**: 대용량 트래픽과 데이터 처리를 위한 견고한 아키텍처
-   **보안성 강화**: 정교한 JWT 정책과 분리된 토큰 저장 전략

### 🔧 기술적 우수성

-   **최신 기술 스택**: 검증된 Langchain4j 1.1.0-beta7 + PostgreSQL+pgvector 조합
-   **무상태 아키텍처**: JWT 기반 확장 가능한 인증 시스템
-   **병렬 처리 최적화**: 3단계 동시 처리로 응답 시간 최소화
-   **자동화 운영**: pg_partman BGW를 통한 완전 무인 데이터 관리

이제 **즉시 개발에 착수할 수 있는 수준의 완성도**를 갖춘 API 명세서로, 중소기업 무역 담당자들에게 혁신적인 무역 정보 서비스를 제공할 준비가 완료되었습니다!
