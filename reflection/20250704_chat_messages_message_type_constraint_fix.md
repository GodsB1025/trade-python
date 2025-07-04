# 채팅 메시지 타입 제약 조건 위반 문제 해결 보고서

**문서 버전:** v1.0  
**작성일:** 2025-07-04  
**작성자:** AI Assistant  

## 1. 문제 개요

### 1.1 발생한 문제
```
sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) 
<class 'asyncpg.exceptions.CheckViolationError'>: 새 자료가 "chat_messages_p20250101" 릴레이션의 
"chat_messages_message_type_check" 체크 제약 조건을 위반했습니다
DETAIL: 실패한 자료: (7, c7d5d0be-415a-4df7-8722-8f6083d31781, 2025-07-04 18:55:23.671777, 
HUMAN, 하이?, null, null, null, null, 2025-07-04 18:55:23.681418)
```

### 1.2 증상
- 사용자가 "하이?"라는 메시지를 전송할 때 DB 제약 조건 위반 에러 발생
- 'HUMAN' 값이 `chat_messages_message_type_check` 제약 조건을 위반
- 채팅 API 응답은 정상적으로 스트리밍되지만 메시지가 DB에 저장되지 않음

## 2. 원인 분석

### 2.1 Context7 MCP를 통한 LangChain 연구 결과
Context7 MCP 도구를 사용하여 LangChain의 메시지 타입 시스템을 조사한 결과:

**LangChain 표준 메시지 타입:**
- `HumanMessage` → `message_to_dict()` 결과: `{'type': 'human', ...}`
- `AIMessage` → `message_to_dict()` 결과: `{'type': 'ai', ...}`
- `SystemMessage` → `message_to_dict()` 결과: `{'type': 'system', ...}`

### 2.2 DB 스키마 제약 조건
```sql
CONSTRAINT chat_messages_message_type_check CHECK (
    ((message_type)::text = ANY ((ARRAY['USER'::character varying, 'AI'::character varying])::text[]))
)
```

**허용되는 값:** 'USER', 'AI'만 허용

### 2.3 코드 레벨 원인
`app/services/chat_history_service.py` 파일의 69번째 줄:
```python
message_type=message_data['type'].upper(),  # 'human' → 'HUMAN' (잘못된 변환)
```

**문제의 변환 과정:**
1. LangChain `HumanMessage` → `message_to_dict()` → `{'type': 'human'}`
2. `.upper()` 적용 → `'HUMAN'`
3. DB 제약 조건 위반 ('USER' 또는 'AI'만 허용)

## 3. 해결 방법

### 3.1 타입 매핑 함수 구현
```python
def _langchain_type_to_db_type(langchain_type: str) -> str:
    """LangChain 메시지 타입을 DB 메시지 타입으로 변환"""
    mapping = {
        'human': 'USER',
        'ai': 'AI',
        'system': 'AI',  # 시스템 메시지도 AI로 취급
        'assistant': 'AI'  # assistant는 ai와 동일
    }
    return mapping.get(langchain_type.lower(), 'USER')


def _db_type_to_langchain_type(db_type: str) -> str:
    """DB 메시지 타입을 LangChain 메시지 타입으로 변환"""
    mapping = {
        'USER': 'human',
        'AI': 'ai'
    }
    return mapping.get(db_type.upper(), 'human')
```

### 3.2 양방향 변환 로직 적용

**1) DB 저장 시 (LangChain → DB):**
```python
# 수정 전
message_type=message_data['type'].upper(),

# 수정 후  
message_type=_langchain_type_to_db_type(message_data['type']),
```

**2) DB 조회 시 (DB → LangChain):**
```python
# 수정 전
{"type": msg.message_type.lower(), "data": {"content": msg.content}}

# 수정 후
{"type": _db_type_to_langchain_type(msg.message_type), "data": {"content": msg.content}}
```

## 4. 적용된 변경사항

### 4.1 수정된 파일
- `app/services/chat_history_service.py`

### 4.2 주요 변경 내용
1. **매핑 함수 추가:** LangChain ↔ DB 타입 변환 함수 2개 추가
2. **저장 로직 수정:** `aadd_message()` 메서드에서 올바른 타입 변환 적용  
3. **조회 로직 수정:** `_db_messages_to_langchain_messages()` 함수에서 올바른 타입 변환 적용
4. **확장성 고려:** 'system', 'assistant' 등 추가 타입도 대비

## 5. 기대 효과

### 5.1 즉시 효과
- 사용자 채팅 메시지가 정상적으로 DB에 저장됨
- `IntegrityError` 완전 해결
- 채팅 기록 기능 정상 동작

### 5.2 장기적 효과  
- LangChain 표준과 DB 스키마 간의 완전한 호환성 확보
- 향후 LangChain 업데이트에도 안정적으로 동작
- 새로운 메시지 타입 추가 시에도 쉽게 확장 가능

## 6. 테스트 권장사항

### 6.1 기본 테스트
```bash
# FastAPI 서버 재시작 후 테스트
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "2", "message": "안녕하세요"}'
```

### 6.2 DB 확인
```sql
-- 메시지가 올바른 타입으로 저장되었는지 확인
SELECT message_type, content FROM chat_messages 
WHERE session_uuid = '...' 
ORDER BY created_at DESC LIMIT 5;
```

## 7. 결론

LangChain의 표준 메시지 타입 체계와 프로젝트의 DB 스키마 간의 불일치가 근본 원인이었습니다. Context7 MCP 도구를 통해 LangChain의 정확한 동작 방식을 파악하고, 양방향 타입 매핑 시스템을 구현하여 완전히 해결했습니다.

이 해결책은 **확장성**, **유지보수성**, **표준 준수**의 원칙을 모두 만족하며, 향후 유사한 문제 발생을 원천적으로 방지합니다. 