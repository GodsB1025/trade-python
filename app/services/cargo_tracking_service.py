"""
화물통관 조회 인식 및 처리 서비스
"""

import re
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from app.models.chat_models import (
    CargoTrackingData,
    CargoTrackingResponse,
    CargoTrackingError,
    CARGO_NUMBER_PATTERNS,
    CARGO_TRACKING_KEYWORDS,
)

logger = logging.getLogger(__name__)


class CargoTrackingService:
    """화물통관 조회 인식 및 처리 서비스"""

    def __init__(self):
        self.patterns = CARGO_NUMBER_PATTERNS
        self.keywords = CARGO_TRACKING_KEYWORDS

    async def detect_cargo_tracking_intent(self, message: str) -> Tuple[bool, float]:
        """
        사용자 메시지에서 화물통관 조회 의도를 감지

        Args:
            message: 사용자 입력 메시지

        Returns:
            (의도 감지 여부, 신뢰도 점수)
        """
        message_lower = message.lower()

        # 1. 키워드 기반 감지
        keyword_score = self._calculate_keyword_score(message_lower)

        # 2. 화물번호 패턴 감지
        pattern_score = self._calculate_pattern_score(message)

        # 3. 전체 신뢰도 계산
        total_score = (keyword_score * 0.6) + (pattern_score * 0.4)

        # 임계값: 0.3 이상이면 화물통관 조회로 판단
        is_cargo_tracking = total_score >= 0.3

        logger.info(f"화물통관 조회 감지: {is_cargo_tracking}, 점수: {total_score:.3f}")
        logger.debug(
            f"키워드 점수: {keyword_score:.3f}, 패턴 점수: {pattern_score:.3f}"
        )

        return is_cargo_tracking, total_score

    def _calculate_keyword_score(self, message_lower: str) -> float:
        """키워드 기반 점수 계산"""
        matched_keywords = []

        for keyword in self.keywords:
            if keyword.lower() in message_lower:
                matched_keywords.append(keyword)

        # 매칭된 키워드 수에 따른 점수 (최대 1.0)
        if not matched_keywords:
            return 0.0

        # 기본 점수 + 추가 키워드 보너스
        base_score = 0.5
        bonus_score = min(0.5, len(matched_keywords) * 0.1)

        return min(1.0, base_score + bonus_score)

    def _calculate_pattern_score(self, message: str) -> float:
        """화물번호 패턴 기반 점수 계산"""
        matched_patterns = []

        for pattern_name, pattern in self.patterns.items():
            if re.search(pattern, message):
                matched_patterns.append(pattern_name)

        # 패턴 매칭 시 높은 점수
        if matched_patterns:
            return 0.8

        # 숫자 조합이 많으면 화물번호일 가능성
        number_sequences = re.findall(r"\d{4,}", message)
        if number_sequences:
            return 0.4

        return 0.0

    async def extract_cargo_information(
        self, message: str
    ) -> Optional[CargoTrackingData]:
        """
        메시지에서 화물 정보를 추출

        Args:
            message: 사용자 입력 메시지

        Returns:
            추출된 화물 정보 또는 None
        """
        try:
            # 화물번호 패턴 매칭
            cargo_numbers = []
            matched_patterns = []

            for pattern_name, pattern in self.patterns.items():
                matches = re.findall(pattern, message)
                if matches:
                    cargo_numbers.extend(matches)
                    matched_patterns.extend([pattern_name] * len(matches))

            # 패턴에 매칭되지 않는 경우 숫자 시퀀스 추출
            if not cargo_numbers:
                number_sequences = re.findall(r"\d{6,}", message)
                if number_sequences:
                    cargo_numbers = number_sequences
                    matched_patterns = ["general_number"] * len(number_sequences)

            if not cargo_numbers:
                logger.warning("화물번호를 찾을 수 없습니다.")
                return None

            # 가장 긴 번호를 메인 화물번호로 선택
            main_cargo_number = max(cargo_numbers, key=len)
            main_pattern_index = cargo_numbers.index(main_cargo_number)
            main_pattern = matched_patterns[main_pattern_index]

            # 화물 유형 추론
            cargo_type = self._infer_cargo_type(main_cargo_number, main_pattern)

            # 신뢰도 계산
            confidence = self._calculate_extraction_confidence(
                main_cargo_number, main_pattern, len(cargo_numbers)
            )

            return CargoTrackingData(
                cargo_number=main_cargo_number,
                cargo_type=cargo_type,
                extracted_patterns=list(set(matched_patterns)),
                confidence_score=confidence,
            )

        except Exception as e:
            logger.error(f"화물 정보 추출 중 오류 발생: {e}", exc_info=True)
            return None

    def _infer_cargo_type(self, cargo_number: str, pattern_type: str) -> str:
        """화물번호와 패턴을 기반으로 화물 유형 추론"""
        type_mapping = {
            "container": "컨테이너",
            "bl_number": "선하증권",
            "awb_number": "항공화물",
            "tracking": "일반화물",
            "korean_format": "국내화물",
            "general_number": "일반화물",
        }

        return type_mapping.get(pattern_type, "일반화물")

    def _calculate_extraction_confidence(
        self, cargo_number: str, pattern_type: str, total_matches: int
    ) -> float:
        """추출 신뢰도 계산"""
        base_confidence = 0.5

        # 패턴 유형별 신뢰도 가중치
        pattern_weights = {
            "container": 0.9,
            "bl_number": 0.85,
            "awb_number": 0.8,
            "korean_format": 0.75,
            "tracking": 0.6,
            "general_number": 0.4,
        }

        pattern_weight = pattern_weights.get(pattern_type, 0.4)

        # 길이에 따른 추가 신뢰도
        length_bonus = min(0.2, len(cargo_number) / 50)

        # 여러 패턴 매칭 시 신뢰도 향상
        multi_match_bonus = min(0.1, (total_matches - 1) * 0.05)

        final_confidence = min(
            1.0, base_confidence + pattern_weight + length_bonus + multi_match_bonus
        )

        return round(final_confidence, 3)

    async def create_success_response(
        self,
        cargo_data: CargoTrackingData,
        session_uuid: str,
        user_id: Optional[int],
        processing_time_ms: int,
    ) -> CargoTrackingResponse:
        """성공 응답 생성"""
        return CargoTrackingResponse(
            status="success",
            message=f"화물번호 '{cargo_data.cargo_number}'을(를) 인식했습니다. 통관 정보를 조회하고 있습니다.",
            cargo_data=cargo_data,
            spring_endpoint="/api/cargo/tracking",  # Spring 엔드포인트
            session_uuid=session_uuid,
            user_id=user_id,
            processing_time_ms=processing_time_ms,
            error_code=None,  # 성공 응답에서는 None
            error_details=None,  # 성공 응답에서는 None
        )

    async def create_error_response(
        self,
        error_code: str,
        error_message: str,
        original_message: str,
        session_uuid: str,
        user_id: Optional[int],
        suggestions: Optional[List[str]] = None,
    ) -> CargoTrackingError:
        """에러 응답 생성"""
        default_suggestions = [
            "화물번호를 정확히 입력해주세요.",
            "예시: ABCD1234567 (컨테이너 번호)",
            "예시: 1234-5678-9012 (추적번호)",
        ]

        return CargoTrackingError(
            error_code=error_code,
            error_message=error_message,
            original_message=original_message,
            session_uuid=session_uuid,
            user_id=user_id,
            suggestions=suggestions or default_suggestions,
        )
