# 채팅 세션 DB 저장 실패 문제 해결 보고서

**작성일**: 2025-07-04  
**작성자**: AI Assistant  
**문제 번호**: CHAT-001  

## 1. 문제 설명

### 증상
- `/api/v1/chat` 엔드포인트로 요청 시 Claude API 응답은 정상적으로 받고, SSE 스트림으로 응답도 잘 전송됨
- 로그에서 `INSERT INTO chat_sessions` 쿼리가 실행되고 `session_uuid`가 생성됨을 확인
- 하지만 실제 PostgreSQL DB를 확인하면 `chat_sessions` 테이블에 해당 행이 저장되지 않음

### 로그 분석
```
BEGIN (implicit)
INSERT INTO chat_sessions (user_id, session_title, message_count) VALUES ($1::BIGINT, $2::VARCHAR, $3::INTEGER) RETURNING chat_sessions.session_uuid, chat_sessions.created_at, chat_sessions.updated_at
[generated in 0.00032s] (2, None, 0)
SELECT chat_sessions.session_uuid, chat_sessions.created_at, chat_sessions.user_id, chat_sessions.session_title, chat_sessions.message_count, chat_sessions.updated_at 
FROM chat_sessions 
WHERE chat_sessions.session_uuid = $1::UUID AND chat_sessions.created_at = $2::TIMESTAMP WITH TIME ZONE
```

**주목할 점**: `BEGIN`은 있지만 `COMMIT`이 없음

## 2. 원인 분석

### 2.1 동기/비동기 타입 불일치
1. **DB 세션 구성 (`app/db/session.py`)**:
   - `AsyncSession`을 사용하도록 구성되어 있음
   - `get_db()` 함수는 비동기 세션을 yield하고 자동으로 commit/rollback 처리

2. **엔드포인트 레이어 (`app/api/v1/endpoints/chat.py`)**:
   - 타입 힌트가 `db: Session`으로 되어 있었음 (동기 세션)
   - 실제로는 `AsyncSession`이 주입되고 있었음

3. **서비스 레이어 (`app/services/chat_service.py`)**:
   - `db: Session` 타입으로 받고 있었음
   - 비동기 CRUD 함수들을 동기적으로 호출하려고 시도

### 2.2 트랜잭션 커밋 타이밍 문제
1. **SSE 스트리밍의 특성**:
   - 제너레이터 함수가 완전히 종료될 때까지 `get_db()`의 finally 블록이 실행되지 않음
   - 따라서 자동 커밋이 지연됨

2. **세션 생성 시점의 커밋 누락**:
   - 새로운 채팅 세션을 생성한 후 즉시 커밋하지 않음
   - 스트리밍이 완료될 때까지 DB에 반영되지 않음

## 3. 해결 방안

### 3.1 타입 수정
1. **엔드포인트 레이어**:
   ```python
   # 변경 전
   from sqlalchemy.orm import Session
   db: Session = Depends(get_db)
   
   # 변경 후
   from sqlalchemy.ext.asyncio import AsyncSession
   db: AsyncSession = Depends(get_db)
   ```

2. **서비스 레이어**:
   ```python
   # 변경 전
   from sqlalchemy.orm import Session
   async def stream_chat_response(self, chat_request: ChatRequest, db: Session, ...)
   
   # 변경 후
   from sqlalchemy.ext.asyncio import AsyncSession
   async def stream_chat_response(self, chat_request: ChatRequest, db: AsyncSession, ...)
   ```

### 3.2 비동기 처리 수정
1. **CRUD 함수 호출에 `await` 추가**:
   ```python
   # 변경 전
   session_obj = crud.chat.get_or_create_session(db=db, user_id=user_id, ...)
   
   # 변경 후
   session_obj = await crud.chat.get_or_create_session(db=db, user_id=user_id, ...)
   ```

2. **백그라운드 작업 비동기화**:
   ```python
   # 변경 전
   def _save_rag_document_from_web_search_task(docs: List[Document], hscode_value: str):
       with SessionLocal() as db:
           hscode_obj = crud.hscode.get_or_create(db, ...)
   
   # 변경 후
   async def _save_rag_document_from_web_search_task(docs: List[Document], hscode_value: str):
       async with SessionLocal() as db:
           hscode_obj = await crud.hscode.get_or_create(db, ...)
   ```

### 3.3 명시적 커밋 추가
1. **세션 생성 후 즉시 커밋**:
   ```python
   session_obj = await crud.chat.get_or_create_session(db=db, user_id=user_id, ...)
   # 세션 생성 후 즉시 커밋하여 DB에 저장
   await db.commit()
   ```

2. **대화 저장 후 커밋**:
   ```python
   # 스트리밍 완료 후
   if user_id:
       await db.commit()
   ```

## 4. 수정된 파일

1. `app/api/v1/endpoints/chat.py`
2. `app/services/chat_service.py`

## 5. 검증 방법

1. 서버 재시작 후 `/api/v1/chat` 엔드포인트로 요청 전송
2. PostgreSQL 로그에서 `COMMIT` 명령어 확인
3. `chat_sessions` 테이블에서 새로운 세션이 저장되었는지 확인

## 6. 교훈 및 향후 개선사항

### 교훈
1. **타입 힌트의 중요성**: 타입 힌트가 실제 사용되는 타입과 일치해야 함
2. **비동기 일관성**: 비동기 함수 체인에서는 모든 레이어가 비동기로 구현되어야 함
3. **트랜잭션 관리**: SSE 같은 스트리밍 응답에서는 명시적인 트랜잭션 관리가 필요

### 개선 제안
1. **타입 체크 도구 도입**: mypy 등을 사용하여 타입 불일치를 사전에 감지
2. **통합 테스트 추가**: DB 저장까지 확인하는 E2E 테스트 작성
3. **트랜잭션 로깅**: 개발 환경에서 BEGIN/COMMIT/ROLLBACK을 명확히 로깅

## 7. 결론

이 문제는 동기/비동기 타입 불일치와 트랜잭션 커밋 타이밍 문제로 인해 발생했습니다. SQLAlchemy의 AsyncSession을 올바르게 사용하고, 적절한 시점에 명시적으로 커밋을 수행함으로써 문제를 해결했습니다. 이번 경험을 통해 비동기 프로그래밍에서의 일관성과 명시적인 트랜잭션 관리의 중요성을 다시 한번 확인했습니다. 