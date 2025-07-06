"""
개선된 트랜잭션 처리 서비스
- 복잡한 세이브포인트 대신 단순한 트랜잭션 관리
- 백그라운드 작업과 메인 트랜잭션 동기화
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import BackgroundTasks

from app.models.db_models import ChatSession, DetailPageAnalysis
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class ImprovedTransactionService:
    """개선된 트랜잭션 처리 서비스"""

    @staticmethod
    async def create_session_with_commit(
        db: AsyncSession, user_id: int, session_uuid_str: str
    ) -> tuple[Optional[ChatSession], bool]:
        """
        세션 생성 후 즉시 커밋

        Returns:
            (session_obj, is_new_session)
        """
        try:
            from app.db import crud

            # 세션 생성/조회
            session_obj = await crud.chat.get_or_create_session(
                db=db, user_id=user_id, session_uuid_str=session_uuid_str
            )

            # 기존 세션인지 확인
            is_new_session = not hasattr(session_obj, "_existing")

            # 즉시 커밋하여 백그라운드 작업에서 볼 수 있게 함
            await db.commit()

            logger.info(
                f"세션 {'생성' if is_new_session else '조회'} 완료: {session_uuid_str}"
            )
            return session_obj, is_new_session

        except Exception as e:
            logger.error(f"세션 처리 중 오류: {e}", exc_info=True)
            await db.rollback()
            return None, False

    @staticmethod
    async def save_user_message_simple(db: AsyncSession, history, message: str) -> bool:
        """사용자 메시지 단순 저장"""
        try:
            from langchain_core.messages import HumanMessage

            human_message = HumanMessage(content=message)
            await history.aadd_message(human_message)
            await db.commit()

            logger.debug("사용자 메시지 저장 완료")
            return True

        except Exception as e:
            logger.error(f"사용자 메시지 저장 실패: {e}", exc_info=True)
            await db.rollback()
            return False

    @staticmethod
    async def save_ai_message_simple(
        db: AsyncSession, history, ai_response: str
    ) -> bool:
        """AI 메시지 단순 저장"""
        try:
            from langchain_core.messages import AIMessage

            ai_message = AIMessage(content=ai_response)
            await history.aadd_message(ai_message)
            await db.commit()

            logger.debug("AI 메시지 저장 완료")
            return True

        except Exception as e:
            logger.error(f"AI 메시지 저장 실패: {e}", exc_info=True)
            await db.rollback()
            return False

    @staticmethod
    async def update_session_title_simple(
        db: AsyncSession, session_obj: ChatSession, title: str
    ) -> bool:
        """세션 제목 단순 업데이트"""
        try:
            setattr(session_obj, "session_title", title)
            await db.commit()

            logger.info(f"세션 제목 업데이트 완료: {title}")
            return True

        except Exception as e:
            logger.error(f"세션 제목 업데이트 실패: {e}", exc_info=True)
            await db.rollback()
            return False

    @staticmethod
    async def schedule_background_analysis_after_commit(
        background_tasks: BackgroundTasks,
        hscode: str,
        product_description: str,
        user_context: str,
        message_hash: str,
        session_uuid: str,
        user_id: Optional[int] = None,
        delay_seconds: float = 1.0,
    ):
        """
        메인 트랜잭션 커밋 후 백그라운드 분석 실행
        delay를 주어 메인 트랜잭션이 완전히 커밋되도록 함
        """

        async def delayed_analysis_task():
            # 메인 트랜잭션 커밋 대기
            await asyncio.sleep(delay_seconds)

            try:
                await ImprovedTransactionService._background_analysis_with_retry(
                    hscode=hscode,
                    product_description=product_description,
                    user_context=user_context,
                    message_hash=message_hash,
                    session_uuid=session_uuid,
                    user_id=user_id,
                )
            except Exception as e:
                logger.error(f"백그라운드 분석 작업 실패: {e}", exc_info=True)

        background_tasks.add_task(delayed_analysis_task)

    @staticmethod
    async def _background_analysis_with_retry(
        hscode: str,
        product_description: str,
        user_context: str,
        message_hash: str,
        session_uuid: str,
        user_id: Optional[int] = None,
        max_retries: int = 3,
    ):
        """재시도 로직이 있는 백그라운드 분석"""

        from app.services.enhanced_detail_generator import EnhancedDetailGenerator

        for attempt in range(max_retries):
            try:
                async with SessionLocal() as bg_db:
                    # 세션 존재 확인 (단순화된 버전)
                    session_exists = (
                        await ImprovedTransactionService._check_session_exists(
                            bg_db, session_uuid
                        )
                    )

                    if not session_exists and attempt < max_retries - 1:
                        # 세션이 아직 보이지 않으면 잠시 대기 후 재시도
                        await asyncio.sleep(1.0 * (attempt + 1))  # 지수 백오프
                        continue

                    # 상세 정보 생성
                    detail_generator = EnhancedDetailGenerator()
                    enhanced_info = (
                        await detail_generator.generate_comprehensive_detail_info(
                            hscode=hscode,
                            product_description=product_description,
                            user_context=user_context,
                            db_session=bg_db,
                        )
                    )

                    # 분석 결과 저장 (단순화된 버전)
                    await ImprovedTransactionService._save_analysis_simple(
                        bg_db=bg_db,
                        message_hash=message_hash,
                        user_context=user_context,
                        hscode=hscode,
                        enhanced_info=enhanced_info,
                        session_uuid=session_uuid if session_exists else None,
                        user_id=user_id,
                    )

                    logger.info(f"백그라운드 분석 완료: {hscode}")
                    return

            except Exception as e:
                logger.warning(f"백그라운드 분석 시도 {attempt + 1} 실패: {e}")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))

    @staticmethod
    async def _check_session_exists(db: AsyncSession, session_uuid: str) -> bool:
        """세션 존재 여부 확인 (단순화)"""
        try:
            from uuid import UUID
            from sqlalchemy import select

            stmt = (
                select(ChatSession.session_uuid)
                .where(ChatSession.session_uuid == UUID(session_uuid))
                .limit(1)
            )

            result = await db.execute(stmt)
            return result.scalar() is not None

        except Exception as e:
            logger.warning(f"세션 존재 확인 실패: {e}")
            return False

    @staticmethod
    async def _save_analysis_simple(
        bg_db: AsyncSession,
        message_hash: str,
        user_context: str,
        hscode: str,
        enhanced_info: Dict[str, Any],
        session_uuid: Optional[str],
        user_id: Optional[int],
    ):
        """분석 결과 단순 저장"""
        try:
            # 기존 분석 결과 확인
            from sqlalchemy import select

            stmt = select(DetailPageAnalysis).where(
                DetailPageAnalysis.message_hash == message_hash
            )
            result = await bg_db.execute(stmt)
            existing_analysis = result.scalars().first()

            if existing_analysis:
                # 기존 레코드 업데이트
                for key, value in enhanced_info.items():
                    if hasattr(existing_analysis, key):
                        setattr(existing_analysis, key, value)

                setattr(existing_analysis, "last_verified_at", datetime.utcnow())

            else:
                # 새 레코드 생성 (단순화된 버전)
                new_analysis = DetailPageAnalysis(
                    user_id=user_id,
                    session_uuid=session_uuid,  # 방안1: 단순화된 외래키
                    message_hash=message_hash,
                    original_message=user_context,
                    detected_intent="hscode_analysis",
                    detected_hscode=hscode,
                    confidence_score=0.9,
                    processing_time_ms=0,
                    analysis_source="enhanced_ai_generation",
                    analysis_metadata=enhanced_info.get("generation_metadata", {}),
                    web_search_performed=True,
                    web_search_results=None,
                    # 상세 정보
                    tariff_info=enhanced_info.get("tariff_info", {}),
                    trade_agreement_info=enhanced_info.get("trade_agreement_info", {}),
                    regulation_info=enhanced_info.get("regulation_info", {}),
                    similar_hscodes_detailed=enhanced_info.get(
                        "similar_hscodes_detailed", {}
                    ),
                    market_analysis=enhanced_info.get("market_analysis", {}),
                    verification_status=enhanced_info.get(
                        "verification_status", "ai_generated"
                    ),
                    data_quality_score=enhanced_info.get("data_quality_score", 0.0),
                    needs_update=enhanced_info.get("needs_update", False),
                    last_verified_at=datetime.utcnow(),
                    expert_opinion=enhanced_info.get("expert_opinion"),
                )

                bg_db.add(new_analysis)

            await bg_db.commit()
            logger.info("분석 결과 저장 완료")

        except Exception as e:
            logger.error(f"분석 결과 저장 실패: {e}", exc_info=True)
            await bg_db.rollback()
            raise
