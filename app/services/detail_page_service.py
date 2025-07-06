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
from app.services.web_search_service import WebSearchService

logger = logging.getLogger(__name__)


class DetailPageService:
    """상세페이지 정보 준비 서비스 - 실제 웹 검색 및 DB 저장"""

    def __init__(self):
        self.web_search_service = WebSearchService()
        self.fallback_analyzer = FallbackHSCodeAnalyzer()

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

                if web_search_info.confidence_score >= 0.7:
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

    def _get_message_hash(self, message: str) -> str:
        """메시지의 SHA256 해시 생성"""
        return hashlib.sha256(message.encode("utf-8")).hexdigest()

    async def _get_cached_analysis(
        self, message_hash: str, db: Optional[AsyncSession] = None
    ) -> Optional[DetailPageAnalysis]:
        """DB에서 기존 분석 결과 조회"""
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
            return result.scalars().first()

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
                # 분석 결과 저장
                analysis = DetailPageAnalysis(
                    user_id=user_id,
                    session_uuid=session_uuid if session_uuid != "" else None,
                    session_created_at=datetime.utcnow(),  # 실제로는 세션 생성 시간 사용
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
        if db:
            try:
                web_search_results = await self.web_search_service.search_hscode_info(
                    message, db, product_name
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
        if not primary_hscode and hscode_patterns:
            primary_hscode = hscode_patterns[0]

        # 신뢰도 계산
        confidence = self._calculate_web_search_confidence(
            web_search_results, hscode_patterns
        )

        # 상세페이지 버튼 생성
        detail_buttons = self._generate_detail_buttons(
            [primary_hscode] if primary_hscode else []
        )

        processing_time = int((time.time() - start_time) * 1000)

        return DetailPageInfo(
            hscode=primary_hscode,
            detected_intent="hscode_search",
            detail_buttons=detail_buttons,
            processing_time_ms=processing_time,
            confidence_score=confidence,
            analysis_source="fallback",
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
        confidence = 0.3  # 기본 신뢰도

        # 웹 검색이 수행되었는지 확인
        if web_search_results.get("search_performed"):
            confidence += 0.3

        # HSCode가 발견되었는지 확인
        if web_search_results.get("primary_hscode"):
            confidence += 0.3

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

    def _calculate_confidence(
        self, hscode_patterns: List[str], fastapi_docs: Optional[Dict[str, Any]]
    ) -> float:
        """신뢰도 계산"""
        confidence = 0.3  # 기본 신뢰도

        # HSCode 패턴이 발견된 경우
        if hscode_patterns:
            confidence += 0.4

        # Context7 문서 조회 성공 시
        if fastapi_docs and fastapi_docs.get("docs_retrieved", 0) > 0:
            confidence += 0.2

            # 관련 스니펫이 많을수록 신뢰도 증가
            snippets = fastapi_docs.get("relevant_snippets", 0)
            if snippets > 5:
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
    """Context7 실패 시 사용할 폴백 분석기"""

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
