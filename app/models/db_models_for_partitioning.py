"""
파티셔닝을 유지하는 경우의 DB 모델
migration_fix_partitioning_issue_v2.sql과 함께 사용
"""

from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    Boolean,
    Float,
    BigInteger as BIGINT,
    ForeignKey,
    Index,
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    Numeric,
    ARRAY,
    func,
    text,
    desc,
    Computed,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class ChatSession(Base):
    """채팅 세션 테이블 - 파티셔닝 유지 버전"""

    __tablename__ = "chat_sessions"

    session_uuid = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        comment="세션 UUID - 복합 기본키 일부",
    )
    created_at = Column(
        DateTime(timezone=True),
        primary_key=True,
        server_default=func.now(),
        comment="세션 생성 시간 - 파티션 키",
    )
    user_id = Column(
        BIGINT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_title = Column(String(255))
    message_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="chat_sessions")
    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        primaryjoin="and_(ChatSession.session_uuid==foreign(ChatMessage.session_uuid), ChatSession.created_at==foreign(ChatMessage.session_created_at))",
    )

    __table_args__ = (
        UniqueConstraint(
            "session_uuid", "created_at", name="chat_sessions_uuid_created_unique"
        ),
        Index("idx_chat_sessions_uuid_only", "session_uuid"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )


class ChatMessage(Base):
    """채팅 메시지 테이블 - 파티셔닝 유지 버전"""

    __tablename__ = "chat_messages"

    message_id = Column(BIGINT, primary_key=True, autoincrement=True)
    created_at = Column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    session_uuid = Column(UUID(as_uuid=True), nullable=False, index=True)
    session_created_at = Column(
        DateTime(timezone=True),
        nullable=True,  # 트리거가 자동으로 채움
        comment="세션 생성 시간 - 트리거가 자동 설정",
    )
    message_type = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    ai_model = Column(String(100))
    thinking_process = Column(Text)
    hscode_analysis = Column(JSONB)
    sse_bookmark_data = Column(JSONB)

    session = relationship("ChatSession", back_populates="messages")

    __table_args__ = (
        CheckConstraint(
            "message_type IN ('USER', 'AI')", name="chat_messages_message_type_check"
        ),
        Index("idx_chat_messages_session_uuid", "session_uuid"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )


class DetailPageAnalysis(Base):
    """상세페이지 분석 결과 테이블 - 파티셔닝 유지 버전"""

    __tablename__ = "detail_page_analyses"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    session_uuid = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="세션 UUID - 트리거로 참조 무결성 보장",
    )
    session_created_at = Column(
        DateTime(timezone=True),
        nullable=True,  # 트리거가 자동으로 채움
        comment="세션 생성 시간 - 트리거가 자동 설정",
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

    # 상세 정보 컬럼들
    tariff_info = Column(JSONB, server_default="{}")
    trade_agreement_info = Column(JSONB, server_default="{}")
    regulation_info = Column(JSONB, server_default="{}")
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
        Index("idx_detail_page_analyses_session_uuid", "session_uuid"),
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
    )
