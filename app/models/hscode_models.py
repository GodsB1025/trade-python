from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class QueryType(str, Enum):
    """쿼리 타입 열거형"""

    HSCODE_SEARCH = "HSCODE_SEARCH"
    REGULATION_SEARCH = "REGULATION_SEARCH"
    STATISTICS_SEARCH = "STATISTICS_SEARCH"
    SHIPMENT_TRACKING = "SHIPMENT_TRACKING"


class ProductInfo(BaseModel):
    """제품 정보 모델"""

    name: Optional[str] = Field(None, description="제품명")
    physical_state: Optional[str] = Field(
        None, description="물리적 상태 (냉동/냉장/상온/건조/액체/고체)"
    )
    processing_state: Optional[str] = Field(
        None, description="가공 상태 (원료/반가공/완제품)"
    )
    packaging_type: Optional[str] = Field(None, description="포장 형태")
    materials: Optional[List[str]] = Field(None, description="원재료 구성")
    usage: Optional[str] = Field(None, description="용도")
    weight: Optional[float] = Field(None, description="중량")
    dimensions: Optional[Dict[str, float]] = Field(
        None, description="규격 (length, width, height)"
    )
    additional_info: Optional[str] = Field(None, description="추가 정보")


class CountryCode(str, Enum):
    """국가 코드 열거형"""

    CN = "CN"  # 중국
    US = "US"  # 미국
    VN = "VN"  # 베트남
    HK = "HK"  # 홍콩
    TW = "TW"  # 대만
    JP = "JP"  # 일본
    EU = "EU"  # 유럽연합
    KR = "KR"  # 한국
    OTHER = "OTHER"  # 기타


class HSCodeResult(BaseModel):
    """HSCode 검색 결과 모델"""

    country: str = Field(..., description="국가 코드")
    country_name: str = Field(..., description="국가명")
    hscode: str = Field(..., description="HSCode")
    description: str = Field(..., description="품목 설명")
    confidence: float = Field(..., description="신뢰도 점수 (0.0 ~ 1.0)")


class DetailButton(BaseModel):
    """상세 페이지 버튼 모델"""

    type: str = Field(
        ..., description="버튼 타입 (REGULATION/STATISTICS/SHIPMENT_TRACKING)"
    )
    label: str = Field(..., description="버튼 레이블")
    url: str = Field(..., description="이동할 URL")
    query_params: Dict[str, str] = Field(
        default_factory=dict, description="쿼리 파라미터"
    )


class SearchResponse(BaseModel):
    """검색 응답 모델"""

    success: bool = Field(..., description="성공 여부")
    query_type: QueryType = Field(..., description="쿼리 타입")
    needs_more_info: bool = Field(..., description="추가 정보 필요 여부")
    missing_info: Optional[List[str]] = Field(None, description="부족한 정보 목록")
    results: Optional[List[HSCodeResult]] = Field(None, description="HSCode 검색 결과")
    detail_buttons: Optional[List[DetailButton]] = Field(
        None, description="상세 페이지 버튼"
    )
    message: str = Field(..., description="사용자에게 전달할 메시지")


class WebSearchResult(BaseModel):
    """웹 검색 결과 모델"""

    code: str = Field(..., description="찾은 HSCode")
    description: str = Field(..., description="설명")
    source: str = Field(..., description="출처 URL")
    is_official: bool = Field(..., description="공식 소스 여부")
    confidence: float = Field(..., description="신뢰도")
