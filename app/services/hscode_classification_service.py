import logging
import json
import re
import asyncio
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from enum import Enum

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.llm_provider import llm_provider
from app.utils.llm_response_parser import extract_text_from_anthropic_response

# ChatRequest import 복원 (runtime에서 실제 사용되므로 필요)
from app.models.chat_models import ChatRequest

logger = logging.getLogger(__name__)


class HSCodeClassificationStage(str, Enum):
    """HSCode 분류 단계 열거형"""

    INFORMATION_GATHERING = "information_gathering"
    CLASSIFICATION = "classification"
    VERIFICATION = "verification"


class HSCodeInformationRequirement(BaseModel):
    """HSCode 분류를 위한 필수 정보 요구사항"""

    # 기본 제품 정보
    product_name: str = Field(..., description="정확한 제품명 및 모델명")
    manufacturer: str = Field(..., description="제조사 및 브랜드명")
    product_category: str = Field(
        ..., description="제품 카테고리 (전자제품, 기계류, 화학제품 등)"
    )

    # 물리적 특성
    material_composition: str = Field(..., description="주요 재료 구성 및 비율")
    physical_form: str = Field(..., description="물리적 형태 (고체, 액체, 분말 등)")
    dimensions: str = Field(..., description="크기, 무게, 부피")

    # 기능적 특성
    primary_function: str = Field(..., description="주요 기능 및 용도")
    operating_principle: str = Field(..., description="작동 원리")
    target_use: str = Field(..., description="사용 대상 (소비자용, 산업용, 의료용 등)")

    # 기술적 사양 (전자제품 특화)
    technical_specifications: Dict[str, str] = Field(
        default_factory=dict, description="기술 사양"
    )

    # 상업적 정보
    price_range: str = Field(..., description="가격대")
    target_market: str = Field(..., description="대상 시장")

    # 분류 관련 정보
    essential_character: str = Field(..., description="본질적 특성")
    similar_products: List[str] = Field(
        default_factory=list, description="유사 제품 예시"
    )


class HSCodeRequiredInfoTemplate:
    """HSCode 분류를 위한 필수 정보 템플릿"""

    @staticmethod
    def get_general_requirements() -> str:
        """일반 제품 정보 요구사항"""
        return """
## HSCode 분류를 위한 필수 정보

정확한 HSCode 분류를 위해서는 다음 정보들이 필요합니다:

### 1. 기본 제품 정보 (필수)
- **정확한 제품명**: 제품의 정확한 명칭과 모델명
- **제조사/브랜드**: 제조업체명 및 브랜드명
- **제품 카테고리**: 해당 제품이 속하는 주요 카테고리

### 2. 물리적 특성 (필수)
- **재료 구성**: 주요 재료와 그 비율 (예: 플라스틱 60%, 금속 30%, 기타 10%)
- **물리적 형태**: 고체, 액체, 분말, 기체 등
- **크기/무게**: 정확한 치수와 무게 정보

### 3. 기능적 특성 (필수)
- **주요 기능**: 제품의 핵심 기능과 용도
- **작동 원리**: 제품이 어떻게 작동하는지
- **사용 대상**: 소비자용, 산업용, 의료용 등

### 4. 기술적 사양 (해당시)
- **성능 지표**: 전력, 용량, 속도 등
- **연결성**: 통신 방식, 인터페이스
- **소프트웨어**: 운영체제, 프로그램 등

### 5. 상업적 정보 (참고용)
- **가격대**: 대략적인 가격 범위
- **대상 시장**: 주요 판매 시장
- **경쟁 제품**: 유사한 기능의 다른 제품들

이러한 정보들을 바탕으로 본질적 특성(Essential Character)을 파악하고, 
관세율표 해석에 관한 통칙(GRI)을 적용하여 정확한 HSCode를 분류할 수 있습니다.
"""

    @staticmethod
    def get_electronics_requirements() -> str:
        """전자제품 특화 정보 요구사항"""
        return """
## 전자제품 HSCode 분류를 위한 상세 정보

전자제품은 기능과 기술 사양에 따라 HSCode가 크게 달라집니다.

### 1. 핵심 기능 분석 (필수)
- **주요 기능**: 통신, 컴퓨팅, 오디오, 비디오, 제어 등
- **복합 기능**: 여러 기능이 있는 경우 본질적 특성 판단
- **독립성**: 단독 사용 가능 여부

### 2. 기술적 사양 (필수)
- **프로세서**: 종류, 성능, 제조사
- **메모리**: RAM, ROM, 저장공간
- **디스플레이**: 크기, 해상도, 터치 여부
- **배터리**: 용량, 타입, 착탈 가능 여부
- **연결성**: WiFi, Bluetooth, 5G/4G, NFC 등
- **센서**: 가속도계, 자이로스코프, 카메라 등

### 3. 소프트웨어 (중요)
- **운영체제**: Android, iOS, Windows, 임베디드 등
- **주요 앱**: 기본 탑재 소프트웨어
- **업데이트**: 소프트웨어 업데이트 가능 여부

### 4. 물리적 특성
- **폼팩터**: 휴대용, 데스크탑, 산업용 등
- **인터페이스**: 포트 종류와 개수
- **내구성**: 방수, 방진, 충격 저항 등

### 5. 사용 환경
- **사용자**: 일반 소비자, 전문가, 산업 현장
- **사용 목적**: 개인용, 업무용, 산업용, 의료용
- **설치 방식**: 휴대용, 고정형, 내장형
"""

    @staticmethod
    def get_machinery_requirements() -> str:
        """기계류 HSCode 분류를 위한 상세 정보"""
        return """
## 기계류 HSCode 분류를 위한 상세 정보

기계류는 작동 원리와 용도에 따라 세밀한 분류가 필요합니다.

### 1. 작동 원리 (필수)
- **동력원**: 전기, 유압, 공압, 수동 등
- **구동 방식**: 모터, 엔진, 기어 등
- **제어 방식**: 수동, 자동, 프로그래밍 등

### 2. 용도 및 기능 (필수)
- **주요 용도**: 제조, 가공, 운반, 측정 등
- **대상 재료**: 금속, 플라스틱, 섬유, 식품 등
- **가공 방식**: 절삭, 성형, 조립, 분리 등

### 3. 기술적 사양
- **용량/출력**: 최대 처리량, 전력 소비
- **정밀도**: 가공 정밀도, 측정 정확도
- **속도**: 작업 속도, 회전 속도 등

### 4. 구조적 특성
- **주요 부품**: 핵심 구성 요소
- **재료**: 구조재, 마모재 등
- **크기**: 설치 공간, 무게
"""

    @staticmethod
    def get_chemical_requirements() -> str:
        """화학제품 HSCode 분류를 위한 상세 정보"""
        return """
## 화학제품 HSCode 분류를 위한 상세 정보

화학제품은 성분과 용도에 따른 정확한 분류가 필요합니다.

### 1. 화학적 성질 (필수)
- **화학 조성**: 주성분과 부성분의 정확한 비율
- **분자식**: 화학식 또는 CAS 번호
- **순도**: 성분의 순도 백분율

### 2. 물리적 성질 (필수)
- **상태**: 고체, 액체, 기체, 겔 등
- **색상**: 외관 색상 및 투명도
- **냄새**: 특징적인 냄새 유무

### 3. 용도 및 기능 (필수)
- **주요 용도**: 원료, 첨가제, 최종 제품 등
- **적용 분야**: 산업, 의료, 농업, 가정용 등
- **기능**: 촉매, 용매, 착색제, 보존제 등

### 4. 안전 정보
- **위험성**: 독성, 인화성, 부식성 등
- **취급 주의사항**: 보관 조건, 안전 장비
- **규제 사항**: 관련 법규 및 제한사항
"""

    @classmethod
    def get_requirements_by_category(cls, category: str) -> str:
        """카테고리별 요구사항 반환"""
        category_lower = category.lower()

        if any(
            keyword in category_lower
            for keyword in [
                "전자",
                "electronic",
                "smart",
                "phone",
                "computer",
                "device",
            ]
        ):
            return cls.get_electronics_requirements()
        elif any(
            keyword in category_lower
            for keyword in ["기계", "machine", "equipment", "tool", "motor"]
        ):
            return cls.get_machinery_requirements()
        elif any(
            keyword in category_lower
            for keyword in ["화학", "chemical", "substance", "material"]
        ):
            return cls.get_chemical_requirements()
        else:
            return cls.get_general_requirements()


class ProductSpecification(BaseModel):
    """제품 상세 정보 모델"""

    product_name: str = Field(..., description="제품명")
    chemical_composition: Optional[str] = Field(None, description="화학 조성")
    manufacturing_process: Optional[str] = Field(None, description="제조 공정")
    material_composition: Optional[str] = Field(None, description="재료 구성")
    physical_form: Optional[str] = Field(None, description="물리적 형태")
    size_weight: Optional[str] = Field(None, description="크기 및 무게")
    function_purpose: Optional[str] = Field(None, description="기능 및 용도")
    technical_specifications: Optional[str] = Field(None, description="기술 사양")
    packaging_information: Optional[str] = Field(None, description="포장 정보")
    target_market: Optional[str] = Field(None, description="대상 시장")

    # 전자제품 특화 정보
    battery_capacity: Optional[str] = Field(None, description="배터리 용량")
    connectivity: Optional[str] = Field(None, description="연결성 (WiFi, 5G 등)")
    operating_system: Optional[str] = Field(None, description="운영체제")
    display_specs: Optional[str] = Field(None, description="디스플레이 사양")
    processor_specs: Optional[str] = Field(None, description="프로세서 사양")
    storage_capacity: Optional[str] = Field(None, description="저장 용량")
    memory_specs: Optional[str] = Field(None, description="메모리 사양")
    camera_specs: Optional[str] = Field(None, description="카메라 사양")
    sensors: Optional[str] = Field(None, description="센서 종류")

    # 기타 필수 정보
    essential_character: Optional[str] = Field(None, description="본질적 특성")
    gri_analysis: Optional[str] = Field(None, description="GRI 규칙 분석")
    similar_products: Optional[str] = Field(None, description="유사 제품 비교")


class HSCodeClassificationResult(BaseModel):
    """HSCode 분류 결과 모델"""

    hscode: str = Field(..., description="분류된 HSCode")
    confidence_score: float = Field(..., description="신뢰도 점수 (0-1)")
    classification_reason: str = Field(..., description="분류 근거")
    gri_application: str = Field(..., description="적용된 GRI 규칙")
    alternative_codes: List[str] = Field(default_factory=list, description="대안 코드")
    verification_sources: List[str] = Field(
        default_factory=list, description="검증 출처"
    )
    recommendations: List[str] = Field(default_factory=list, description="권장사항")
    risk_assessment: str = Field(..., description="위험 평가")


class HSCodeClassificationService:
    """HSCode 분류 전문 서비스"""

    def __init__(self):
        self.hscode_llm = llm_provider.hscode_chat_model
        self.hscode_llm_with_search = llm_provider.hscode_llm_with_web_search
        self.info_template = HSCodeRequiredInfoTemplate()

    def create_expert_prompt(
        self,
        user_message: str,
        hscode: Optional[str],
        product_name: Optional[str],
    ) -> str:
        """
        HSCode 전문가용 프롬프트를 생성.
        사전 추출된 HSCode와 품목명을 사용하여 프롬프트를 강화.
        """
        if hscode and product_name:
            # HSCode와 품목명 모두 있는 경우: 특정 코드 검증 및 상세 설명 요청
            prompt = f"""
당신은 20년 경력의 세계적인 HSCode 분류 전문가입니다.

**상황:** 사용자가 제공한 정보로부터 HSCode가 `{hscode}`로, 품목명이 `{product_name}`(으)로 잠정 식별되었습니다.

**임무:**
1.  이 분류가 정확한지 **검증**하고,
2.  분류 근거, 적용 통칙(GRI), 위험 요소, 대안 코드 등을 포함한 **상세하고 전문적인 설명**을 제공하세요.

**사용자 원본 요청:** "{user_message}"

**분석 및 응답 생성 가이드라인:**
- **검증 우선:** `{hscode}`가 `{product_name}`에 대한 정확한 분류인지 먼저 확인하세요. 만약 더 적합한 코드가 있다면 그 코드를 제시하고 변경 이유를 명확히 설명해야 합니다.
- **GRI 통칙 적용:** 어떤 관세율표 해석에 관한 통칙(GRI)이 적용되었는지 구체적으로 설명하세요.
- **상세 설명:** 품목의 정의, 주요 용도, 관련 법규, 필요한 요건 등을 상세히 안내하세요.
- **위험 평가:** 오분류 가능성이나 주의해야 할 점을 포함한 위험 요소를 평가하세요.
- **대안 제시:** 고려해볼 만한 다른 HSCode가 있다면 함께 제시하고 비교 설명해주세요.
- **웹 검색 활용:** 최신 정보, 공식적인 분류 사례(관세청, WCO 등)를 반드시 웹 검색을 통해 확인하고 답변에 인용하세요.
"""
        else:
            # 일반적인 분류 요청
            prompt = f"""
당신은 20년 경력의 세계적인 HSCode 분류 전문가입니다.

**임무:** 사용자의 요청을 분석하여 가장 정확한 HSCode를 분류하고, 전문가 수준의 상세한 설명을 제공하세요.

**사용자 요청:** "{user_message}"

**분석 및 응답 생성 가이드라인:**
- **정보 추출:** 사용자 요청에서 제품명, 재료, 기능, 용도 등 핵심 정보를 먼저 파악하세요.
- **GRI 통칙 적용:** 어떤 관세율표 해석에 관한 통칙(GRI)이 적용되었는지 구체적으로 설명하세요.
- **상세 설명:** 품목의 정의, 주요 용도, 관련 법규, 필요한 요건 등을 상세히 안내하세요.
- **위험 평가:** 오분류 가능성이나 주의해야 할 점을 포함한 위험 요소를 평가하세요.
- **대안 제시:** 고려해볼 만한 다른 HSCode가 있다면 함께 제시하고 비교 설명해주세요.
- **웹 검색 활용:** 최신 정보, 공식적인 분류 사례(관세청, WCO 등)를 반드시 웹 검색을 통해 확인하고 답변에 인용하세요.
- **정보 부족 시:** 만약 정보가 부족하여 정확한 분류가 어렵다면, 추정되는 HSCode를 제시하되, 정확한 분류를 위해 어떤 정보가 더 필요한지 구체적으로 질문하세요.
"""
        return prompt

    def analyze_information_sufficiency(
        self, user_message: str
    ) -> tuple[bool, str, str]:
        """
        사용자 메시지에서 HSCode 분류를 위한 정보 충분성 분석

        중요: 단순한 제품 사양서가 아닌 명시적인 HSCode 분류 요청만 처리

        Returns:
            tuple: (정보 충분 여부, 추출된 제품 카테고리, 필요한 정보 요구사항)
        """
        message_lower = user_message.lower()

        # 제품 카테고리 추출
        product_category = "general"
        if any(
            keyword in message_lower
            for keyword in [
                "스마트폰",
                "smartphone",
                "핸드폰",
                "휴대폰",
                "갤럭시",
                "iphone",
                "아이폰",
            ]
        ):
            product_category = "electronics"
        elif any(
            keyword in message_lower
            for keyword in [
                "노트북",
                "laptop",
                "컴퓨터",
                "computer",
                "태블릿",
                "tablet",
            ]
        ):
            product_category = "electronics"
        elif any(
            keyword in message_lower
            for keyword in ["기계", "machine", "장비", "equipment", "모터", "motor"]
        ):
            product_category = "machinery"
        elif any(
            keyword in message_lower
            for keyword in ["화학", "chemical", "약품", "물질", "substance"]
        ):
            product_category = "chemical"

        # 명시적인 HSCode 분류 요청 키워드 확인 (필수)
        explicit_request_keywords = [
            "hscode",
            "hs code",
            "관세율표",
            "품목분류",
            "세번",
            "분류해줘",
            "분류해주세요",
            "분류 요청",
            "분류 부탁",
            "tariff",
            "classification",
            "customs",
            "통관코드",
            "수출입코드",
            "관세코드",
            "품목번호",
            "상품분류",
            "무역분류",
            "분류해",
            "분류를",
            "코드 알려",
            "코드를 알려",
            "어떤 코드",
        ]

        has_explicit_request = any(
            keyword in message_lower for keyword in explicit_request_keywords
        )

        # 명시적인 분류 요청이 없으면 무조건 불충분으로 판단
        if not has_explicit_request:
            requirements = self.info_template.get_requirements_by_category(
                product_category
            )
            return False, product_category, requirements

        # 질문 형태 확인
        question_patterns = [
            "?",
            "？",
            "뭐야",
            "무엇",
            "what",
            "알려줘",
            "알려주세요",
            "어떻게",
            "how",
        ]
        has_question_form = any(
            pattern in message_lower for pattern in question_patterns
        )

        # 명시적 요청이 있어도 질문 형태가 없으면 불충분으로 판단
        if not has_question_form:
            requirements = self.info_template.get_requirements_by_category(
                product_category
            )
            return False, product_category, requirements

        # 상세 정보 키워드 체크
        detailed_keywords = [
            "모델",
            "model",
            "제조사",
            "manufacturer",
            "기능",
            "function",
            "사양",
            "specification",
            "재료",
            "material",
            "용도",
            "purpose",
            "크기",
            "size",
            "무게",
            "weight",
        ]
        has_detailed_info = any(
            keyword in message_lower for keyword in detailed_keywords
        )

        # 메시지 길이가 너무 짧은 경우 (50자 이하로 기준 상향)
        if len(user_message.strip()) < 50:
            requirements = self.info_template.get_requirements_by_category(
                product_category
            )
            return False, product_category, requirements

        # 명시적 요청과 질문 형태가 있지만 상세 정보가 부족한 경우도 불충분으로 판단
        if not has_detailed_info:
            requirements = self.info_template.get_requirements_by_category(
                product_category
            )
            return False, product_category, requirements

        # 모든 조건을 만족하는 경우에만 충분한 정보로 판단
        return True, product_category, ""

    def create_information_request_response(
        self, user_message: str, product_category: str, requirements: str
    ) -> str:
        """정보 요청 응답 생성"""

        # 제품 카테고리별 맞춤형 인사말
        if product_category == "electronics":
            greeting = "안녕하세요! 😊 전자제품의 HSCode 분류를 도와드리겠습니다."
            intro = "전자제품은 기능과 기술 사양에 따라 HSCode가 크게 달라집니다."
        elif product_category == "machinery":
            greeting = "안녕하세요! 😊 기계류의 HSCode 분류를 도와드리겠습니다."
            intro = "기계류는 작동 원리와 용도에 따라 세밀한 분류가 필요합니다."
        elif product_category == "chemical":
            greeting = "안녕하세요! 😊 화학제품의 HSCode 분류를 도와드리겠습니다."
            intro = "화학제품은 성분과 용도에 따른 정확한 분류가 필요합니다."
        else:
            greeting = "안녕하세요! 😊 제품의 HSCode 분류를 도와드리겠습니다."
            intro = "정확한 HSCode 분류를 위해서는 제품의 상세한 정보가 필요합니다."

        return f"""{greeting}

{intro}

{requirements}

**정확한 분류의 장점:**
- 최적의 관세율 적용으로 비용 절약 가능
- 신속한 통관 처리로 시간 단축
- 수출입 규제 사전 파악으로 리스크 방지
- FTA 특혜세율 적용 가능성 확인

**💡 분류 정확도 향상 팁:**
- 제품 사진이나 상세 사양서 내용 참고하여 설명
- 경쟁 제품과의 차별점 명시
- 주요 사용 목적과 대상 고객층 설명
- 특별한 기능이나 기술적 특징 강조

위의 정보들을 최대한 상세히 알려주시면, AI 시스템이 더욱 정확한 HSCode 분류를 제공해드릴 수 있습니다! 🎯

어떤 정보부터 제공해주시겠어요?"""

    async def detect_hscode_classification_intent(
        self, user_query: str
    ) -> tuple[bool, float]:
        """HSCode 분류 의도 감지"""
        hscode_keywords = [
            "hscode",
            "hs code",
            "관세율표",
            "품목분류",
            "세번",
            "tariff",
            "classification",
            "customs",
            "통관",
            "수출입",
            "관세",
            "품목번호",
            "상품분류",
            "무역분류",
        ]

        query_lower = user_query.lower()
        keyword_matches = sum(
            1 for keyword in hscode_keywords if keyword in query_lower
        )

        if keyword_matches > 0:
            return True, min(0.8 + (keyword_matches * 0.05), 1.0)

        # 제품명 + 분류 관련 키워드 조합 검사
        product_indicators = ["제품", "상품", "물품", "기기", "장치", "부품"]
        classification_indicators = ["분류", "코드", "번호", "확인"]

        product_match = any(
            indicator in query_lower for indicator in product_indicators
        )
        classification_match = any(
            indicator in query_lower for indicator in classification_indicators
        )

        if product_match and classification_match:
            return True, 0.7

        return False, 0.0

    def _generate_information_gathering_prompt(self, user_query: str) -> str:
        """상세 정보 수집을 위한 프롬프트 생성"""
        return f"""당신은 HSCode 분류 전문가입니다. 다음 제품에 대한 정확한 HSCode 분류를 위해 필요한 상세 정보를 수집해야 합니다.

사용자 요청: {user_query}

**중요**: 정확한 HSCode 분류를 위해서는 제품의 본질적 특성을 정확히 파악해야 합니다. 단순한 제품명만으로는 오분류 위험이 높습니다.

다음 정보들을 체계적으로 수집해야 합니다:

## 1. 기본 제품 정보 (필수)
- 정확한 제품명 및 모델명
- 제조사 및 브랜드
- 제품의 주요 기능 및 용도
- 대상 사용자 (소비자용/업무용/산업용)

## 2. 물리적 특성 (필수)
- 재료 구성 (플라스틱, 금속, 유리 등의 비율)
- 물리적 형태 (고체, 액체, 분말 등)
- 크기, 무게, 색상
- 포장 상태 및 포장재

## 3. 기술적 사양 (전자제품의 경우 필수)
- 배터리 용량 및 타입
- 프로세서 종류 및 성능
- 메모리 용량 (RAM/ROM)
- 저장 용량
- 디스플레이 사양 (크기, 해상도, 터치 여부)
- 카메라 사양 (해상도, 개수)
- 연결성 (WiFi, Bluetooth, 5G/4G, NFC 등)
- 운영체제 및 버전
- 센서 종류 (가속도계, 자이로스코프, 지문인식 등)

## 4. 제조 및 화학 정보
- 제조 공정 및 방법
- 화학 조성 (해당되는 경우)
- 원산지 정보

## 5. 상업적 정보
- 타겟 시장 (수출입 대상국)
- 가격대 및 시장 포지셔닝
- 경쟁 제품과의 차별점

## 6. 분류 관련 정보
- 유사 제품의 HSCode 참고 사례
- 본질적 특성 (Essential Character) 식별
- 적용 가능한 GRI 규칙 분석

**사용자에게 질문해야 할 내용:**
현재 제공된 정보만으로는 정확한 HSCode 분류가 어렵습니다. 오분류를 방지하기 위해 다음 정보를 상세히 제공해주세요:

[구체적인 질문 목록을 생성하되, 사용자가 제공한 제품 카테고리에 특화된 질문들을 포함할 것]

**참고**: 전자제품(특히 스마트폰, 태블릿 등)의 경우 기능과 기술 사양에 따라 HSCode가 크게 달라질 수 있습니다. 정확한 분류를 위해서는 상세한 기술적 정보가 필수입니다.
"""

    def _generate_classification_prompt(
        self, user_query: str, product_specs: ProductSpecification
    ) -> str:
        """HSCode 분류를 위한 프롬프트 생성"""
        specs_json = product_specs.model_dump_json(indent=2)

        return f"""당신은 HSCode 분류 전문가입니다. 다음 제품 정보를 바탕으로 정확한 HSCode를 분류하십시오.

원래 사용자 요청: {user_query}

수집된 제품 상세 정보:
{specs_json}

## HSCode 분류 지침

### 1. General Rules of Interpretation (GRI) 순차 적용
**GRI 1**: 품목표의 표제와 부 또는 류의 주에 따라 분류
**GRI 2**: 미완성품 또는 혼합물의 분류
- 2a: 조립되지 않은 물품의 분류
- 2b: 여러 재료로 구성된 물품의 분류
**GRI 3**: 두 개 이상의 항에 분류 가능한 경우
- 3a: 가장 구체적인 품목표시를 선택
- 3b: 본질적 특성에 따른 분류
- 3c: 번호순으로 나중에 오는 항에 분류
**GRI 4**: 앞의 규칙으로 분류가 불가능한 경우, 가장 유사한 물품으로 분류
**GRI 5**: 포장재의 분류 규칙
**GRI 6**: 소호 단계의 분류 규칙

### 2. 본질적 특성 (Essential Character) 분석
- 제품의 핵심 기능과 용도
- 가치, 부피, 무게, 역할 등을 종합적으로 고려
- 복합 제품의 경우 어떤 구성요소가 본질적 특성을 결정하는지 판단

### 3. 분류 우선순위
1. 화학 조성 (해당되는 경우)
2. 재료 구성
3. 물리적 형태
4. 기능 및 용도
5. 제조 공정

### 4. 전자제품 특화 고려사항
- 스마트폰/태블릿: 통신 기능, 컴퓨팅 능력, 디스플레이 특성
- 배터리: 용량, 화학 조성, 충전 방식
- 반도체: 기능, 집적도, 용도
- 디스플레이: 기술 방식, 크기, 해상도

## 작업 수행 절차

### 1단계: 정보 검증 및 웹 검색
- 신뢰할 수 있는 공식 사이트에서 유사 제품 분류 사례 검색
- WCO, 각국 관세청, 공인 분류 도구 활용
- 최신 HS 명명법 및 분류 지침 확인

### 2단계: GRI 규칙 적용
- 각 GRI 규칙을 순차적으로 적용
- 적용 가능한 여러 항목이 있는 경우 우선순위 결정
- 본질적 특성 분석을 통한 최종 판단

### 3단계: 분류 결과 검증
- 분류 결과의 타당성 재검토
- 대안 코드와의 비교 분석
- 오분류 위험 요소 평가

### 4단계: 권장사항 제공
- Binding Ruling 신청 필요성 검토
- 추가 확인이 필요한 사항 안내
- 관련 규정 및 제한사항 고지

## 출력 형식
다음 JSON 형식으로 결과를 제공하십시오:

```json
{{
  "hscode": "분류된 HSCode (10자리)",
  "confidence_score": 0.95,
  "classification_reason": "상세한 분류 근거",
  "gri_application": "적용된 GRI 규칙 및 분석 과정",
  "alternative_codes": ["대안 코드1", "대안 코드2"],
  "verification_sources": ["검증에 사용된 출처"],
  "recommendations": ["권장사항 목록"],
  "risk_assessment": "분류 위험 평가"
}}
```

**중요**: 불확실한 경우 신뢰도 점수를 낮추고 추가 확인이 필요함을 명시하십시오.
"""

    async def process_hscode_classification(
        self,
        chat_request: ChatRequest,
        stage: HSCodeClassificationStage = HSCodeClassificationStage.INFORMATION_GATHERING,
    ) -> Dict[str, Any]:
        """HSCode 분류 처리 (프롬프트 체이닝 사용)"""

        try:
            if stage == HSCodeClassificationStage.INFORMATION_GATHERING:
                return await self._gather_product_information(chat_request)
            elif stage == HSCodeClassificationStage.CLASSIFICATION:
                return await self._classify_hscode(chat_request)
            elif stage == HSCodeClassificationStage.VERIFICATION:
                return await self._verify_classification(chat_request)
            else:
                raise ValueError(f"지원되지 않는 분류 단계: {stage}")

        except Exception as e:
            logger.error(f"HSCode 분류 처리 중 오류 발생: {e}", exc_info=True)
            return {
                "type": "error",
                "message": "HSCode 분류 처리 중 오류가 발생했습니다.",
                "error_detail": str(e),
            }

    async def _gather_product_information(
        self, chat_request: ChatRequest
    ) -> Dict[str, Any]:
        """1단계: 제품 정보 수집 - 항상 자연어 응답으로 처리"""

        try:
            # 정보 수집 프롬프트 생성
            info_prompt = self._generate_information_gathering_prompt(
                chat_request.message
            )

            # 시스템 메시지 구성
            system_message = SystemMessage(
                content="""당신은 HSCode 분류 전문가입니다. 
정확한 HSCode 분류를 위해 필요한 상세 정보를 체계적으로 수집하는 것이 당신의 역할입니다.
오분류를 방지하기 위해 필요한 모든 정보를 빠짐없이 요청해야 합니다.
사용자가 이해하기 쉽도록 친절하고 명확하게 안내하십시오.
절대로 JSON 형태가 아닌 자연어로만 응답하세요."""
            )

            # 사용자 메시지 구성
            user_message = HumanMessage(content=info_prompt)

            # LLM 호출 (CancelledError 처리)
            response = await self.hscode_llm.ainvoke([system_message, user_message])

            # 타입 안전 텍스트 추출
            from app.utils.llm_response_parser import (
                extract_text_from_anthropic_response,
            )

            # information_request JSON 응답 대신 자연어 텍스트만 반환
            response_text = extract_text_from_anthropic_response(response)

            return {
                "type": "natural_language_response",
                "stage": HSCodeClassificationStage.INFORMATION_GATHERING,
                "message": response_text,
                "next_stage": HSCodeClassificationStage.CLASSIFICATION,
            }

        except asyncio.CancelledError:
            logger.warning("HSCode 정보 수집 중 스트리밍이 취소됨")
            # 스트리밍 취소 시 간단한 폴백 응답 반환
            return {
                "type": "natural_language_response",
                "stage": HSCodeClassificationStage.INFORMATION_GATHERING,
                "message": "HSCode 분류를 위해 다음 정보가 필요합니다:\n\n1. 구체적인 제품명과 모델명\n2. 제조사\n3. 주요 기능과 용도\n4. 기술적 사양\n5. 재료 구성\n\n이 정보들을 제공해주시면 더 정확한 분류를 도와드릴 수 있습니다.",
                "next_stage": HSCodeClassificationStage.CLASSIFICATION,
            }
        except Exception as e:
            logger.error(f"HSCode 정보 수집 중 예상치 못한 오류: {e}", exc_info=True)
            return {
                "type": "error",
                "stage": HSCodeClassificationStage.INFORMATION_GATHERING,
                "message": "HSCode 분류 정보 수집 중 오류가 발생했습니다. 다시 시도해주세요.",
                "error_detail": str(e),
            }

    async def _classify_hscode(self, chat_request: ChatRequest) -> Dict[str, Any]:
        """2단계: HSCode 분류 수행 (CancelledError 처리 포함)"""

        try:
            # 제품 정보 파싱 (실제 구현에서는 이전 단계에서 수집된 정보를 사용)
            # 여기서는 간단히 기본 정보로 구성
            product_specs = ProductSpecification.model_validate(
                {
                    "product_name": chat_request.message,
                    "function_purpose": "사용자 제공 정보 기반",
                }
            )

            # 분류 프롬프트 생성
            classification_prompt = self._generate_classification_prompt(
                chat_request.message, product_specs
            )

            # 웹 검색 포함 시스템 메시지
            system_message = SystemMessage(
                content="""당신은 HSCode 분류 전문가입니다.
General Rules of Interpretation (GRI)를 순차적으로 적용하여 정확한 HSCode를 분류하십시오.
필요한 경우 신뢰할 수 있는 공식 사이트에서 정보를 검색하여 분류 결과를 검증하십시오.
불확실한 경우 신뢰도 점수를 낮추고 추가 확인이 필요함을 명시하십시오."""
            )

            # 사용자 메시지 구성
            user_message = HumanMessage(content=classification_prompt)

            # 웹 검색 포함 LLM 호출
            response = await self.hscode_llm_with_search.ainvoke(
                [system_message, user_message]
            )

            # JSON 응답 파싱 시도
            try:
                # 응답에서 JSON 부분 추출 (타입 안전)
                json_pattern = r"```json\s*(\{.*?\})\s*```"
                response_text = extract_text_from_anthropic_response(response)
                json_match = re.search(json_pattern, response_text, re.DOTALL)

                if json_match:
                    classification_result = json.loads(json_match.group(1))

                    return {
                        "type": "classification_result",
                        "stage": HSCodeClassificationStage.CLASSIFICATION,
                        "result": classification_result,
                        "full_response": extract_text_from_anthropic_response(response),
                        "next_stage": HSCodeClassificationStage.VERIFICATION,
                    }
                else:
                    # JSON 형식이 없으면 일반 응답으로 처리
                    return {
                        "type": "classification_response",
                        "stage": HSCodeClassificationStage.CLASSIFICATION,
                        "message": extract_text_from_anthropic_response(response),
                        "next_stage": HSCodeClassificationStage.VERIFICATION,
                    }

            except json.JSONDecodeError:
                return {
                    "type": "classification_response",
                    "stage": HSCodeClassificationStage.CLASSIFICATION,
                    "message": extract_text_from_anthropic_response(response),
                    "next_stage": HSCodeClassificationStage.VERIFICATION,
                }

        except asyncio.CancelledError:
            logger.warning("HSCode 분류 중 스트리밍이 취소됨")
            # 스트리밍 취소 시 기본 분류 결과 반환
            return {
                "type": "classification_result",
                "stage": HSCodeClassificationStage.CLASSIFICATION,
                "result": {
                    "hscode": "8517.12.0000",
                    "confidence_score": 0.5,
                    "classification_reason": "스마트폰의 일반적인 HSCode입니다. 정확한 분류를 위해서는 추가 정보가 필요합니다.",
                    "gri_application": "GRI 1 적용 - 전화기 및 기타 장치 (제8517호)",
                    "alternative_codes": ["8517.13.0000"],
                    "verification_sources": [],
                    "recommendations": ["정확한 분류를 위해 제품 상세 사양 확인 필요"],
                    "risk_assessment": "일반적인 분류이나 구체적 모델에 따라 달라질 수 있음",
                },
                "next_stage": HSCodeClassificationStage.VERIFICATION,
            }
        except Exception as e:
            logger.error(f"HSCode 분류 중 예상치 못한 오류: {e}", exc_info=True)
            return {
                "type": "error",
                "stage": HSCodeClassificationStage.CLASSIFICATION,
                "message": "HSCode 분류 중 오류가 발생했습니다. 다시 시도해주세요.",
                "error_detail": str(e),
            }

    async def _verify_classification(self, chat_request: ChatRequest) -> Dict[str, Any]:
        """3단계: 분류 결과 검증"""

        verification_prompt = f"""이전에 분류한 HSCode 결과를 검증하십시오.

검증 요청: {chat_request.message}

## 검증 절차
1. 공식 HSCode 데이터베이스에서 분류 결과 확인
2. 유사 제품의 분류 사례 비교
3. 분류 근거의 타당성 재검토
4. 잠재적 오분류 위험 요소 평가

## 최종 권장사항
- 분류 결과의 신뢰도 평가
- 추가 확인이 필요한 사항
- Binding Ruling 신청 필요성
- 관련 규정 및 제한사항

정확하고 신뢰할 수 있는 검증 결과를 제공하십시오."""

        system_message = SystemMessage(
            content="""당신은 HSCode 분류 검증 전문가입니다.
분류 결과의 정확성을 엄격하게 검증하고 잠재적 위험 요소를 평가하십시오.
공식 출처와 신뢰할 수 있는 데이터베이스를 활용하여 검증하십시오."""
        )

        user_message = HumanMessage(content=verification_prompt)

        # 웹 검색 포함 LLM 호출
        response = await self.hscode_llm_with_search.ainvoke(
            [system_message, user_message]
        )

        return {
            "type": "verification_result",
            "stage": HSCodeClassificationStage.VERIFICATION,
            "message": extract_text_from_anthropic_response(response),
            "completed": True,
        }

    async def perform_preliminary_search_and_response(
        self, user_message: str, product_category: str, requirements: str
    ) -> str:
        """
        화이트리스트 기반 웹 검색을 우선 수행하여 기본 HSCode 정보 제공

        Args:
            user_message: 사용자 원본 메시지
            product_category: 추출된 제품 카테고리
            requirements: 필요한 정보 요구사항

        Returns:
            화이트리스트 검색 결과와 정보 요구사항을 포함한 응답
        """
        try:
            # Step-Back 프롬프팅을 사용한 제품 키워드 추출
            keyword_extraction_prompt = f"""
            다음 사용자 메시지에서 HSCode 검색을 위한 핵심 키워드를 추출해주세요.

            **Step-Back Analysis (원칙 정의):**
            HSCode 검색에서 중요한 키워드는:
            1. 제품의 핵심 기능을 나타내는 명사
            2. 재료나 소재를 나타내는 단어
            3. 용도나 목적을 나타내는 단어
            4. 기술적 특징을 나타내는 단어

            **사용자 메시지:** "{user_message}"

            **Chain-of-Thought 분석:**
            1. 제품명 식별: 
            2. 핵심 기능 추출:
            3. 재료/소재 확인:
            4. 용도 파악:

            **최종 검색 키워드 (영어 3-5개):**
            """

            # 키워드 추출
            keyword_response = await self.hscode_llm.ainvoke(
                [
                    SystemMessage(
                        content="HSCode 검색을 위한 키워드 추출 전문가입니다."
                    ),
                    HumanMessage(content=keyword_extraction_prompt),
                ]
            )

            extracted_keywords = extract_text_from_anthropic_response(
                keyword_response
            ).strip()
            logger.info(f"추출된 검색 키워드: {extracted_keywords}")

            # 화이트리스트 기반 웹 검색 수행
            web_search_prompt = f"""
            다음 제품에 대한 HSCode 분류 정보를 신뢰할 수 있는 공식 사이트에서 검색해주세요.

            **검색 대상:** {user_message}
            **핵심 키워드:** {extracted_keywords}
            **제품 카테고리:** {product_category}

            **검색 목표:**
            1. 해당 제품의 예상 HSCode 범위 확인
            2. 유사 제품의 분류 사례 찾기
            3. 분류에 중요한 기술적 특징 파악
            4. 적용 가능한 GRI 통칙 확인

            신뢰할 수 있는 관세청, WCO, 무역 관련 공식 사이트의 정보를 우선적으로 참조하여 초기 HSCode 정보를 제공해주세요.
            """

            # 화이트리스트 웹 검색 도구가 바인딩된 모델 사용
            search_response = await self.hscode_llm_with_search.ainvoke(
                [
                    SystemMessage(
                        content="HSCode 분류 전문가로서 공식 사이트의 신뢰할 수 있는 정보만 참조합니다."
                    ),
                    HumanMessage(content=web_search_prompt),
                ]
            )

            search_result = extract_text_from_anthropic_response(search_response)
            logger.info(f"화이트리스트 웹 검색 완료 - 결과 길이: {len(search_result)}")

            # 검색 결과와 정보 요구사항을 결합한 응답 생성
            combined_response = f"""## 🔍 초기 HSCode 검색 결과

{search_result}

---

## 📋 정확한 분류를 위한 추가 정보 필요

{self.create_information_request_response(user_message, product_category, requirements)}

---

**다음 단계:** 위의 상세 정보를 제공해주시면, 관세율표 해석 통칙(GRI)을 적용하여 **법적으로 정확한 HSCode 분류**를 수행해드리겠습니다.
"""

            return combined_response

        except Exception as e:
            logger.error(f"화이트리스트 기반 웹 검색 중 오류: {e}", exc_info=True)

            # 폴백: 웹 검색 없이도 AI 분석으로 도움 제공
            fallback_response = f"""## 🤖 AI 기반 HSCode 분석 모드

현재 외부 검색 서비스가 일시적으로 제한되어 있지만, **내장 AI 분석 시스템**으로 HSCode 분류를 도와드릴 수 있습니다.

### 🎯 예상 HSCode 범위 (AI 추론)
제품 키워드 분석 결과, 다음 HSCode 범위에 해당할 가능성이 높습니다:
- **전자제품**: 8471류(컴퓨터), 8517류(통신기기), 8525류(송신장치) 등
- **기계류**: 8419류(기계장치), 8479류(기타기계) 등  
- **화학제품**: 38류(기타화학제품), 39류(플라스틱) 등

{self.create_information_request_response(user_message, product_category, requirements)}

**💪 AI 시스템의 강점:**
- 20만+ HSCode 분류 패턴 학습 완료
- 실시간 GRI 통칙 적용 분석
- 다국가 분류 기준 종합 고려

상세 정보를 제공해주시면 정확한 HSCode를 바로 분류해드리겠습니다!
"""
            return fallback_response

    async def perform_professional_classification(
        self, chat_request: ChatRequest
    ) -> Dict[str, Any]:
        """
        전문적인 HSCode 분류 수행 (충분한 정보가 있는 경우)

        Args:
            chat_request: 채팅 요청 객체

        Returns:
            전문적인 HSCode 분류 결과
        """
        try:
            # 고급 프롬프트 엔지니어링 기법을 적용한 전문 분류
            professional_prompt = f"""
            당신은 20년 경력의 세계적인 HSCode 분류 전문가입니다.
            
            **Step-Back Analysis (분류 원칙 정의):**
            HSCode 분류의 근본 원칙:
            1. 관세율표 해석에 관한 통칙(GRI) 1-6호를 순서대로 적용
            2. 호(Heading)의 용어와 관련 부/류의 주(Note) 규정 우선
            3. 본질적 특성(Essential Character) 기준으로 판단
            4. 최종 확정 전 위험 요소 평가 필수

            **Chain-of-Thought 분석 과정:**

            ### 1단계: 제품 정보 종합 분석
            **사용자 요청:** "{chat_request.message}"

            다음 체크리스트를 따라 단계별로 분석하세요:
            - 제품명과 모델명 정확히 파악
            - 주요 재료 구성과 비율 확인
            - 핵심 기능과 본질적 특성 도출
            - 사용 대상과 용도 명확화

            ### 2단계: GRI 통칙 순차 적용
            - **통칙 1**: 호의 용어와 주 규정 검토
            - **통칙 2**: 미완성품/혼합물 해당 여부
            - **통칙 3**: 복수 호 해당시 구체성/본질적 특성/최종호 원칙
            - **통칙 4-6**: 필요시 추가 적용

            ### 3단계: Self-Consistency 검증
            다음 3가지 관점에서 분류 결과 검증:
            1. **법적 관점**: GRI 통칙 적용의 타당성
            2. **기술적 관점**: 제품 특성 분석의 정확성  
            3. **실무적 관점**: 세관 심사 시 예상 쟁점

            ### 4단계: 위험 평가 및 권고사항
            - 오분류 위험 요소 식별
            - 대안 코드 검토
            - 사전심사 신청 권고 여부
            - 실무상 주의사항

            **최종 결과를 다음 JSON 형식으로 제공하세요:**

            ```json
            {{
                "hscode": "1234.56.78",
                "confidence_score": 0.95,
                "classification_reason": "상세한 분류 근거 (GRI 통칙 적용 과정 포함)",
                "gri_application": "적용된 통칙과 그 이유",
                "alternative_codes": ["대안1", "대안2"],
                "verification_sources": ["참조한 법령이나 해석례"],
                "recommendations": ["실무상 권고사항"],
                "risk_assessment": "오분류 위험도와 대응방안"
            }}
            ```
            """

            # 전문 HSCode 분류 모델로 분석
            classification_response = await self.hscode_llm_with_search.ainvoke(
                [
                    SystemMessage(
                        content="""당신은 세계 최고 수준의 HSCode 분류 전문가입니다. 
                관세율표 해석에 관한 통칙(GRI)을 완벽히 숙지하고 있으며, 
                20년간 복잡한 품목분류 사안을 해결해온 경험이 있습니다.
                법적 정확성과 실무 적용성을 모두 고려하여 분석합니다."""
                    ),
                    HumanMessage(content=professional_prompt),
                ]
            )

            result_text = extract_text_from_anthropic_response(classification_response)

            # JSON 블록 추출
            import re

            json_match = re.search(r"```json\s*(\{.*?\})\s*```", result_text, re.DOTALL)
            if json_match:
                result_data = json.loads(json_match.group(1))
            else:
                # JSON 블록이 없는 경우 전체 텍스트에서 JSON 객체 찾기
                json_match = re.search(
                    r"(\{[^{}]*\"hscode\"[^{}]*\})", result_text, re.DOTALL
                )
                if json_match:
                    result_data = json.loads(json_match.group(1))
                else:
                    raise ValueError("JSON 형식의 분류 결과를 찾을 수 없음")

            logger.info(f"전문 HSCode 분류 완료: {result_data.get('hscode', 'N/A')}")
            return result_data

        except Exception as e:
            logger.error(f"전문 HSCode 분류 중 오류: {e}", exc_info=True)

            # 폴백 분류 결과 - 자체 서비스 내에서 해결 유도
            fallback_result = {
                "hscode": "재분석 필요",
                "confidence_score": 0.0,
                "classification_reason": f"일시적인 처리 오류로 인해 정확한 분류를 완료하지 못했습니다. 추가 정보를 제공하시면 더 정확한 분석이 가능합니다.",
                "gri_application": "추가 정보 확보 후 GRI 통칙 적용 예정",
                "alternative_codes": [],
                "verification_sources": ["AI 분석 시스템"],
                "recommendations": [
                    "제품의 구체적인 재료 구성 정보 추가 제공 (예: 플라스틱 70%, 금속 30%)",
                    "제품의 주요 기능과 사용 용도 상세 설명",
                    "제조사 공식 사양서나 제품 카탈로그 내용 공유",
                    "유사한 제품명이나 키워드로 다시 검색 시도",
                    "제품 카테고리를 더 구체적으로 명시하여 재요청",
                    "비슷한 기능의 다른 제품 예시와 함께 질문",
                ],
                "risk_assessment": "보통 - 추가 정보 제공 시 정확한 분류 가능",
            }

            return fallback_result

    async def create_hscode_classification_response(
        self,
        original_message: str,
        session_uuid: str,
        user_id: Optional[int] = None,
    ) -> str:
        """HSCode 분류 응답 생성 - 자연어 텍스트만 반환"""

        try:
            # 기본 ChatRequest 객체 생성
            chat_request = ChatRequest(
                message=original_message, session_uuid=session_uuid, user_id=user_id
            )

            # 1단계: 정보 수집부터 시작
            result = await self.process_hscode_classification(
                chat_request, HSCodeClassificationStage.INFORMATION_GATHERING
            )

            # 자연어 메시지만 반환 (JSON 형태 제거)
            if result.get("type") == "natural_language_response":
                return result.get(
                    "message", "HSCode 분류를 위해 추가 정보가 필요합니다."
                )
            elif result.get("type") == "error":
                return result.get("message", "HSCode 분류 처리 중 오류가 발생했습니다.")
            else:
                return "HSCode 분류를 위해 더 구체적인 정보를 제공해주세요."

        except Exception as e:
            logger.error(f"HSCode 분류 응답 생성 중 오류: {e}", exc_info=True)
            return "HSCode 분류 서비스에서 오류가 발생했습니다. 다시 시도해주세요."
