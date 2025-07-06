# Context7 사용 시 예상 난관 분석

## 📋 개요
HSCode 상세페이지 정보 준비 (작업 B) 구현 시 Context7 MCP 도구 사용에서 예상되는 주요 난관들을 분석합니다.

## 🚨 주요 난관들

### 1. **FastAPI StreamingResponse와 Context7의 비동기 처리 충돌**

#### 문제점
- **FastAPI SSE 스트리밍**: 실시간 이벤트 전송이 필요함
- **Context7 API 호출**: 동기적 특성으로 인한 blocking 가능성
- **병렬 처리**: 3단계 병렬 처리 중 Context7 호출이 전체 성능에 영향

#### Context7 제약사항
```python
# Context7는 동기적 호출이 기본
mcp_context7_resolve_library_id(libraryName="fastapi")
mcp_context7_get_library_docs(context7CompatibleLibraryID="/tiangolo/fastapi")

# 하지만 우리의 요구사항은 비동기 병렬 처리
async def prepare_detail_page_info():
    # 이 부분에서 Context7 호출이 blocking될 수 있음
    pass
```

### 2. **Pydantic 모델 검증과 Context7 응답 구조 불일치**

#### 문제점
- **우리의 모델**: 엄격한 타입 검증이 필요한 Pydantic 모델
- **Context7 응답**: 가변적이고 예측하기 어려운 구조

#### 예상 충돌 지점
```python
class DetailPageInfo(BaseModel):
    hscode: str
    confidence: float
    detail_buttons: List[DetailButton]
    # Context7에서 받은 데이터가 이 구조와 맞지 않을 수 있음
```

### 3. **실시간 SSE 이벤트 생성의 타이밍 문제**

#### 문제점
- **요구사항**: `detail_page_button_ready` 이벤트를 즉시 전송
- **Context7**: API 호출 시간이 가변적 (수초 소요 가능)
- **사용자 경험**: 로딩 스피너 표시 중 너무 오래 대기하면 UX 저하

## 🔧 예상 해결 방안

### 1. **비동기 래퍼 구현**
```python
import asyncio
import functools

async def async_context7_call(func, *args, **kwargs):
    """Context7 호출을 비동기로 래핑"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
```

### 2. **백그라운드 태스크 활용**
```python
async def stream_chat_response():
    # 즉시 로딩 이벤트 전송
    yield "event: detail_page_buttons_start\n"
    
    # Context7 호출을 백그라운드에서 실행
    background_tasks.add_task(prepare_detail_info_with_context7)
    
    # AI 응답은 병렬로 계속 스트리밍
    async for chunk in ai_response_stream:
        yield chunk
```

### 3. **Pydantic 모델 유연성 확보**
```python
class DetailPageInfo(BaseModel):
    model_config = ConfigDict(
        extra='ignore',  # 추가 필드 무시
        str_strip_whitespace=True,
        validate_default=True
    )
    
    hscode: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
```

## ⚠️ 리스크 요소

### 높은 리스크 🔴
1. **Context7 API 응답 시간 불확실성**
2. **병렬 처리 시 리소스 경합 가능성**
3. **SSE 연결 끊김 시 Context7 호출 중단 처리**

### 중간 리스크 🟡
1. **Context7 응답 데이터 구조 변경 가능성**
2. **메모리 사용량 증가 (여러 Context7 호출 동시 실행)**

### 낮은 리스크 🟢
1. **Pydantic 모델 스키마 불일치** (해결 방안 명확)
2. **로깅 및 모니터링 구현** (기존 인프라 활용 가능)

## 🎯 권장 접근법

### Phase 1: 기본 구조 검증
- Context7 API 호출 테스트
- 기본적인 비동기 래퍼 구현
- 간단한 SSE 이벤트 생성 테스트

### Phase 2: 병렬 처리 최적화
- 실제 병렬 처리 성능 측정
- 백그라운드 태스크 안정성 검증
- 에러 핸들링 강화

### Phase 3: 프로덕션 준비
- 부하 테스트 및 성능 튜닝
- 모니터링 및 알림 시스템 구축
- 장애 복구 프로세스 수립

## 📊 다음 단계

1. **기술적 상세 설계** (2단계 문서)
2. **구현 계획 및 일정** (3단계 문서)
3. **테스트 전략** (4단계 문서)
4. **배포 및 모니터링 계획** (5단계 문서) 