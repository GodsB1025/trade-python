### 문제 해결 보고서: `RunnableWithMessageHistory` Pydantic 유효성 검사 오류

**작성일:** 2024-07-27

---

### 1. 문제 상황 (What was the problem?)

회원 사용자가 채팅 API (`/api/v1/chat`)를 호출할 때, 서버에서 `500 Internal Server Error`가 발생하며 채팅 기능이 완전히 실패하는 문제가 발생했습니다.

로그 분석 결과, 오류의 근원지는 `app/services/chat_service.py` 파일 내에서 LangChain의 `RunnableWithMessageHistory` 클래스를 초기화하는 부분이었으며, 다음과 같은 `pydantic_core.ValidationError`가 발생하고 있었습니다.

```
pydantic_core._pydantic_core.ValidationError: 2 validation errors for RunnableWithMessageHistory
history_factory_config.0.id
  Missing required argument [type=missing_argument, ...]
history_factory_config.0.annotation
  Missing required argument [type=missing_argument, ...]
```

이 오류는 `RunnableWithMessageHistory` 생성에 필요한 `history_factory_config` 인자의 `id`와 `annotation` 필드가 누락되었음을 나타냅니다.

### 2. 원인 분석 (What was the cause?)

`Context7` (웹 검색)을 통해 LangChain 공식 문서를 심층 분석한 결과, 문제의 원인은 `RunnableWithMessageHistory`의 `history_factory_config` 파라미터에 대한 오해에서 비롯된 명백한 API 오사용이었습니다.

*   **잘못된 구현:** 기존 코드는 `history_factory_config`에 실제 세션 UUID 값(`{"session_id": "some-uuid-string"}`)을 직접 전달하고 있었습니다.
*   **올바른 사용법:** LangChain 공식 문서에 따르면, `history_factory_config`는 실제 값을 받는 곳이 아닙니다. 대신, 런타임에 어떤 설정 가능한 필드를 받을 것인지에 대한 **명세(Specification)**를 정의하는 곳입니다. 이 명세는 `ConfigurableFieldSpec` 클래스의 인스턴스 리스트 형태로 전달해야 합니다.
*   **결론:** Pydantic은 `ConfigurableFieldSpec` 객체를 기대하는 곳에 단순 `dict`가 들어오자, 필수 필드(`id`, `annotation` 등)가 누락되었다고 판단하여 `ValidationError`를 발생시켰습니다.

### 3. 해결 과정 (How was it solved?)

문제의 원인을 명확히 파악한 후, 다음과 같이 코드를 수정하여 문제를 해결했습니다.

1.  **`ConfigurableFieldSpec` 임포트:** 먼저 필요한 클래스를 `langchain_core.runnables`로부터 임포트했습니다.
    ```python
    from langchain_core.runnables import ConfigurableFieldSpec
    ```

2.  **`RunnableWithMessageHistory` 초기화 로직 수정:** `app/services/chat_service.py` 파일에서 `RunnableWithMessageHistory`를 생성하는 부분을 다음과 같이 LangChain 공식 문서의 가이드에 맞게 수정했습니다.

    *   **수정 전:**
        ```python
        chain_with_history = RunnableWithMessageHistory(
            # ... other args ...
            history_factory_config=[{"session_id": current_session_uuid}]
        )
        ```

    *   **수정 후:**
        ```python
        chain_with_history = RunnableWithMessageHistory(
            self.llm_service.chat_chain,
            get_history,
            input_messages_key="question",
            history_messages_key="chat_history",
            history_factory_config=[
                ConfigurableFieldSpec(
                    id="session_id",
                    annotation=str,
                    name="Session ID",
                )
            ],
        )
        ```
    이 수정은 `history_factory_config`에 "우리는 'session_id'라는 이름의 문자열 타입 설정 값을 받을 것입니다"라는 명세를 올바르게 정의하여 전달합니다.

3.  **실행 시 `config` 전달:** 체인을 실행하는 `.astream()` 호출 시에는 `config={"configurable": {"session_id": current_session_uuid}}` 와 같이 실제 `session_id` 값을 `configurable` 딕셔너리에 담아 전달하도록 했습니다. (이 부분은 이미 올바르게 구현되어 있었으나, 전체적인 맥락에서 재확인했습니다.)

이러한 수정을 통해 `Pydantic ValidationError`가 완전히 해결되었고, 회원 사용자의 채팅 기능이 의도한 대로 대화 기록을 관리하며 정상적으로 동작하게 되었습니다. 