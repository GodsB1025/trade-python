### **제목: `chat_service`의 불필요한 수동 채팅 기록 저장 로직 제거**

**날짜:** 2024-07-28

---

### **1. 문제 상황 (The Problem)**

이전 단계에서 `PostgresChatMessageHistory`를 비동기 네이티브 클래스로 성공적으로 리팩토링했음에도 불구하고, 채팅 API 호출 시 `NotImplementedError: 동기 \`add_message\`는 지원되지 않습니다. 대신 \`aadd_message\`를 사용하십시오.` 오류가 계속 발생했습니다.

오류의 발생 지점은 `app/services/chat_service.py` 내부에서 `history.add_message`를 호출하는 부분이었습니다.

### **2. 근본 원인 (The Root Cause)**

이번 문제의 근본 원인은 **`LangChain` 프레임워크의 핵심 기능에 대한 이해 부족**으로, `RunnableWithMessageHistory`의 역할과 중복되는 코드를 수동으로 작성한 것에 있습니다.

1.  **`RunnableWithMessageHistory`의 자동화 기능:** 이 클래스는 체인(Runnable)을 감싸, 체인의 실행 전후로 **자동으로** 대화 기록(입력 메시지, 출력 메시지)을 관리(조회 및 저장)하는 역할을 합니다. 즉, 개발자가 `history.add_message` 같은 메서드를 직접 호출할 필요가 없습니다.

2.  **불필요한 수동 로직:** `chat_service.py`의 `stream_chat_response` 메서드에서는 `RunnableWithMessageHistory`로 감싸진 체인을 실행한 후, `if history:` 블록에서 사용자의 질문과 AI의 답변을 `history.add_message`를 사용해 **수동으로 저장**하려 했습니다.

3.  **오류 발생 시나리오:**
    *   `chat_service.py`는 `RunnableWithMessageHistory`를 사용하여 체인을 실행했습니다. 이 과정에서 `LangChain`은 이미 내부적으로 `history.aget_messages()`를 호출하여 대화 기록을 가져왔습니다.
    *   체인 실행이 성공적으로 끝나자, `chat_service.py`는 불필요한 수동 저장 로직을 실행했습니다.
    *   이때 `await run_in_threadpool(history.add_message, ...)`를 호출했고, 이는 이전 단계에서 의도적으로 `NotImplementedError`를 발생시키도록 수정한 `PostgresChatMessageHistory`의 동기 메서드 `add_message`를 트리거하여 에러가 발생했습니다.

### **3. 해결 방안 (The Solution)**

`LangChain` 프레임워크의 기능을 신뢰하고, 중복되는 코드를 제거하여 아키텍처를 단순화하는 방향으로 문제를 해결했습니다.

1.  **수동 기록 로직 완전 제거:** `app/services/chat_service.py`의 `stream_chat_response` 메서드 내에서, 체인 실행 후에 `history.add_message`를 호출하던 `if history:` 블록 전체를 삭제했습니다. 이제 대화 기록 관리는 전적으로 `RunnableWithMessageHistory`의 자동화된 메커니즘에 의해 처리됩니다.

2.  **초기화 코드 간소화:** `PostgresChatMessageHistory`가 이미 비동기 세션을 직접 받을 수 있도록 수정되었으므로, 불필요한 `run_in_threadpool` 래퍼 없이 `history = PostgresChatMessageHistory(...)`와 같이 직접적으로 초기화하도록 코드를 수정하여 가독성과 효율성을 높였습니다.

이러한 수정을 통해 `chat_service`는 더 이상 프레임워크의 기능과 충돌하지 않게 되었습니다. 코드는 더 간결해지고, `LangChain`의 설계 의도에 부합하게 되어 안정성과 유지보수성이 크게 향상되었습니다. 