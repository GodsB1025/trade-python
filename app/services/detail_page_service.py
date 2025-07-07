import asyncio
import hashlib
import logging
import re
import time
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.models.schemas import DetailPageInfo, DetailButton
from app.models.db_models import DetailPageAnalysis, DetailPageButton
from app.services.enhanced_detail_generator import EnhancedDetailGenerator

logger = logging.getLogger(__name__)


class DetailPageService:
    """상세페이지 정보 준비 서비스"""

    def __init__(self):
        self.enhanced_detail_generator = EnhancedDetailGenerator()

    async def prepare_detail_page_info(
        self,
        message: str,
        session_uuid: str,
        user_id: Optional[int] = None,
        db: Optional[AsyncSession] = None,
        override_hscode: Optional[str] = None,
        product_name: Optional[str] = None,
    ) -> DetailPageInfo:
        """HSCode를 기반으로 상세페이지 정보를 준비"""
        start_time = time.time()

        if not override_hscode:
            logger.info("상세 정보 준비 건너뛰기: HSCode가 제공되지 않았습니다.")
            return DetailPageInfo(
                detected_intent="general_chat",
                analysis_source="skipped",
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

        logger.info(
            f"HSCode '{override_hscode}'를 사용하여 상세 정보 준비를 시작합니다."
        )

        try:
            enhanced_info = (
                await self.enhanced_detail_generator.generate_comprehensive_detail_info(
                    hscode=override_hscode,
                    product_description=product_name or message,
                    user_context=f"사용자 질문: {message}",
                    db_session=db,
                )
            )

            detail_buttons = self._generate_detail_buttons([override_hscode])
            processing_time = int((time.time() - start_time) * 1000)

            detail_page_info = DetailPageInfo(
                hscode=override_hscode,
                detected_intent="hscode_search",
                detail_buttons=detail_buttons,
                processing_time_ms=processing_time,
                confidence_score=1.0,  # 외부에서 확정된 코드이므로 신뢰도 1.0
                analysis_source="pre_analyzed",
            )

            if db and enhanced_info:
                message_hash = self._get_message_hash(f"{override_hscode}:{message}")
                asyncio.create_task(
                    self._save_analysis_with_enhanced_info_to_db(
                        message=message,
                        message_hash=message_hash,
                        session_uuid=session_uuid,
                        user_id=user_id,
                        analysis_info=detail_page_info,
                        enhanced_info=enhanced_info,
                        db=db,
                    )
                )
            return detail_page_info

        except Exception as e:
            logger.error(f"상세페이지 정보 준비 중 오류: {e}", exc_info=True)
            return DetailPageInfo(
                hscode=override_hscode,
                detected_intent="hscode_search",
                processing_time_ms=int((time.time() - start_time) * 1000),
                analysis_source="error",
                error_message=f"상세 정보 생성 중 오류 발생: {e}",
            )

    async def get_enhanced_detail_info_by_hscode(
        self, hscode: str, db: Optional[AsyncSession] = None
    ) -> Optional[Dict[str, Any]]:
        """
        HSCode로 저장된 상세 정보 조회
        """
        if not db:
            return None

        try:
            stmt = (
                select(DetailPageAnalysis)
                .where(
                    DetailPageAnalysis.detected_hscode == hscode,
                    DetailPageAnalysis.verification_status.in_(
                        ["ai_generated", "verified"]
                    ),
                )
                .order_by(DetailPageAnalysis.created_at.desc())
                .limit(1)
            )

            result = await db.execute(stmt)
            analysis = result.scalars().first()

            if not analysis:
                return None

            enhanced_info = {
                "tariff_info": getattr(analysis, "tariff_info", {}),
                "trade_agreement_info": getattr(analysis, "trade_agreement_info", {}),
                "regulation_info": getattr(analysis, "regulation_info", {}),
                "non_tariff_info": getattr(analysis, "non_tariff_info", {}),
                "similar_hscodes_detailed": getattr(
                    analysis, "similar_hscodes_detailed", {}
                ),
                "market_analysis": getattr(analysis, "market_analysis", {}),
                "verification_status": getattr(
                    analysis, "verification_status", "unknown"
                ),
                "data_quality_score": getattr(analysis, "data_quality_score", 0.0),
                "last_verified_at": getattr(analysis, "last_verified_at", None),
                "expert_opinion": getattr(analysis, "expert_opinion", None),
                "analysis_id": analysis.id,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at is not None
                    else None
                ),
            }
            return enhanced_info
        except Exception as e:
            logger.error(f"상세 정보 조회 중 오류: {e}")
            return None

    async def update_verification_status(
        self,
        analysis_id: int,
        new_status: str,
        expert_opinion: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> bool:
        """
        분석 결과의 검증 상태 업데이트
        """
        if not db:
            return False

        try:
            stmt = select(DetailPageAnalysis).where(
                DetailPageAnalysis.id == analysis_id
            )

            result = await db.execute(stmt)
            analysis = result.scalars().first()

            if not analysis:
                return False

            setattr(analysis, "verification_status", new_status)
            setattr(analysis, "last_verified_at", datetime.utcnow())

            if expert_opinion:
                setattr(analysis, "expert_opinion", expert_opinion)

            if new_status == "verified":
                setattr(analysis, "data_quality_score", 1.0)
                setattr(analysis, "needs_update", False)
            elif new_status == "rejected":
                setattr(analysis, "data_quality_score", 0.0)
                setattr(analysis, "needs_update", True)

            await db.commit()
            logger.info(
                f"분석 결과 {analysis_id}의 검증 상태를 {new_status}로 업데이트"
            )
            return True

        except Exception as e:
            logger.error(f"검증 상태 업데이트 중 오류: {e}")
            await db.rollback()
            return False

    def _get_message_hash(self, message: str) -> str:
        """메시지의 SHA256 해시 생성"""
        return hashlib.sha256(message.encode("utf-8")).hexdigest()

    async def _save_analysis_with_enhanced_info_to_db(
        self,
        message: str,
        message_hash: str,
        session_uuid: str,
        user_id: Optional[int],
        analysis_info: DetailPageInfo,
        enhanced_info: Dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """분석 결과와 상세 정보를 DB에 저장 (백그라운드 작업)"""
        try:
            logger.info(f"상세 분석 결과 DB 저장 시작: {message_hash[:8]}...")
            from app.db.session import SessionLocal

            async with SessionLocal() as bg_db:
                valid_session_uuid = None
                if session_uuid:
                    try:
                        from uuid import UUID
                        from app.models.db_models import ChatSession

                        stmt = (
                            select(ChatSession.session_uuid)
                            .where(ChatSession.session_uuid == UUID(session_uuid))
                            .limit(1)
                        )
                        result = await bg_db.execute(stmt)
                        if result.scalar_one_or_none():
                            valid_session_uuid = session_uuid
                    except Exception as e:
                        logger.warning(f"세션 UUID 확인 중 오류: {e}")

                analysis = DetailPageAnalysis(
                    user_id=user_id,
                    session_uuid=valid_session_uuid,
                    message_hash=message_hash,
                    original_message=message,
                    detected_intent=analysis_info.detected_intent,
                    detected_hscode=analysis_info.hscode,
                    confidence_score=analysis_info.confidence_score,
                    processing_time_ms=analysis_info.processing_time_ms,
                    analysis_source=analysis_info.analysis_source,
                    web_search_performed=False,
                    verification_status="ai_generated",
                    data_quality_score=enhanced_info.get("data_quality_score", 0.7),
                    **enhanced_info,
                )
                bg_db.add(analysis)
                await bg_db.flush()

                for button in analysis_info.detail_buttons:
                    button_obj = DetailPageButton(
                        analysis_id=analysis.id,
                        button_type=button.type,
                        label=button.label,
                        url=button.url,
                        action=button.action,
                        query_params=button.query_params,
                        priority=button.priority,
                        is_active=True,
                    )
                    bg_db.add(button_obj)

                await bg_db.commit()
                logger.info(f"상세 분석 결과 DB 저장 완료: {message_hash[:8]}...")

        except Exception as e:
            logger.error(f"상세 분석 결과 DB 저장 실패: {e}", exc_info=True)

    def _generate_detail_buttons(
        self, hscode_patterns: List[str]
    ) -> List[DetailButton]:
        """HSCode 패턴 목록으로부터 상세페이지 버튼 목록을 생성합니다."""
        buttons = []
        if not hscode_patterns:
            return buttons

        main_hscode = hscode_patterns[0]

        button_templates = [
            {
                "type": "link",
                "label": "관세청 법령정보",
                "url": "https://unipass.customs.go.kr/clip/index.do",
                "query_params": {"hscode": main_hscode},
                "priority": 1,
            },
            {
                "type": "link",
                "label": "TradeNAVI",
                "url": "https://www.tradenavi.or.kr/web/main.do",
                "query_params": {"hscode": main_hscode},
                "priority": 2,
            },
            {
                "type": "action",
                "label": "AI 유사사례 분석",
                "action": "ANALYZE_SIMILAR_CASES",
                "query_params": {"hscode": main_hscode},
                "priority": 3,
            },
            {
                "type": "action",
                "label": "AI 리포트 생성",
                "action": "GENERATE_AI_REPORT",
                "query_params": {"hscode": main_hscode},
                "priority": 4,
            },
        ]

        for template in button_templates:
            buttons.append(
                DetailButton(
                    type=template["type"],
                    label=template["label"],
                    url=template.get("url"),
                    action=template.get("action"),
                    query_params=template.get("query_params"),
                    priority=template["priority"],
                )
            )
        return buttons
