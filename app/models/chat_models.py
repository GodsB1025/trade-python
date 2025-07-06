"""
채팅 세션 및 상태 관리 모델
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import uuid
from dataclasses import dataclass, field
from .schemas import ChatMessage, SearchResult
from pydantic import BaseModel, Field


@dataclass
class ConversationSession:
    """대화 세션 관리 클래스"""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    messages: List[ChatMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)
    search_history: List[str] = field(default_factory=list)

    def add_message(self, message: ChatMessage) -> None:
        """메시지 추가"""
        self.messages.append(message)
        self.last_activity = datetime.now()

    def get_recent_messages(self, limit: int = 10) -> List[ChatMessage]:
        """최근 메시지 반환"""
        return self.messages[-limit:] if len(self.messages) > limit else self.messages

    def is_expired(self, timeout_minutes: int = 60) -> bool:
        """세션 만료 확인"""
        timeout = timedelta(minutes=timeout_minutes)
        return datetime.now() - self.last_activity > timeout

    def add_search_query(self, query: str) -> None:
        """검색 기록 추가"""
        self.search_history.append(query)
        self.last_activity = datetime.now()


class SessionManager:
    """세션 관리자 클래스"""

    def __init__(self):
        self._sessions: Dict[str, ConversationSession] = {}

    def create_session(self) -> ConversationSession:
        """새 세션 생성"""
        session = ConversationSession()
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """세션 조회"""
        session = self._sessions.get(session_id)
        if session and session.is_expired():
            self.remove_session(session_id)
            return None
        return session

    def get_or_create_session(self, session_id: Optional[str]) -> ConversationSession:
        """세션 조회 또는 생성"""
        if session_id:
            session = self.get_session(session_id)
            if session:
                return session
        return self.create_session()

    def remove_session(self, session_id: str) -> bool:
        """세션 삭제"""
        return self._sessions.pop(session_id, None) is not None

    def cleanup_expired_sessions(self, timeout_minutes: int = 60) -> int:
        """만료된 세션 정리"""
        expired_sessions = [
            session_id
            for session_id, session in self._sessions.items()
            if session.is_expired(timeout_minutes)
        ]

        for session_id in expired_sessions:
            self.remove_session(session_id)

        return len(expired_sessions)

    def get_session_count(self) -> int:
        """활성 세션 수 반환"""
        return len(self._sessions)


@dataclass
class PromptChainContext:
    """프롬프트 체이닝 컨텍스트"""

    original_query: str
    search_results: List[SearchResult] = field(default_factory=list)
    intermediate_responses: List[str] = field(default_factory=list)
    reasoning_steps: List[str] = field(default_factory=list)
    confidence_scores: List[float] = field(default_factory=list)

    def add_search_results(self, results: List[SearchResult]) -> None:
        """검색 결과 추가"""
        self.search_results.extend(results)

    def add_reasoning_step(self, step: str, confidence: Optional[float] = None) -> None:
        """추론 단계 추가"""
        self.reasoning_steps.append(step)
        if confidence is not None:
            self.confidence_scores.append(confidence)

    def get_context_summary(self) -> str:
        """컨텍스트 요약 반환"""
        summary = f"원본 질문: {self.original_query}\n"
        if self.search_results:
            summary += f"검색 결과: {len(self.search_results)}개\n"
        if self.reasoning_steps:
            summary += f"추론 단계: {len(self.reasoning_steps)}단계\n"
        return summary


# 전역 세션 매니저 인스턴스
session_manager = SessionManager()


class ChatRequest(BaseModel):
    """
    /api/v1/chat 엔드포인트에 대한 요청 스키마.
    구현계획.md vFinal 및 chat_endpoint_implementation_plan.md v1.0 기준.
    Java에서 생성한 session_uuid를 필수로 받음.
    """

    user_id: Optional[int] = Field(
        None, description="회원 ID. 없으면 비회원으로 간주함."
    )
    session_uuid: str = Field(
        ...,
        description="Java에서 생성한 채팅 세션의 UUID. 새 채팅 시작 시에도 Java에서 생성해서 전송함.",
    )
    message: str = Field(
        ..., min_length=1, max_length=5000, description="사용자의 질문 메시지"
    )


class StreamingChatResponse(BaseModel):
    """
    채팅 응답 스트림의 각 조각(chunk)에 대한 스키마.
    SSE(Server-Sent Events)의 `data` 필드에 JSON 형태로 전송됨.
    """

    type: str = Field(
        ..., description="이벤트의 종류 (예: 'token', 'metadata', 'error')"
    )
    data: dict = Field(..., description="이벤트와 관련된 데이터 페이로드")


# ==================================
# 화물통관 조회 응답 모델 (신규)
# ==================================


class CargoTrackingData(BaseModel):
    """Spring으로 전송할 화물통관 조회 데이터"""

    cargo_number: str = Field(..., description="추출된 화물번호")
    cargo_type: Optional[str] = Field(None, description="화물 유형 (추론)")
    extracted_patterns: List[str] = Field(
        default_factory=list, description="인식된 패턴들"
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="인식 신뢰도 (0.0-1.0)"
    )


class CargoTrackingResponse(BaseModel):
    """화물통관 조회 응답 스키마"""

    intent_type: str = Field(default="cargo_tracking", description="의도 유형")
    status: str = Field(..., description="처리 상태 (success, error)")
    message: str = Field(..., description="사용자 확인 메시지")

    # 성공 시 포함될 데이터
    cargo_data: Optional[CargoTrackingData] = Field(
        None, description="화물 조회 데이터"
    )
    spring_endpoint: Optional[str] = Field(
        None, description="Spring 전송 대상 엔드포인트"
    )

    # 메타데이터
    session_uuid: str = Field(..., description="세션 UUID")
    user_id: Optional[int] = Field(None, description="사용자 ID")
    processed_at: datetime = Field(
        default_factory=datetime.now, description="처리 시각"
    )
    processing_time_ms: int = Field(..., description="처리 시간 (밀리초)")

    # 에러 시 포함될 정보
    error_code: Optional[str] = Field(None, description="에러 코드")
    error_details: Optional[Dict[str, Any]] = Field(None, description="에러 상세 정보")


class CargoTrackingError(BaseModel):
    """화물통관 조회 에러 응답 스키마"""

    intent_type: str = Field(default="cargo_tracking", description="의도 유형")
    status: str = Field(default="error", description="처리 상태")
    error_code: str = Field(..., description="에러 코드")
    error_message: str = Field(..., description="에러 메시지")

    # 원본 요청 정보
    original_message: str = Field(..., description="원본 사용자 메시지")
    session_uuid: str = Field(..., description="세션 UUID")
    user_id: Optional[int] = Field(None, description="사용자 ID")

    # 추가 정보
    suggestions: List[str] = Field(default_factory=list, description="사용자 제안사항")
    retry_available: bool = Field(default=True, description="재시도 가능 여부")
    processed_at: datetime = Field(
        default_factory=datetime.now, description="처리 시각"
    )


# 화물번호 패턴 정의 (상수)
CARGO_NUMBER_PATTERNS = {
    "container": r"[A-Z]{4}[0-9]{7}",  # 컨테이너 번호: ABCD1234567
    "bl_number": r"[A-Z]{3}[0-9]{8,12}",  # B/L 번호: ABC12345678
    "awb_number": r"[0-9]{3}-?[0-9]{8}",  # AWB 번호: 123-12345678
    "tracking": r"[0-9]{10,15}",  # 일반 추적번호: 1234567890
    "korean_format": r"[0-9]{4}-[0-9]{4}-[0-9]{4}",  # 한국 형식: 1234-5678-9012
}

# 화물통관 조회 관련 키워드
CARGO_TRACKING_KEYWORDS = [
    "화물",
    "통관",
    "조회",
    "추적",
    "운송",
    "배송",
    "수입",
    "수출",
    "컨테이너",
    "선적",
    "항공",
    "해상",
    "육상",
    "물류",
    "bl",
    "awb",
    "tracking",
    "cargo",
    "shipment",
    "container",
    "화물번호",
    "추적번호",
    "운송장번호",
    "선적번호",
]
