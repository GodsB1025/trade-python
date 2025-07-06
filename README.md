# 무역 규제 레이더 플랫폼 백엔드

AI 기반 무역 규제 분석 및 HSCode 분류 서비스를 제공하는 FastAPI 백엔드 시스템입니다.

## 주요 기능

- AI 기반 HSCode 분류 및 무역 규제 분석
- 실시간 채팅 스트리밍 (SSE)
- 화물통관 조회 서비스
- 상세페이지 정보 자동 생성
- 다국어 지원 (한국어 우선)

## 📡 SSE 이벤트 구조 (v2.0 표준화)

### 개선된 이벤트 네이밍 컨벤션

모든 SSE 이벤트에 명확한 이벤트 이름을 부여하여 프론트엔드에서 쉽게 파싱할 수 있도록 개선했습니다.

#### 1. 채팅 관련 이벤트
```typescript
// 세션 정보
event: chat_session_info
data: {"session_uuid": "uuid", "timestamp": 123456}

// 메시지 시작/종료
event: chat_message_start
event: chat_message_delta
event: chat_message_limit  
event: chat_message_stop

// 컨텐츠 블록 (실제 텍스트)
event: chat_content_start
event: chat_content_delta    // 스트리밍 텍스트 청크
event: chat_content_stop

// 메타데이터 (새 세션인 경우)
event: chat_metadata_start
event: chat_metadata_stop
```

#### 2. 병렬 처리 이벤트
```typescript
// 병렬 처리 상태
event: parallel_processing
data: {
  "stage": "parallel_processing_start",
  "content": "3단계 병렬 처리를 시작합니다...",
  "progress": 15,
  "timestamp": "2025-07-06T14:44:04.298191Z"
}
```

#### 3. 상세페이지 버튼 이벤트
```typescript
// 버튼 준비 시작/완료
event: detail_buttons_start
event: detail_button_ready      // 개별 버튼
event: detail_buttons_complete
event: detail_buttons_error
```

### 프론트엔드 파싱 가이드

**Before (문제):**
```javascript
// 이벤트 타입을 data 내부에서 찾아야 함
eventSource.addEventListener('message', (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'content_block_delta') {
    // 텍스트 처리
  }
});
```

**After (해결):**
```javascript
// 명확한 이벤트 이름으로 직접 처리
eventSource.addEventListener('chat_content_delta', (event) => {
  const data = JSON.parse(event.data);
  appendText(data.delta.text);
});

eventSource.addEventListener('parallel_processing', (event) => {
  const data = JSON.parse(event.data);
  updateProgress(data.progress, data.content);
});

eventSource.addEventListener('detail_button_ready', (event) => {
  const button = JSON.parse(event.data);
  addDetailButton(button);
});
```

### 이벤트 흐름 순서

1. `chat_session_info` - 세션 정보
2. `chat_message_start` - 메시지 시작
3. `chat_metadata_start/stop` - 새 세션인 경우 메타데이터
4. `chat_content_start` - 컨텐츠 블록 시작
5. `parallel_processing` - 병렬 처리 시작
6. `chat_content_delta` (연속) - 실제 텍스트 스트리밍
7. `detail_buttons_start` - 상세버튼 준비 시작
8. `detail_button_ready` (반복) - 개별 버튼 준비 완료
9. `detail_buttons_complete` - 모든 버튼 준비 완료
10. `chat_content_stop` - 컨텐츠 블록 종료
11. `chat_message_delta` - 메시지 메타데이터
12. `chat_message_limit` - 메시지 제한 정보
13. `chat_message_stop` - 메시지 종료

## 🚀 빠른 시작

### 환경 설정

```bash
# 의존성 설치
uv sync

# 환경 변수 설정
cp .env.example .env
# .env 파일 수정 (API 키 등)

# 서버 실행
uv run python main.py
```

### API 엔드포인트

- **POST /api/v1/chat** - AI 채팅 (SSE 스트리밍)
- **GET /api/v1/monitoring/health** - 서버 상태 확인
- **GET /docs** - API 문서 (Swagger UI)

## 📚 추가 문서

- `docs/` 디렉토리에서 상세 문서 확인
- `PYTHON_SERVER_GUIDE.md` - 서버 설정 가이드
- `reflection/` 디렉토리 - 개발 히스토리

## 🔧 개발 환경

- Python 3.11+
- FastAPI
- SQLAlchemy (비동기)
- LangChain
- Anthropic Claude API
