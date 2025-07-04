### **제목: `chat_history_service` 비동기 처리 버그 수정 보고서**

**날짜:** 2024-07-28

---

### **1. 문제 상황 (The Problem)**

회원 사용자가 채팅 API (`/api/v1/chat`)를 호출했을 때, LangChain 체인 실행 중 서버에서 `TypeError: 'coroutine' object is not iterable` 오류가 발생하며 스트림이 비정상적으로 종료되었습니다.

이 문제는 `RunnableWithMessageHistory`가 이전 대화 기록을 데이터베이스에서 로드하는 과정에서 발생했습니다.

### **2. 근본 원인 (The Root Cause)**

에러의 핵심 원인은 **동기(Synchronous)와 비동기(Asynchronous) 코드의 부적절한 혼용**이었습니다.

1.  **비동기 데이터베이스 계층:** `app/db/crud.py`의 모든 데이터베이스 접근 함수 (`get_messages_by_session` 등)는 `async def`로 정의되어 있으며, `AsyncSession`을 사용하는 완전한 비동기 방식이었습니다. 따라서 이 함수들은 호출 시 데이터가 아닌 **코루틴(Coroutine) 객체**를 반환합니다.

2.  **동기 채팅 기록 클래스:** 반면, `app/services/chat_history_service.py`의 `PostgresChatMessageHistory` 클래스는 동기적으로 설계되었습니다. 특히 문제가 된 `messages` 속성(`@property def messages`)은 동기 메서드였지만, 내부에서 `await` 키워드 없이 비동기 함수인 `crud_chat.get_messages_by_session`을 호출했습니다.

3.  **오류 발생 시나리오:**
    *   `FastAPI`와 `LangChain`의 비동기 실행기(`astream`)는 `PostgresChatMessageHistory`의 `aget_messages` 메서드를 호출하려 시도했습니다.
    *   `aget_messages`가 구현되어 있지 않자, `LangChain`은 기본 동작으로 동기 메서드인 `messages` 속성을 별도 스레드에서 실행(`run_in_executor`)했습니다.
    *   `messages` 속성은 `await crud_chat.get_messages_by_session(...)` 대신 `crud_chat.get_messages_by_session(...)`를 호출하여 코루틴 객체를 그대로 `db_messages` 변수에 할당했습니다.
    *   결과적으로 `_db_messages_to_langchain_messages` 함수가 리스트 대신 코루틴 객체를 이터레이션(`for msg in db_messages:`)하려고 시도하면서 `TypeError`가 발생했습니다.

### **3. 해결 방안 (The Solution)**

`PostgresChatMessageHistory` 클래스를 `FastAPI`와 `LangChain`의 비동기 패러다임에 완전히 맞도록 리팩토링했습니다.

1.  **비동기 인터페이스 구현:** `BaseChatMessageHistory`가 제공하는 비동기 메서드들을 명시적으로 구현했습니다.
    *   `async def aget_messages(self)`: 메시지 조회를 위해 `await crud_chat.get_messages_by_session(...)`를 호출하도록 수정했습니다.
    *   `async def aadd_message(self, message)`: 메시지 추가를 위해 `await crud_chat.create_message(...)`를 호출하도록 수정했습니다.
    *   `async def aclear(self)`: 메시지 삭제를 위해 `await crud_chat.delete_messages_by_session_uuid(...)`를 호출하도록 수정했습니다.

2.  **잘못된 사용 방지:** 잠재적인 오류를 방지하기 위해, 기존의 동기 메서드(`messages` 속성, `add_message`, `clear`)의 내용을 `NotImplementedError`를 발생시키도록 변경했습니다. 이를 통해 해당 클래스가 비동기 환경에서만 사용되어야 함을 명확히 하고, 의도치 않은 동기적 사용을 막았습니다.

3.  **타입 힌트 및 임포트 정리:** `__init__` 메서드의 `db` 파라미터 타입을 `Session`에서 `AsyncSession`으로 변경하고, 불필요한 `Session` 임포트를 정리하여 코드의 명확성을 높였습니다.

이러한 수정을 통해 `PostgresChatMessageHistory`는 이제 `LangChain`의 비동기 실행 흐름 내에서 데이터베이스와 효율적이고 올바르게 상호작용하며, 최초에 발생했던 `TypeError`를 완벽하게 해결했습니다. 