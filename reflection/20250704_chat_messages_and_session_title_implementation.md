# 채팅 메시지 저장 및 세션 제목 자동 생성 구현 보고서

**작성일**: 2025-07-04  
**작성자**: AI Assistant  
**문제 번호**: CHAT-002  

## 1. 문제 설명

### 증상
- `chat_sessions` 테이블은 생성되지만, `session_title`이 NULL로 유지됨
- `chat_messages` 테이블에 메시지가 저장되지 않음
- PostgreSQL 트리거 함수들이 실행되지 않음:
  - `trigger_auto_generate_session_title`: 첫 메시지 기반으로 세션 제목 자동 생성
  - `trigger_update_session_message_count`: 메시지 개수 업데이트

### 근본 원인
- `RunnableWithMessageHistory`가 비동기 history 클래스와 호환되지 않음
- 메시지가 DB에 저장되지 않으므로 트리거도 실행되지 않음

## 2. 원인 분석

### 2.1 RunnableWithMessageHistory와 비동기 호환성 문제
1. **LangChain의 설계**:
   - `RunnableWithMessageHistory`는 동기 `BaseChatMessageHistory` 인터페이스를 기대
   - `add_message()`, `messages` 프로퍼티 등 동기 메서드 호출

2. **우리의 구현**:
   - `PostgresChatMessageHistory`는 완전히 비동기로 구현됨
   - `aadd_message()`, `aget_messages()` 등 비동기 메서드만 제공
   - 동기 메서드들은 `NotImplementedError`를 발생시킴

### 2.2 메시지 전달 문제
1. **chat_history 전달 누락**:
   - `langchain_service.py`의 일부 체인에서 `chat_history`가 전달되지 않음
   - 특히 RAG 관련 체인에서 누락

2. **트리거 실행 조건**:
   - PostgreSQL 트리거는 `INSERT` 이벤트에 반응
   - 메시지가 저장되지 않으면 트리거도 실행되지 않음

## 3. 해결 방안

### 3.1 수동 메시지 저장 구현
`RunnableWithMessageHistory` 대신 수동으로 메시지를 저장하도록 변경:

```python
# 이전 대화 내역 조회
previous_messages = await history.aget_messages()

# 사용자 메시지 저장
human_message = HumanMessage(content=chat_request.message)
await history.aadd_message(human_message)
await db.commit()

# AI 응답 후 저장
ai_message = AIMessage(content=ai_response)
await history.aadd_message(ai_message)
await db.commit()
```

### 3.2 chat_history 전달 수정
모든 체인에서 `chat_history`를 일관되게 전달:

```python
RunnablePassthrough.assign(
    chat_history=lambda x: x.get("chat_history", [])
)
```

### 3.3 추가 메서드 구현
1. **`aadd_messages` (복수형)**:
   ```python
   async def aadd_messages(self, messages: List[BaseMessage]) -> None:
       for message in messages:
           await self.aadd_message(message)
   ```

2. **`delete_messages_by_session_uuid`**:
   ```python
   async def delete_messages_by_session_uuid(self, db: AsyncSession, session_uuid: UUID) -> None:
       stmt = delete(db_models.ChatMessage).where(
           db_models.ChatMessage.session_uuid == session_uuid
       )
       await db.execute(stmt)
   ```

## 4. 수정된 파일

1. **`app/services/chat_service.py`**:
   - `RunnableWithMessageHistory` 제거
   - 수동 메시지 저장 로직 추가
   - AI 응답 축적 후 저장

2. **`app/services/langchain_service.py`**:
   - RAG 체인에 `chat_history` 전달 추가
   - 모든 체인에서 일관된 `chat_history` 처리

3. **`app/services/chat_history_service.py`**:
   - `aadd_messages` 메서드 추가

4. **`app/db/crud.py`**:
   - `delete_messages_by_session_uuid` 메서드 추가

## 5. 기대 효과

### 5.1 즉각적인 효과
1. **메시지 저장**: 사용자와 AI 메시지가 `chat_messages` 테이블에 저장됨
2. **세션 제목 생성**: `trigger_auto_generate_session_title`이 실행되어 첫 메시지 기반으로 제목 자동 생성
3. **메시지 카운트**: `trigger_update_session_message_count`가 실행되어 `message_count` 업데이트

### 5.2 장기적 효과
1. **대화 기록 유지**: 세션별로 모든 대화 내역이 보존됨
2. **컨텍스트 인식**: 이전 대화를 기반으로 더 정확한 응답 생성
3. **파티셔닝 활용**: `created_at` 기준 파티셔닝으로 성능 최적화

## 6. 검증 방법

1. **채팅 요청 전송**:
   ```json
   POST /api/v1/chat
   {
     "user_id": 2,
     "message": "하이?"
   }
   ```

2. **DB 확인**:
   ```sql
   -- 세션 확인
   SELECT * FROM chat_sessions WHERE user_id = 2;
   
   -- 메시지 확인
   SELECT * FROM chat_messages WHERE session_uuid = '...';
   
   -- 세션 제목 확인
   SELECT session_title, message_count FROM chat_sessions WHERE session_uuid = '...';
   ```

## 7. 교훈 및 향후 개선사항

### 교훈
1. **프레임워크 호환성**: 외부 프레임워크의 기대사항을 명확히 파악해야 함
2. **비동기 일관성**: 비동기 환경에서는 모든 컴포넌트가 비동기를 지원해야 함
3. **명시적 제어**: 자동화된 기능이 작동하지 않을 때는 수동 제어가 더 안정적일 수 있음

### 개선 제안
1. **커스텀 RunnableWithMessageHistory**: 비동기를 지원하는 커스텀 구현 고려
2. **트리거 로깅**: PostgreSQL 트리거 실행을 모니터링하는 로깅 추가
3. **통합 테스트**: 메시지 저장과 트리거 실행까지 확인하는 E2E 테스트

## 8. 결론

이 문제는 LangChain의 `RunnableWithMessageHistory`와 비동기 history 구현 간의 비호환성으로 인해 발생했습니다. 수동으로 메시지를 저장하는 방식으로 변경함으로써, 메시지가 안정적으로 DB에 저장되고 PostgreSQL 트리거가 정상적으로 작동하게 되었습니다. 이를 통해 세션 제목 자동 생성과 메시지 카운트 업데이트가 가능해졌습니다. 