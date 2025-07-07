"""
데이터베이스 테이블 스키마 (SQLAlchemy 모델)
"""

import enum
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    Enum as SQLAlchemyEnum,
    Computed,
    Index,
    ForeignKeyConstraint,
    Numeric,
    Float,
    text,
    desc,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, BIGINT, ARRAY
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import relationship, declarative_base, Mapped, mapped_column
from sqlalchemy import func
from pgvector.sqlalchemy import Vector

Base = declarative_base()


# --- ENUM Type Definitions (from 구현계획.md) ---


class BookmarkType(enum.Enum):
    HS_CODE = "HS_CODE"
    CARGO = "CARGO"


class FeedType(enum.Enum):
    HS_CODE_TARIFF_CHANGE = "HS_CODE_TARIFF_CHANGE"
    HS_CODE_REGULATION_UPDATE = "HS_CODE_REGULATION_UPDATE"
    CARGO_STATUS_UPDATE = "CARGO_STATUS_UPDATE"
    TRADE_NEWS = "TRADE_NEWS"
    POLICY_UPDATE = "POLICY_UPDATE"


class TargetType(enum.Enum):
    HS_CODE = "HS_CODE"
    CARGO = "CARGO"


class ImportanceLevel(enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# --- Model Definitions ---


class User(Base):
    """사용자 테이블 모델"""

    __tablename__ = "users"

    # 계획서의 다른 테이블 FK가 BIGINT를 참조하므로 일관성을 위해 BIGINT로 변경
    # PK는 자동으로 인덱스가 생성되므로 index=True는 불필요
    id = Column(BIGINT, primary_key=True)
    email = Column(
        String(255), nullable=False, unique=True, index=True
    )  # DDL의 idx_users_email 에 해당
    # name, created_at 등 Spring Boot에서 관리하는 다른 필드는 여기에서 제외할 수 있음
    # 단, ORM 관계에 필요하다면 최소한으로 유지
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chat_sessions = relationship(
        "ChatSession", back_populates="user", cascade="all, delete-orphan"
    )
    bookmarks = relationship(
        "Bookmark", back_populates="user", cascade="all, delete-orphan"
    )
    update_feeds = relationship(
        "UpdateFeed", back_populates="user", cascade="all, delete-orphan"
    )


class TradeNews(Base):
    """무역 뉴스 테이블 모델 (`스키마.md` 기준)"""

    __tablename__ = "trade_news"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text)
    source_name = Column(String(200), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False)
    source_url = Column(String(1000), nullable=True)
    category = Column(String(50), index=True, nullable=True)
    priority = Column(Integer, nullable=False, default=1)
    fetched_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "title", "published_at", name="uq_trade_news_title_published_at"
        ),
        Index("idx_trade_news_priority", "priority", desc("published_at")),
        Index("idx_trade_news_published", desc("published_at")),
        Index("idx_trade_news_category", "category"),
    )


class ChatSession(Base):
    """채팅 세션 테이블 모델 - 방안1: 파티셔닝 제거, 단순화"""

    __tablename__ = "chat_sessions"

    session_uuid: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        comment="세션 UUID - 단일 기본키",
    )
    user_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
        comment="세션 생성 시간 - 인덱스로 성능 보장",
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    session_title: Mapped[Optional[str]] = mapped_column(String(255))
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped["User"] = relationship("User", back_populates="chat_sessions")
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        primaryjoin="ChatSession.session_uuid==foreign(ChatMessage.session_uuid)",
        foreign_keys="[ChatMessage.session_uuid]",
    )

    __table_args__ = (
        Index("idx_chat_sessions_user_id", "user_id"),
        Index("idx_chat_sessions_created_at", desc("created_at")),
        Index("idx_chat_sessions_user_created", "user_id", desc("created_at")),
    )


class ChatMessage(Base):
    """채팅 메시지 테이블 모델 - 방안1: 파티셔닝 제거, 단순화"""

    __tablename__ = "chat_messages"

    message_id = Column(BIGINT, primary_key=True, autoincrement=True)
    session_uuid = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.session_uuid", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="세션 UUID - 단순화된 외래키",
    )
    message_type = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    ai_model = Column(String(100))
    thinking_process = Column(Text)
    hscode_analysis = Column(JSONB)
    sse_bookmark_data = Column(JSONB)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
        comment="메시지 생성 시간",
    )

    session = relationship("ChatSession", back_populates="messages")

    __table_args__ = (
        CheckConstraint(
            "message_type IN ('USER', 'AI')", name="chat_messages_message_type_check"
        ),
        Index("idx_chat_messages_session_uuid", "session_uuid"),
        Index("idx_chat_messages_created_at", desc("created_at")),
        Index("idx_chat_messages_message_type", "message_type"),
        Index(
            "idx_chat_messages_hscode_analysis",
            "hscode_analysis",
            postgresql_using="gin",
            postgresql_where=text("hscode_analysis IS NOT NULL"),
        ),
        Index(
            "idx_chat_messages_sse_bookmark",
            "sse_bookmark_data",
            postgresql_using="gin",
            postgresql_where=text("sse_bookmark_data IS NOT NULL"),
        ),
    )


class Bookmark(Base):
    """북마크 테이블 모델 - 구현계획.md v6.3 기준"""

    __tablename__ = "bookmarks"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    user_id = Column(
        BIGINT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type = Column(SQLAlchemyEnum(BookmarkType, name="bookmark_type"), nullable=False)
    target_value = Column(String(50), nullable=False)
    display_name = Column(String(200))
    sse_generated = Column(Boolean, nullable=False, default=False)
    sse_event_data = Column(JSONB)
    sms_notification_enabled = Column(Boolean, nullable=False, default=False)
    email_notification_enabled = Column(Boolean, nullable=False, default=True)
    monitoring_active = Column(
        Boolean,
        Computed(
            "sms_notification_enabled OR email_notification_enabled", persisted=True
        ),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="bookmarks")
    update_feeds = relationship(
        "UpdateFeed",
        primaryjoin="and_(Bookmark.user_id == foreign(UpdateFeed.user_id), "
        "Bookmark.type == foreign(UpdateFeed.target_type), "
        "Bookmark.target_value == foreign(UpdateFeed.target_value))",
        back_populates="bookmark",
        cascade="all, delete-orphan",
        viewonly=True,  # 이 관계는 조회용으로만 사용
    )

    __table_args__ = (
        UniqueConstraint("user_id", "target_value", name="_user_target_value_uc"),
        Index(
            "idx_bookmarks_monitoring_active",
            "monitoring_active",
            postgresql_where=text("monitoring_active IS TRUE"),
        ),
    )


class UpdateFeed(Base):
    """업데이트 피드 테이블 모델 - 구현계획.md v6.3 기준"""

    __tablename__ = "update_feeds"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    user_id = Column(
        BIGINT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Bookmark가 삭제되어도 피드는 남아야 할 수 있으므로 bookmark_id는 FK가 아닐 수 있음.
    # 하지만 계획서상으로는 사용자가 삭제되면 피드도 삭제되므로 user_id FK는 유지.
    # 북마크와의 직접적인 관계는 target_value로 찾는 것이 더 유연할 수 있음.
    # 여기서는 계획서에 명시된 user_id FK만 유지하고, bookmark_id는 삭제.
    feed_type = Column(SQLAlchemyEnum(FeedType, name="feed_type"), nullable=False)
    target_type = Column(SQLAlchemyEnum(TargetType, name="target_type"))
    target_value = Column(String(50))
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    source_url = Column(String(1000))
    importance = Column(
        SQLAlchemyEnum(ImportanceLevel, name="importance_level"),
        nullable=False,
        default=ImportanceLevel.MEDIUM,
    )
    is_read = Column(Boolean, nullable=False, default=False)
    included_in_daily_notification = Column(Boolean, nullable=False, default=False)
    daily_notification_sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="update_feeds")
    bookmark = relationship(
        "Bookmark",
        primaryjoin="and_(foreign(UpdateFeed.user_id) == Bookmark.user_id, "
        "foreign(UpdateFeed.target_type) == Bookmark.type, "
        "foreign(UpdateFeed.target_value) == Bookmark.target_value)",
        back_populates="update_feeds",
        viewonly=True,  # 이 관계는 조회용으로만 사용
    )


class HscodeVector(Base):
    """HSCode 벡터 테이블 모델"""

    __tablename__ = "hscode_vectors"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    hscode = Column(String(20), nullable=False, unique=True)
    product_name = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    embedding = Column(Vector(1024), nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False, server_default="{}")
    classification_basis = Column(Text)
    similar_hscodes = Column(JSONB)
    keywords = Column(ARRAY(Text))
    web_search_context = Column(Text)
    hscode_differences = Column(Text)
    confidence_score = Column(Float, default=0.0)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "idx_hscode_vectors_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 32, "ef_construction": 128},
        ),
        Index("idx_hscode_vectors_metadata", "metadata", postgresql_using="gin"),
        Index("idx_hscode_vectors_keywords", "keywords", postgresql_using="gin"),
    )


class MonitorLog(Base):
    """AI 모델 사용 모니터링 로그 테이블 모델"""

    __tablename__ = "monitor_logs"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"))
    api_endpoint = Column(String(200), nullable=False)
    claude_model = Column(String(100), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    total_cost_usd = Column(Numeric(10, 6), nullable=False, default=0.0)
    response_time_ms = Column(Integer, nullable=False, default=0)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")

    __table_args__ = (
        Index("idx_monitor_logs_user_cost", "user_id", "created_at", "total_cost_usd"),
        Index("idx_monitor_logs_daily_stats", text("date(created_at)"), "claude_model"),
    )


class Langchain4jEmbedding(Base):
    """Langchain4j 임베딩 테이블 모델 (스키마 호환성)"""

    __tablename__ = "langchain4j_embedding"

    embedding_id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    embedding = Column(Vector(1024), nullable=False)
    # 'text' is a reserved keyword in some contexts
    text = Column("text", Text)
    metadata_ = Column("metadata", JSONB)

    __table_args__ = (
        Index(
            "idx_langchain4j_embedding_vector",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )


class Hscode(Base):
    """HSCode 테이블 모델 - chat_service.py에서 사용"""

    __tablename__ = "hscode"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, unique=True, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Document와의 관계
    documents = relationship("DocumentV2", back_populates="hscode")

    __table_args__ = (Index("idx_hscode_code", "code"),)


class DocumentV2(Base):
    """문서 저장 테이블 모델 - RAG 문서 저장용"""

    __tablename__ = "documents"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    hscode_id = Column(
        BIGINT, ForeignKey("hscode.id", ondelete="CASCADE"), nullable=False
    )
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False, server_default="{}")
    content_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # HSCode와의 관계
    hscode = relationship("Hscode", back_populates="documents")

    __table_args__ = (
        Index("idx_documents_hscode_id", "hscode_id"),
        Index("idx_documents_content_hash", "content_hash"),
    )


class DetailPageAnalysis(Base):
    """상세페이지 분석 결과 테이블 모델 - 방안1: 단순화된 외래키"""

    __tablename__ = "detail_page_analyses"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    session_uuid = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.session_uuid", ondelete="SET NULL"),
        index=True,
        nullable=True,
        comment="채팅 세션 UUID - 단순화된 외래키",
    )
    message_hash = Column(String(64), nullable=False, index=True)
    original_message = Column(Text, nullable=False)
    detected_intent = Column(String(50), nullable=False, index=True)
    detected_hscode = Column(String(20), index=True)
    confidence_score = Column(Float, nullable=False, default=0.0)
    processing_time_ms = Column(Integer, nullable=False, default=0)
    analysis_source = Column(String(50), nullable=False, index=True)
    analysis_metadata = Column(JSONB, nullable=False, server_default="{}")
    web_search_performed = Column(Boolean, nullable=False, default=False)
    web_search_results = Column(JSONB)

    # 상세 정보 컬럼들 추가
    tariff_info = Column(JSONB, server_default="{}")
    trade_agreement_info = Column(JSONB, server_default="{}")
    regulation_info = Column(JSONB, server_default="{}")
    non_tariff_info = Column(JSONB, server_default="{}")
    similar_hscodes_detailed = Column(JSONB, server_default="{}")
    market_analysis = Column(JSONB, server_default="{}")
    verification_status = Column(String(50), server_default="pending")
    expert_opinion = Column(Text)
    needs_update = Column(Boolean, server_default="FALSE")
    last_verified_at = Column(DateTime(timezone=True))
    data_quality_score = Column(Float, server_default="0.0")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 관계 설정
    user = relationship("User")
    buttons = relationship(
        "DetailPageButton", back_populates="analysis", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_detail_page_analyses_user_session", "user_id", "session_uuid"),
        Index("idx_detail_page_analyses_message_hash", "message_hash"),
        Index(
            "idx_detail_page_analyses_confidence",
            "confidence_score",
            postgresql_where=text("confidence_score >= 0.7"),
        ),
        Index(
            "idx_detail_page_analyses_web_search",
            "web_search_performed",
            postgresql_where=text("web_search_performed = true"),
        ),
        Index(
            "idx_detail_page_analyses_metadata",
            "analysis_metadata",
            postgresql_using="gin",
        ),
        # 새로운 인덱스들 추가
        Index(
            "idx_detail_page_analyses_verification_status",
            "verification_status",
            postgresql_where=text("verification_status != 'pending'"),
        ),
        Index(
            "idx_detail_page_analyses_needs_update",
            "needs_update",
            postgresql_where=text("needs_update = TRUE"),
        ),
        Index(
            "idx_detail_page_analyses_data_quality",
            "data_quality_score",
            postgresql_where=text("data_quality_score >= 0.8"),
        ),
        Index(
            "idx_detail_page_analyses_tariff_info",
            "tariff_info",
            postgresql_using="gin",
        ),
        Index(
            "idx_detail_page_analyses_regulation_info",
            "regulation_info",
            postgresql_using="gin",
        ),
        Index(
            "idx_detail_page_analyses_non_tariff_info",
            "non_tariff_info",
            postgresql_using="gin",
        ),
        Index(
            "idx_detail_page_analyses_market_analysis",
            "market_analysis",
            postgresql_using="gin",
        ),
    )


class DetailPageButton(Base):
    """상세페이지 버튼 정보 테이블 모델"""

    __tablename__ = "detail_page_buttons"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    analysis_id = Column(
        BIGINT,
        ForeignKey("detail_page_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    button_type = Column(String(50), nullable=False, index=True)
    label = Column(String(200), nullable=False)
    url = Column(String(500), nullable=False)
    query_params = Column(JSONB, nullable=False, server_default="{}")
    priority = Column(Integer, nullable=False, default=1, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계 설정
    analysis = relationship("DetailPageAnalysis", back_populates="buttons")

    __table_args__ = (
        Index(
            "idx_detail_page_buttons_active",
            "is_active",
            postgresql_where=text("is_active = true"),
        ),
    )


class WebSearchCache(Base):
    """웹 검색 결과 캐시 테이블 모델"""

    __tablename__ = "web_search_cache"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    search_query_hash = Column(String(64), nullable=False, unique=True, index=True)
    search_query = Column(Text, nullable=False)
    search_type = Column(String(50), nullable=False, index=True)
    search_results = Column(JSONB, nullable=False)
    result_count = Column(Integer, nullable=False, default=0)
    search_provider = Column(String(50), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_web_search_cache_created", desc("created_at")),)
