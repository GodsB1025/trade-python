"""
API 요청/응답 스키마 정의
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime
from enum import Enum
from uuid import UUID

from .db_models import BookmarkType, FeedType, TargetType, ImportanceLevel


class SearchType(str, Enum):
    """웹 검색 타입 열거형"""

    GENERAL = "general"
    NEWS = "news"
    ACADEMIC = "academic"
    TECHNICAL = "technical"


class SearchRequest(BaseModel):
    """웹 검색 요청 스키마"""

    query: str = Field(..., description="검색 쿼리")
    search_types: List[SearchType] = Field(
        default=[SearchType.GENERAL], description="검색 타입 목록"
    )
    max_results_per_search: int = Field(
        default=5, ge=1, le=10, description="검색당 최대 결과 수"
    )
    use_prompt_chaining: bool = Field(
        default=True, description="프롬프트 체이닝 사용 여부"
    )


class ChatMessageRequest(BaseModel):
    """API 요청용 채팅 메시지 스키마"""

    role: str = Field(..., description="메시지 역할 (user/assistant/system)")
    content: str = Field(..., description="메시지 내용")
    timestamp: datetime = Field(default_factory=datetime.now, description="메시지 시각")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="추가 메타데이터"
    )


class ChatContext(BaseModel):
    userAgent: Optional[str] = None
    language: Optional[str] = None


class ChatRequest(BaseModel):
    """/api/chat 요청 본문 스키마"""

    question: str = Field(
        ..., min_length=1, max_length=4000, description="사용자의 자연어 질문"
    )
    userId: Optional[int] = Field(
        None, description="회원 ID. 없으면 비회원(게스트)으로 간주함."
    )
    sessionId: Optional[str] = Field(None, description="기존 채팅 세션 ID (UUID 형식)")
    context: Optional[ChatContext] = Field(None, description="추가 컨텍스트 정보")


class SearchResult(BaseModel):
    """개별 검색 결과"""

    title: str = Field(..., description="검색 결과 제목")
    url: str = Field(..., description="검색 결과 URL")
    snippet: str = Field(..., description="검색 결과 요약")
    search_type: SearchType = Field(..., description="검색 타입")
    relevance_score: Optional[float] = Field(default=None, description="관련성 점수")


class WebSearchResults(BaseModel):
    """웹 검색 결과 집합"""

    query: str = Field(..., description="검색 쿼리")
    total_results: int = Field(..., description="총 결과 수")
    results: List[SearchResult] = Field(..., description="검색 결과 목록")
    search_duration_ms: int = Field(..., description="검색 소요 시간 (밀리초)")


class AIResponse(BaseModel):
    """AI 응답 스키마"""

    content: str = Field(..., description="AI 응답 내용")
    confidence_score: Optional[float] = Field(default=None, description="응답 신뢰도")
    sources_used: List[str] = Field(
        default_factory=list, description="참조한 소스 목록"
    )
    reasoning_steps: Optional[List[str]] = Field(default=None, description="추론 과정")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="추가 메타데이터"
    )


class ChatResponse(BaseModel):
    """채팅 응답 스키마"""

    message: str = Field(..., description="AI 응답 메시지")
    session_id: str = Field(..., description="세션 ID")
    ai_response: AIResponse = Field(..., description="AI 상세 응답")
    web_search_results: Optional[WebSearchResults] = Field(
        default=None, description="웹 검색 결과"
    )
    conversation_history: List[ChatMessageRequest] = Field(..., description="대화 이력")
    processing_time_ms: int = Field(..., description="처리 시간 (밀리초)")
    timestamp: datetime = Field(default_factory=datetime.now, description="응답 시각")


class ErrorResponse(BaseModel):
    """에러 응답 스키마"""

    error_code: str = Field(..., description="에러 코드")
    error_message: str = Field(..., description="에러 메시지")
    details: Optional[Dict[str, Any]] = Field(default=None, description="에러 상세")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="에러 발생 시각"
    )


class HealthCheckResponse(BaseModel):
    """헬스체크 응답 스키마"""

    status: str = Field(..., description="서비스 상태")
    version: str = Field(..., description="애플리케이션 버전")
    anthropic_connection: bool = Field(..., description="Anthropic API 연결 상태")
    timestamp: datetime = Field(default_factory=datetime.now, description="체크 시각")


# ==================================
# SSE 스트리밍 이벤트 스키마 (v6.1 기준)
# ==================================


class SSEInitialMetadata(BaseModel):
    claudeIntent: str
    estimatedTime: int
    isAuthenticated: bool
    sessionCreated: bool
    sessionId: Optional[str]
    ragEnabled: bool
    parallelProcessing: bool


class SSESessionInfo(BaseModel):
    isAuthenticated: bool
    userType: Literal["MEMBER", "GUEST"]
    sessionId: Optional[str]
    recordingEnabled: bool
    message: str


class SSEThinking(BaseModel):
    stage: str
    content: str
    progress: int
    userType: Optional[Literal["MEMBER"]] = None


class SSEMainMessageStart(BaseModel):
    type: Literal["start"]
    timestamp: datetime = Field(default_factory=datetime.now)


class SSEBookmarkData(BaseModel):
    available: bool
    hsCode: Optional[str] = None
    productName: Optional[str] = None
    confidence: Optional[float] = None


class SSEMainMessageComplete(BaseModel):
    type: Literal["metadata"]
    sources: List[Dict[str, Any]]
    relatedInfo: Dict[str, Any]
    processingTime: int
    sessionId: Optional[str]
    ragSources: List[str]
    cacheHit: bool
    bookmarkData: SSEBookmarkData


class SSEMainMessageData(BaseModel):
    type: Literal["content"]
    content: str


class SSEDetailedPageButton(BaseModel):
    type: Literal["button"]
    buttonType: Literal["HS_CODE", "REGULATION", "STATISTICS"]
    priority: int
    url: str
    title: str
    description: str
    isReady: bool


class SSEDetailedPageButtonsStart(BaseModel):
    type: Literal["start"]
    timestamp: datetime = Field(default_factory=datetime.now)
    buttonsCount: int


class SSEDetailedPageButtonsComplete(BaseModel):
    type: Literal["complete"]
    timestamp: datetime = Field(default_factory=datetime.now)
    totalPreparationTime: int


class SSEMemeberSessionCreated(BaseModel):
    type: Literal["session_created"]
    sessionId: str
    isFirstMessage: bool
    timestamp: datetime = Field(default_factory=datetime.now)


class SSEMemeberRecordSaved(BaseModel):
    type: Literal["record_saved"]
    sessionId: str
    messageCount: int
    partitionYear: int
    timestamp: datetime = Field(default_factory=datetime.now)


# ==================================
# DB 모델과 동기화된 Pydantic 스키마 (v6.3 기준)
# ==================================

# --- TradeNews 스키마 ---


class TradeNewsBase(BaseModel):
    """무역 뉴스 기본 스키마"""

    title: str = Field(..., max_length=500)
    summary: Optional[str] = None
    source_name: str = Field(..., max_length=200)
    published_at: datetime
    source_url: Optional[HttpUrl] = None
    category: Optional[str] = Field(None, max_length=50)
    priority: int = 1
    fetched_at: datetime


class TradeNewsCreate(TradeNewsBase):
    """무역 뉴스 생성용 스키마"""

    pass


class TradeNews(TradeNewsBase):
    """DB 조회용 무역 뉴스 스키마"""

    id: int

    class Config:
        from_attributes = True


# --- Bookmark 스키마 ---


class BookmarkBase(BaseModel):
    """북마크 기본 스키마"""

    user_id: int
    type: BookmarkType
    target_value: str = Field(..., max_length=50)
    display_name: Optional[str] = Field(None, max_length=200)
    sse_generated: bool = False
    sse_event_data: Optional[Dict[str, Any]] = None
    sms_notification_enabled: bool = False
    email_notification_enabled: bool = True


class BookmarkCreate(BookmarkBase):
    """북마크 생성용 스키마"""

    pass


class Bookmark(BookmarkBase):
    """DB 조회용 북마크 스키마"""

    id: int
    monitoring_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- UpdateFeed 스키마 ---


class UpdateFeedBase(BaseModel):
    """업데이트 피드 기본 스키마"""

    user_id: int
    feed_type: FeedType
    target_type: Optional[TargetType] = None
    target_value: Optional[str] = Field(None, max_length=50)
    title: str = Field(..., max_length=500)
    content: str
    source_url: Optional[HttpUrl] = None
    importance: ImportanceLevel = ImportanceLevel.MEDIUM


class UpdateFeedCreate(UpdateFeedBase):
    """업데이트 피드 생성용 스키마"""

    pass


class UpdateFeed(UpdateFeedBase):
    """DB 조회용 업데이트 피드 스키마"""

    id: int
    is_read: bool
    included_in_daily_notification: bool
    daily_notification_sent_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ==================================
# 북마크 모니터링 스키마
# ==================================
class MonitoringResult(BaseModel):
    """북마크 모니터링 결과 스키마"""

    status: str = Field(default="success", description="작업 상태")
    monitored_bookmarks: int = Field(..., description="모니터링한 총 북마크 수")
    updates_found: int = Field(..., description="발견된 총 업데이트 수")


# ==================================
# DB 연동을 위한 채팅 스키마
# ==================================


class ChatMessageBase(BaseModel):
    """채팅 메시지 기본 스키마"""

    message_type: str
    content: str
    ai_model: Optional[str] = None
    thinking_process: Optional[str] = None
    hscode_analysis: Optional[dict] = None
    sse_bookmark_data: Optional[dict] = None


class ChatMessageCreate(ChatMessageBase):
    """채팅 메시지 생성용 스키마"""

    session_uuid: UUID
    session_created_at: datetime


class ChatMessage(ChatMessageBase):
    """DB 조회용 채팅 메시지 스키마"""

    message_id: int
    created_at: datetime
    session_uuid: UUID
    session_created_at: datetime

    class Config:
        from_attributes = True


class ChatSessionBase(BaseModel):
    """채팅 세션 기본 스키마"""

    user_id: int
    session_title: Optional[str] = None


class ChatSessionCreate(ChatSessionBase):
    """채팅 세션 생성용 스키마"""

    pass


class ChatSession(ChatSessionBase):
    """DB 조회용 채팅 세션 스키마"""

    session_uuid: UUID
    created_at: datetime
    message_count: int
    updated_at: datetime
    messages: List[ChatMessage] = []

    class Config:
        from_attributes = True


# ==================================
# 뉴스 기사 스키마
# ==================================

# ==================================
# 상세페이지 정보 준비 스키마 (작업 B)
# ==================================


class DetailButton(BaseModel):
    """상세페이지 버튼 정보"""

    type: Literal["HS_CODE", "REGULATION", "STATISTICS"]
    label: str = Field(..., description="버튼 레이블")
    url: str = Field(..., description="버튼 URL")
    query_params: Optional[Dict[str, str]] = Field(
        default=None, description="쿼리 파라미터"
    )
    priority: int = Field(..., description="버튼 우선순위")


class DetailPageInfo(BaseModel):
    """상세페이지 정보 모델"""

    hscode: Optional[str] = None
    detected_intent: str = Field(default="hscode_search")
    detail_buttons: List[DetailButton] = Field(default_factory=list)
    processing_time_ms: int = Field(default=0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    analysis_source: Literal["context7", "fallback", "cache"] = Field(
        default="fallback"
    )
    context7_metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Context7 분석 메타데이터"
    )


class Context7AnalysisResult(BaseModel):
    """Context7 분석 결과"""

    hscode_patterns: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    library_docs_used: List[str] = Field(default_factory=list)
    total_tokens: int = Field(default=0)
    api_calls: int = Field(default=0)
    processing_time_ms: int = Field(default=0)
    success: bool = Field(default=False)
