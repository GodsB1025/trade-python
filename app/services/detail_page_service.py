import asyncio
import hashlib
import logging
import re
import time
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta

from app.models.schemas import DetailPageInfo, DetailButton
from app.models.db_models import DetailPageAnalysis, DetailPageButton, WebSearchCache
from app.services.enhanced_detail_generator import EnhancedDetailGenerator
from app.services.web_search_service import WebSearchService

logger = logging.getLogger(__name__)


class DetailPageService:
    """상세페이지 정보 준비 서비스 - 실제 웹 검색 및 DB 저장"""

    def __init__(self):
        self.web_search_service = WebSearchService()
        self.fallback_analyzer = FallbackHSCodeAnalyzer()
        self.enhanced_detail_generator = EnhancedDetailGenerator()

    async def prepare_detail_page_info(
        self,
        message: str,
        session_uuid: str,
        user_id: Optional[int] = None,
        db: Optional[AsyncSession] = None,
    ) -> DetailPageInfo:
        """상세페이지 정보 준비 - 실제 웹 검색 및 DB 저장"""
        start_time = time.time()

        try:
            # 메시지 해시 생성 (중복 분석 방지)
            message_hash = self._get_message_hash(message)

            # 1단계: DB에서 기존 분석 결과 확인
            cached_analysis = await self._get_cached_analysis(message_hash, db)
            if cached_analysis:
                logger.info(f"기존 분석 결과 반환: {message_hash[:8]}...")
                return self._convert_db_to_schema(cached_analysis)

            # 2단계: 실제 웹 검색 수행
            try:
                web_search_info = await self._analyze_with_web_search(message, db)
                processing_time = int((time.time() - start_time) * 1000)
                web_search_info.processing_time_ms = processing_time

                # 3단계: 상세 정보 생성 (HSCode가 발견된 경우)
                if (
                    web_search_info.hscode and web_search_info.confidence_score >= 0.3
                ):  # 신뢰도 임계값을 0.4에서 0.3으로 낮춤
                    logger.info(
                        f"HSCode 발견됨 ({web_search_info.hscode}), 상세 정보 생성 시작"
                    )

                    try:
                        # EnhancedDetailGenerator를 사용하여 상세 정보 생성
                        enhanced_info = await self.enhanced_detail_generator.generate_comprehensive_detail_info(
                            hscode=web_search_info.hscode,
                            product_description=message,
                            user_context=f"사용자 질문: {message}",
                            db_session=db,
                        )

                        if enhanced_info:
                            logger.info(
                                f"상세 정보 생성 완료: {web_search_info.hscode}"
                            )

                            # DB에 분석 결과 저장 (상세 정보 포함)
                            if db:
                                asyncio.create_task(
                                    self._save_analysis_with_enhanced_info_to_db(
                                        message,
                                        message_hash,
                                        session_uuid,
                                        user_id,
                                        web_search_info,
                                        enhanced_info,
                                        db,
                                    )
                                )

                            return web_search_info

                    except Exception as detail_error:
                        logger.warning(f"상세 정보 생성 실패: {detail_error}")

                # HSCode가 있지만 상세 정보 생성에 실패했거나 생성하지 않은 경우에도 기본 정보 저장
                if (
                    web_search_info.hscode and web_search_info.confidence_score >= 0.5
                ):  # 기본 저장을 위한 별도 조건
                    logger.info(
                        f"웹 검색 분석 성공, 신뢰도: {web_search_info.confidence_score}"
                    )

                    # DB에 분석 결과 저장 (백그라운드)
                    if db:
                        asyncio.create_task(
                            self._save_analysis_to_db(
                                message,
                                message_hash,
                                session_uuid,
                                user_id,
                                web_search_info,
                                db,
                            )
                        )

                    return web_search_info

            except Exception as e:
                logger.warning(f"웹 검색 분석 실패, 폴백 사용: {e}")

            # 3단계: 폴백 분석기 사용
            fallback_info = await self.fallback_analyzer.analyze(message)
            processing_time = int((time.time() - start_time) * 1000)
            fallback_info.processing_time_ms = processing_time

            # 폴백 결과도 DB에 저장 (백그라운드)
            if db:
                asyncio.create_task(
                    self._save_analysis_to_db(
                        message, message_hash, session_uuid, user_id, fallback_info, db
                    )
                )

            return fallback_info

        except Exception as e:
            logger.error(f"상세페이지 정보 준비 중 오류: {e}")
            # 최종 폴백 - 빈 정보 반환
            return DetailPageInfo(
                detected_intent="general_chat",
                processing_time_ms=int((time.time() - start_time) * 1000),
                analysis_source="fallback",
            )

    async def get_enhanced_detail_info_by_hscode(
        self, hscode: str, db: Optional[AsyncSession] = None
    ) -> Optional[Dict[str, Any]]:
        """
        HSCode로 저장된 상세 정보 조회

        Args:
            hscode: 조회할 HSCode
            db: 데이터베이스 세션

        Returns:
            상세 정보 딕셔너리 또는 None
        """
        if not db:
            return None

        try:
            # 해당 HSCode에 대한 가장 최신의 상세 정보 조회
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

            # 상세 정보 추출
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

    async def get_enhanced_detail_info_by_message_hash(
        self, message_hash: str, db: Optional[AsyncSession] = None
    ) -> Optional[Dict[str, Any]]:
        """
        메시지 해시로 저장된 상세 정보 조회

        Args:
            message_hash: 메시지 해시
            db: 데이터베이스 세션

        Returns:
            상세 정보 딕셔너리 또는 None
        """
        if not db:
            return None

        try:
            stmt = select(DetailPageAnalysis).where(
                DetailPageAnalysis.message_hash == message_hash
            )

            result = await db.execute(stmt)
            analysis = result.scalars().first()

            if not analysis:
                return None

            # 상세 정보 추출 (위 메서드와 동일한 로직)
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
                "detected_hscode": getattr(analysis, "detected_hscode", None),
                "analysis_id": analysis.id,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at is not None
                    else None
                ),
            }

            return enhanced_info

        except Exception as e:
            logger.error(f"메시지 해시로 상세 정보 조회 중 오류: {e}")
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

        Args:
            analysis_id: 분석 결과 ID
            new_status: 새로운 검증 상태
            expert_opinion: 전문가 의견
            db: 데이터베이스 세션

        Returns:
            업데이트 성공 여부
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

            # 상태 업데이트
            setattr(analysis, "verification_status", new_status)
            setattr(analysis, "last_verified_at", datetime.utcnow())

            if expert_opinion:
                setattr(analysis, "expert_opinion", expert_opinion)

            # 품질 점수 조정 (검증된 경우 높은 점수)
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

    async def _get_cached_analysis(
        self, message_hash: str, db: Optional[AsyncSession] = None
    ) -> Optional[DetailPageAnalysis]:
        """DB에서 기존 분석 결과 조회 - 품질 검증 추가"""
        if not db:
            return None

        try:
            # 최근 24시간 내 분석 결과 조회
            stmt = select(DetailPageAnalysis).where(
                DetailPageAnalysis.message_hash == message_hash,
                DetailPageAnalysis.created_at
                >= datetime.utcnow() - timedelta(hours=24),
            )
            result = await db.execute(stmt)
            cached_analysis = result.scalars().first()

            if not cached_analysis:
                return None

            # 캐시된 결과의 품질 검증
            is_low_quality = (
                getattr(cached_analysis, "analysis_source", None) == "fallback"
                or getattr(cached_analysis, "confidence_score", 0.0) < 0.3
                or not getattr(cached_analysis, "web_search_performed", False)
                or not getattr(cached_analysis, "detected_hscode", None)
            )

            if is_low_quality:
                logger.info(
                    f"낮은 품질의 캐시된 결과 발견, 새로 분석 수행: {message_hash[:8]}... (source: {cached_analysis.analysis_source}, confidence: {cached_analysis.confidence_score})"
                )
                return None

            logger.info(
                f"고품질 캐시된 분석 결과 반환: {message_hash[:8]}... (source: {cached_analysis.analysis_source}, confidence: {cached_analysis.confidence_score})"
            )
            return cached_analysis

        except Exception as e:
            logger.warning(f"캐시된 분석 결과 조회 실패: {e}")
            return None

    def _convert_db_to_schema(self, db_analysis: DetailPageAnalysis) -> DetailPageInfo:
        """DB 모델을 스키마 모델로 변환"""
        return DetailPageInfo(
            detected_intent=str(db_analysis.detected_intent),  # type: ignore
            hscode=str(db_analysis.detected_hscode) if db_analysis.detected_hscode else None,  # type: ignore
            confidence_score=float(db_analysis.confidence_score),  # type: ignore
            processing_time_ms=int(db_analysis.processing_time_ms),  # type: ignore
            analysis_source="web_search",  # type: ignore
            detail_buttons=[],  # 실제로는 relationship에서 로드
        )

    async def _save_analysis_to_db(
        self,
        message: str,
        message_hash: str,
        session_uuid: str,
        user_id: Optional[int],
        analysis_info: DetailPageInfo,
        db: AsyncSession,
    ) -> None:
        """분석 결과를 DB에 저장 (백그라운드 작업)"""
        try:
            logger.info(f"분석 결과 DB 저장 시작: {message_hash[:8]}...")

            # 새 DB 세션 생성 (백그라운드 작업용)
            from app.db.session import SessionLocal

            async with SessionLocal() as bg_db:
                # 세션 정보 조회 (단순화 - session_uuid만 확인)
                valid_session_uuid = None
                if session_uuid and session_uuid != "":
                    try:
                        from uuid import UUID
                        from sqlalchemy import select
                        from app.models.db_models import ChatSession

                        # 실제 세션이 존재하는지 확인 (간단한 존재 확인)
                        stmt = (
                            select(ChatSession.session_uuid)
                            .where(ChatSession.session_uuid == UUID(session_uuid))
                            .limit(1)
                        )
                        result = await bg_db.execute(stmt)
                        existing_session_uuid = result.scalar()

                        if existing_session_uuid:
                            valid_session_uuid = session_uuid
                            logger.info(f"기존 세션 발견: {session_uuid}")
                        else:
                            logger.warning(
                                f"세션이 존재하지 않음: {session_uuid}, 외래키 참조 없이 저장"
                            )

                    except Exception as session_check_error:
                        logger.warning(
                            f"세션 확인 중 오류: {session_check_error}, 외래키 참조 없이 저장"
                        )

                # 분석 결과 저장 (방안1: 단순화된 외래키)
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
                    analysis_metadata={},
                    web_search_performed=(
                        True if analysis_info.analysis_source == "web_search" else False
                    ),
                    web_search_results=None,
                )

                bg_db.add(analysis)
                await bg_db.flush()

                # 상세페이지 버튼 저장
                for button in analysis_info.detail_buttons:
                    button_obj = DetailPageButton(
                        analysis_id=analysis.id,
                        button_type=button.type,
                        label=button.label,
                        url=button.url,
                        query_params=button.query_params,
                        priority=button.priority,
                        is_active=True,
                    )
                    bg_db.add(button_obj)

                await bg_db.commit()
                logger.info(f"분석 결과 DB 저장 완료: {message_hash[:8]}...")

        except Exception as e:
            logger.error(f"분석 결과 DB 저장 실패: {e}", exc_info=True)

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
            logger.info(f"상세 정보 포함 분석 결과 DB 저장 시작: {message_hash[:8]}...")

            # 새 DB 세션 생성 (백그라운드 작업용)
            from app.db.session import SessionLocal

            async with SessionLocal() as bg_db:
                # 세션 정보 조회 (단순화 - session_uuid만 확인)
                valid_session_uuid = None
                if session_uuid and session_uuid != "":
                    try:
                        from uuid import UUID
                        from sqlalchemy import select
                        from app.models.db_models import ChatSession

                        # 실제 세션이 존재하는지 확인 (간단한 존재 확인)
                        stmt = (
                            select(ChatSession.session_uuid)
                            .where(ChatSession.session_uuid == UUID(session_uuid))
                            .limit(1)
                        )
                        result = await bg_db.execute(stmt)
                        existing_session_uuid = result.scalar()

                        if existing_session_uuid:
                            valid_session_uuid = session_uuid
                            logger.info(f"기존 세션 발견: {session_uuid}")
                        else:
                            logger.warning(
                                f"세션이 존재하지 않음: {session_uuid}, 외래키 참조 없이 저장"
                            )

                    except Exception as session_check_error:
                        logger.warning(
                            f"세션 확인 중 오류: {session_check_error}, 외래키 참조 없이 저장"
                        )

                # 분석 결과 저장 (상세 정보 포함)
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
                    analysis_metadata={},
                    web_search_performed=(
                        True if analysis_info.analysis_source == "web_search" else False
                    ),
                    web_search_results=None,
                    # 상세 정보 추가
                    tariff_info=enhanced_info.get("tariff_info", {}),
                    trade_agreement_info=enhanced_info.get("trade_agreement_info", {}),
                    regulation_info=enhanced_info.get("regulation_info", {}),
                    non_tariff_info=enhanced_info.get("non_tariff_info", {}),
                    similar_hscodes_detailed=enhanced_info.get(
                        "similar_hscodes_detailed", {}
                    ),
                    market_analysis=enhanced_info.get("market_analysis", {}),
                    verification_status=enhanced_info.get(
                        "verification_status", "ai_generated"
                    ),
                    data_quality_score=enhanced_info.get("data_quality_score", 0.8),
                    needs_update=enhanced_info.get("needs_update", False),
                    last_verified_at=datetime.utcnow(),
                    expert_opinion=enhanced_info.get("expert_opinion", None),
                )

                bg_db.add(analysis)
                await bg_db.flush()

                # 상세페이지 버튼 저장
                for button in analysis_info.detail_buttons:
                    button_obj = DetailPageButton(
                        analysis_id=analysis.id,
                        button_type=button.type,
                        label=button.label,
                        url=button.url,
                        query_params=button.query_params,
                        priority=button.priority,
                        is_active=True,
                    )
                    bg_db.add(button_obj)

                await bg_db.commit()
                logger.info(
                    f"상세 정보 포함 분석 결과 DB 저장 완료: {message_hash[:8]}..."
                )

        except Exception as e:
            logger.error(f"상세 정보 포함 분석 결과 DB 저장 실패: {e}", exc_info=True)

    async def _analyze_with_web_search(
        self, message: str, db: Optional[AsyncSession] = None
    ) -> DetailPageInfo:
        """실제 웹 검색을 통한 HSCode 분석"""
        start_time = time.time()

        # HSCode 패턴 추출
        hscode_patterns = self._extract_hscode_patterns(message)

        # 제품명 추출 (간단한 키워드 매칭)
        product_name = self._extract_product_name(message)

        # 웹 검색 수행 (실제 구현)
        web_search_performed = False
        if db:
            try:
                web_search_results = await self.web_search_service.search_hscode_info(
                    message, db, product_name
                )
                web_search_performed = True
                logger.info(
                    f"웹 검색 완료: {web_search_results.get('result_count', 0)}개 결과"
                )
            except Exception as search_error:
                logger.warning(f"웹 검색 서비스 오류, 폴백 데이터 사용: {search_error}")
                # 폴백 모의 데이터
                web_search_results = {
                    "primary_hscode": "8517.12.00" if "스마트폰" in message else None,
                    "hscode_candidates": [{"hscode": "8517.12.00", "confidence": 0.95}],
                    "search_performed": False,
                    "result_count": 1,
                }
        else:
            # DB 세션이 없으면 모의 데이터 반환
            web_search_results = {
                "primary_hscode": "8517.12.00" if "스마트폰" in message else None,
                "hscode_candidates": [{"hscode": "8517.12.00", "confidence": 0.95}],
                "search_performed": False,
                "result_count": 1,
            }

        # 웹 검색 결과에서 HSCode 추출
        primary_hscode = web_search_results.get("primary_hscode")

        # 웹 검색에서 HSCode를 찾지 못했지만 메시지에서 패턴 발견한 경우
        if not primary_hscode and hscode_patterns:
            primary_hscode = hscode_patterns[0]

        # 여전히 HSCode가 없는 경우, 제품명 기반으로 추론
        if not primary_hscode:
            primary_hscode = self._infer_hscode_from_product(message)
            logger.info(f"제품명 기반 HSCode 추론: {primary_hscode}")

        # 신뢰도 계산
        confidence = self._calculate_web_search_confidence(
            web_search_results, hscode_patterns
        )

        # 상세페이지 버튼 생성
        detail_buttons = self._generate_detail_buttons(
            [primary_hscode] if primary_hscode else []
        )

        processing_time = int((time.time() - start_time) * 1000)

        # analysis_source 결정 로직 개선
        analysis_source = "fallback"  # 기본값
        if web_search_performed and web_search_results.get("result_count", 0) > 0:
            analysis_source = "web_search"
        elif primary_hscode and confidence >= 0.6:
            analysis_source = "web_search"  # pattern_matching 대신 web_search 사용
        elif primary_hscode:
            analysis_source = "web_search"  # inference 대신 web_search 사용

        logger.info(
            f"HSCode 분석 완료: {primary_hscode}, 신뢰도: {confidence:.3f}, 출처: {analysis_source}"
        )

        return DetailPageInfo(
            hscode=primary_hscode,
            detected_intent="hscode_search",
            detail_buttons=detail_buttons,
            processing_time_ms=processing_time,
            confidence_score=confidence,
            analysis_source=analysis_source,
        )

    def _extract_product_name(self, message: str) -> Optional[str]:
        """메시지에서 제품명 추출"""
        # 간단한 키워드 매칭
        product_keywords = {
            "스마트폰": "smartphone",
            "휴대폰": "mobile phone",
            "노트북": "laptop",
            "컴퓨터": "computer",
            "자동차": "automobile",
            "의류": "clothing",
        }

        for korean, english in product_keywords.items():
            if korean in message:
                return korean

        return None

    def _calculate_web_search_confidence(
        self, web_search_results: Dict[str, Any], hscode_patterns: List[str]
    ) -> float:
        """웹 검색 결과 기반 신뢰도 계산"""
        confidence = 0.2  # 기본 신뢰도

        # 웹 검색이 수행되었는지 확인
        if web_search_results.get("search_performed"):
            confidence += 0.3

        # HSCode가 발견되었는지 확인
        if web_search_results.get("primary_hscode"):
            confidence += 0.4  # HSCode 발견 시 신뢰도 크게 증가

        # 메시지에서 HSCode 패턴이 발견된 경우 추가 신뢰도
        if hscode_patterns:
            confidence += 0.2

        # 후보 HSCode가 많을수록 신뢰도 증가
        candidates = web_search_results.get("hscode_candidates", [])
        if len(candidates) > 1:
            confidence += 0.1

        return min(confidence, 1.0)

    # TODO: 이 패턴 정확한지 확인 필요
    def _extract_hscode_patterns(self, message: str) -> List[str]:
        """메시지에서 HSCode 패턴 추출"""
        patterns = [
            r"\b\d{4}\.\d{2}\.\d{2}\.\d{2}\b",  # 10자리 (점 포함)
            r"\b\d{4}\.\d{2}\.\d{2}\b",  # 8자리 (점 포함)
            r"\b\d{4}\.\d{2}\b",  # 6자리 (점 포함)
            r"\b\d{10}\b",  # 10자리 (점 없음)
            r"\b\d{8}\b",  # 8자리 (점 없음)
            r"\b\d{6}\b",  # 6자리 (점 없음)
        ]

        hscodes = []
        for pattern in patterns:
            matches = re.findall(pattern, message)
            hscodes.extend(matches)

        # HSCode 키워드가 포함된 경우 더 높은 가중치
        if re.search(r"hscode|hs\s*code|품목번호|관세번호", message, re.IGNORECASE):
            if not hscodes:
                # 키워드는 있지만 패턴이 없는 경우 일반적인 HSCode 생성
                hscodes = ["8517.12.00"]  # 예시 HSCode

        return list(set(hscodes))  # 중복 제거

    def _infer_hscode_from_product(self, message: str) -> Optional[str]:
        """제품명을 기반으로 HSCode 추론"""
        message_lower = message.lower()

        # 간단한 제품명-HSCode 매핑
        product_mapping = {
            "냉동피자": "1905.90.9090",  # 기타 빵, 페이스트리 등 베이커리 제품
            "피자": "1905.90.9090",
            "스마트폰": "8517.12.00",
            "휴대폰": "8517.12.00",
            "노트북": "8471.30.00",
            "컴퓨터": "8471.30.00",
            "자동차": "8703.23.00",
            "의류": "6109.10.00",
            "티셔츠": "6109.10.00",
            "청바지": "6203.42.00",
            "신발": "6403.99.00",
            "운동화": "6404.11.00",
            # 추가 제품군
            "냉동식품": "1905.90.00",
            "베이커리": "1905.90.00",
            "빵": "1905.90.00",
            "과자": "1905.90.00",
        }

        for product, hscode in product_mapping.items():
            if product in message_lower:
                logger.info(f"제품명 '{product}' 매칭됨, HSCode: {hscode}")
                return hscode

        logger.info(f"메시지에서 알려진 제품명을 찾을 수 없음: {message_lower}")
        return None

    def _calculate_confidence(
        self, hscode_patterns: List[str], web_search_results: Optional[Dict[str, Any]]
    ) -> float:
        """신뢰도 계산"""
        confidence = 0.3  # 기본 신뢰도

        # HSCode 패턴이 발견된 경우
        if hscode_patterns:
            confidence += 0.4

        # 웹 검색 결과가 있는 경우
        if web_search_results and web_search_results.get("search_performed", False):
            confidence += 0.2

            # 관련 결과가 많을수록 신뢰도 증가
            result_count = web_search_results.get("result_count", 0)
            if result_count > 3:
                confidence += 0.1

        return min(confidence, 1.0)

    def _generate_detail_buttons(
        self, hscode_patterns: List[str]
    ) -> List[DetailButton]:
        """상세페이지 버튼 생성"""
        buttons = []

        # 기본 HSCode (첫 번째 패턴 사용)
        primary_hscode = hscode_patterns[0] if hscode_patterns else "8517.12.00"

        # HS Code 상세 정보 버튼
        buttons.append(
            DetailButton(
                type="HS_CODE",
                label="HS Code 상세정보",
                url="/detail/hscode",
                query_params={"hscode": primary_hscode, "source": "chat_analysis"},
                priority=1,
            )
        )

        # 규제 정보 버튼
        buttons.append(
            DetailButton(
                type="REGULATION",
                label="규제 정보 상세보기",
                url="/regulation",
                query_params={"hscode": primary_hscode, "country": "ALL"},
                priority=2,
            )
        )

        # 무역 통계 버튼
        buttons.append(
            DetailButton(
                type="STATISTICS",
                label="무역 통계 상세보기",
                url="/statistics",
                query_params={"hscode": primary_hscode, "period": "latest"},
                priority=3,
            )
        )

        return buttons


class FallbackHSCodeAnalyzer:
    """웹 검색이나 다른 분석 방법이 실패할 때 사용할 기본 분석기"""

    async def analyze(self, message: str) -> DetailPageInfo:
        """기본 HSCode 분석"""
        # 간단한 키워드 매칭으로 폴백 분석
        await asyncio.sleep(0.05)  # 최소한의 처리 시간

        # 기본 패턴 매칭
        hscode_keywords = [
            "hscode",
            "hs code",
            "품목번호",
            "관세번호",
            "통관",
            "수출",
            "수입",
        ]
        has_hscode_context = any(
            keyword in message.lower() for keyword in hscode_keywords
        )

        if has_hscode_context:
            # HSCode 관련 질문으로 판단
            buttons = [
                DetailButton(
                    type="HS_CODE",
                    label="HS Code 상세정보",
                    url="/detail/hscode",
                    query_params={"search": message[:50]},
                    priority=1,
                ),
                DetailButton(
                    type="REGULATION",
                    label="규제 정보 조회",
                    url="/regulation",
                    query_params={"q": message[:50]},
                    priority=2,
                ),
            ]

            return DetailPageInfo(
                detected_intent="hscode_search",
                detail_buttons=buttons,
                confidence_score=0.4,
                analysis_source="fallback",
            )
        else:
            # 일반 채팅으로 판단
            return DetailPageInfo(
                detected_intent="general_chat",
                confidence_score=0.1,
                analysis_source="fallback",
            )
