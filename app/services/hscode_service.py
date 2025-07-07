import logging
import re
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_voyageai import VoyageAIEmbeddings
from langchain_community.tools.tavily_search import TavilySearchResults
from fastapi import BackgroundTasks
from pydantic import SecretStr

from app.models.hscode_models import (
    QueryType,
    ProductInfo,
    HSCodeResult,
    DetailButton,
    SearchResponse,
    WebSearchResult,
    CountryCode,
)
from app.models.db_models import HscodeVector
from app.core.config import settings

logger = logging.getLogger(__name__)


class HSCodeService:
    """HSCode 검색 서비스"""

    # 주요 수출국 목록
    MAJOR_EXPORT_COUNTRIES = {
        CountryCode.CN: "중국",
        CountryCode.US: "미국",
        CountryCode.VN: "베트남",
        CountryCode.HK: "홍콩",
        CountryCode.TW: "대만",
    }

    # 국가별 신뢰할 수 있는 소스
    TRUSTED_SOURCES = {
        "KR": ["customs.go.kr", "kita.net", "tradenavi.or.kr"],
        "CN": ["customs.gov.cn", "ccpit.org", "english.customs.gov.cn"],
        "US": ["usitc.gov", "cbp.gov", "hts.usitc.gov"],
        "VN": ["customs.gov.vn", "vcci.com.vn"],
        "HK": ["customs.gov.hk", "tid.gov.hk"],
        "TW": ["customs.mof.gov.tw", "trade.gov.tw"],
        "JP": ["customs.go.jp", "jetro.go.jp"],
    }

    def __init__(self):
        # 하드코딩된 ChatAnthropic 모델
        from langchain_anthropic import ChatAnthropic

        self.llm = ChatAnthropic(
            model_name=settings.ANTHROPIC_MODEL,
            api_key=SecretStr(settings.ANTHROPIC_API_KEY),
            temperature=1,
            max_tokens_to_sample=15_000,
            timeout=1200.0,
            max_retries=5,
            streaming=True,
            stop=None,
            default_headers={
                "anthropic-beta": "extended-cache-ttl-2025-04-11",
                "anthropic-version": "2023-06-01",
            },
            thinking={"type": "enabled", "budget_tokens": 6_000},
        )
        self.embeddings = VoyageAIEmbeddings(
            api_key=SecretStr(settings.VOYAGE_API_KEY),
            model="voyage-multilingual-2",
            batch_size=32,
        )
        self.web_search_tool = TavilySearchResults(max_results=5)

    async def search_hscode(
        self, user_query: str, db: AsyncSession, background_tasks: BackgroundTasks
    ) -> SearchResponse:
        """메인 검색 함수"""
        try:
            # 1단계: 쿼리 타입 분석
            query_type = self._analyze_query_type(user_query)

            # 2단계: 제품 정보 추출
            product_info = await self._extract_product_info(user_query)

            # 3단계: 정보 충분성 검증
            validation_result = self._validate_product_info(product_info)

            if not validation_result["is_complete"]:
                return SearchResponse(
                    success=False,
                    query_type=query_type,
                    needs_more_info=True,
                    missing_info=validation_result["missing_fields"],
                    results=None,
                    detail_buttons=None,
                    message=self._generate_info_request_message(
                        validation_result["missing_fields"], product_info.name
                    ),
                )

            # 4단계: HSCode 결정
            hscodes = await self._determine_hscode(product_info)

            # 5단계: 상세 페이지 버튼 생성
            detail_buttons = self._generate_detail_buttons(hscodes, query_type)

            # 6단계: 응답 생성
            response = self._generate_response(query_type, hscodes, detail_buttons)

            # 7단계: 결과 캐싱 (비동기)
            if hscodes:
                background_tasks.add_task(
                    self._cache_hscode_result, user_query, product_info, hscodes, db
                )

            return response

        except Exception as e:
            logger.error(f"HSCode 검색 중 오류: {e}", exc_info=True)
            return SearchResponse(
                success=False,
                query_type=QueryType.HSCODE_SEARCH,
                needs_more_info=False,
                missing_info=None,
                results=None,
                detail_buttons=None,
                message="처리 중 오류가 발생했습니다. 다시 시도해주세요.",
            )

    def _analyze_query_type(self, query: str) -> QueryType:
        """쿼리 타입 분석"""
        lower_query = query.lower()

        if "규제" in lower_query or "regulation" in lower_query:
            return QueryType.REGULATION_SEARCH
        elif "통계" in lower_query or "statistics" in lower_query:
            return QueryType.STATISTICS_SEARCH
        elif "추적" in lower_query or "tracking" in lower_query:
            return QueryType.SHIPMENT_TRACKING

        return QueryType.HSCODE_SEARCH

    async def _extract_product_info(self, query: str) -> ProductInfo:
        """LLM을 사용한 제품 정보 추출"""
        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(
                    content="""
                다음 사용자 쿼리에서 제품 정보를 추출하세요.
                JSON 형식으로 반환하되, 다음 필드를 포함해야 합니다:
                - name: 제품명
                - physical_state: 물리적 상태 (냉동/냉장/상온/건조/액체/고체 중 하나)
                - processing_state: 가공 상태 (원료/반가공/완제품 중 하나)
                - packaging_type: 포장 형태
                - materials: 원재료 구성 (리스트)
                - usage: 용도
                - weight: 중량 (숫자)
                - additional_info: 기타 추가 정보
            """
                ),
                HumanMessage(content=f"쿼리: {query}"),
            ]
        )

        structured_llm = self.llm.with_structured_output(ProductInfo)
        result = await structured_llm.ainvoke(prompt.format_messages())

        # 타입 체커를 위한 명시적 타입 확인
        if isinstance(result, ProductInfo):
            return result
        else:
            # 기본값 반환 (모든 필드는 Optional)
            return ProductInfo(
                name=None,
                physical_state=None,
                processing_state=None,
                packaging_type=None,
                materials=None,
                usage=None,
                weight=None,
                dimensions=None,
                additional_info=None,
            )

    def _validate_product_info(self, info: ProductInfo) -> Dict[str, Any]:
        """정보 충분성 검증"""
        missing_fields = []

        # 기본 정보 확인
        if not info.name:
            missing_fields.append("제품명")
        if not info.physical_state:
            missing_fields.append("물리적 상태")
        if not info.processing_state:
            missing_fields.append("가공 상태")

        # 특정 제품에 따른 추가 정보 확인
        if info.name and self._is_food(info.name):
            if not info.materials:
                missing_fields.append("원재료 구성")
            if not info.packaging_type:
                missing_fields.append("포장 형태")

        return {
            "is_complete": len(missing_fields) == 0,
            "missing_fields": missing_fields,
        }

    async def _determine_hscode(self, product_info: ProductInfo) -> List[HSCodeResult]:
        """HSCode 결정 (웹 검색 활용)"""
        results = []

        # 한국 HSK 코드 먼저 결정 (기준)
        korea_result = await self._search_country_hscode(product_info, "KR", "한국")
        if korea_result:
            results.append(korea_result)

        # 주요 수출국별 HSCode 검색
        for country_code, country_name in self.MAJOR_EXPORT_COUNTRIES.items():
            result = await self._search_country_hscode(
                product_info, country_code.value, country_name
            )
            if result:
                results.append(result)

        return results

    async def _search_country_hscode(
        self, product_info: ProductInfo, country_code: str, country_name: str
    ) -> Optional[HSCodeResult]:
        """국가별 HSCode 검색"""
        try:
            # 웹 검색 쿼리 구성
            search_query = f"{product_info.name} {country_code} HSCode tariff"
            if product_info.physical_state:
                search_query += f" {product_info.physical_state}"
            if product_info.processing_state:
                search_query += f" {product_info.processing_state}"

            # 웹 검색 실행
            search_results = await self.web_search_tool.ainvoke({"query": search_query})

            # 검색 결과에서 HSCode 추출
            for result in search_results:
                hscode = self._extract_hscode_from_text(result.get("content", ""))
                if hscode:
                    # 신뢰도 계산
                    confidence = self._calculate_confidence(
                        result.get("url", ""), country_code
                    )

                    return HSCodeResult(
                        country=country_code,
                        country_name=country_name,
                        hscode=hscode,
                        description=result.get("content", "")[:200],
                        confidence=confidence,
                    )

            # 기본값 반환
            return HSCodeResult(
                country=country_code,
                country_name=country_name,
                hscode=self._get_default_hscode(country_code),
                description=f"기본 분류 - {product_info.name}",
                confidence=0.3,
            )

        except Exception as e:
            logger.error(f"{country_code} HSCode 검색 오류: {e}")
            return None

    def _extract_hscode_from_text(self, text: str) -> Optional[str]:
        """텍스트에서 HSCode 추출"""
        # 다양한 HSCode 패턴 매칭
        patterns = [
            r"\b\d{4}\.\d{2}\.\d{2}\.\d{2}\b",  # 10자리 (한국, 중국, 미국)
            r"\b\d{4}\.\d{2}\.\d{2}\b",  # 8자리 (베트남, 홍콩)
            r"\b\d{4}\.\d{2}\b",  # 6자리 (국제 표준)
            r"\b\d{10}\b",  # 10자리 (점 없음)
            r"\b\d{8}\b",  # 8자리 (점 없음)
            r"\b\d{6}\b",  # 6자리 (점 없음)
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0).replace(".", "")

        return None

    def _calculate_confidence(self, url: str, country_code: str) -> float:
        """신뢰도 계산"""
        confidence = 0.5

        # 공식 소스인지 확인
        trusted_sources = self.TRUSTED_SOURCES.get(country_code, [])
        for source in trusted_sources:
            if source in url:
                confidence += 0.3
                break

        return min(confidence, 1.0)

    def _get_default_hscode(self, country_code: str) -> str:
        """국가별 기본 HSCode"""
        defaults = {
            "KR": "9999999999",  # 10자리
            "CN": "9999999999",  # 10자리
            "US": "9999999999",  # 10자리
            "VN": "99999999",  # 8자리
            "HK": "99999999",  # 8자리
            "TW": "99999999999",  # 11자리
            "JP": "999999999",  # 9자리
        }
        return defaults.get(country_code, "999999")

    def _generate_detail_buttons(
        self, hscodes: List[HSCodeResult], query_type: QueryType
    ) -> List[DetailButton]:
        """상세 페이지 버튼 생성"""
        buttons = []

        # 기본 HSCode (한국 기준)
        primary_hscode = ""
        if hscodes:
            korea_result = next((r for r in hscodes if r.country == "KR"), None)
            primary_hscode = korea_result.hscode if korea_result else hscodes[0].hscode

        buttons.append(
            DetailButton(
                type="REGULATION",
                label="규제 정보 상세보기",
                url="/regulation",
                query_params={"hscode": primary_hscode, "country": "ALL"},
            )
        )

        buttons.append(
            DetailButton(
                type="STATISTICS",
                label="무역 통계 상세보기",
                url="/statistics",
                query_params={"hscode": primary_hscode, "period": "latest"},
            )
        )

        buttons.append(
            DetailButton(
                type="SHIPMENT_TRACKING",
                label="화물 추적 정보",
                url="/tracking",
                query_params={"hscode": primary_hscode},
            )
        )

        return buttons

    def _generate_response(
        self,
        query_type: QueryType,
        hscodes: List[HSCodeResult],
        buttons: List[DetailButton],
    ) -> SearchResponse:
        """최종 응답 생성"""
        message = ""

        if query_type == QueryType.HSCODE_SEARCH:
            message = "주요 수출국의 HSCode 정보입니다:\n\n"
            for result in hscodes:
                message += (
                    f"{result.country_name}: {result.hscode} - {result.description}\n"
                )
            message += "\n다른 국가의 HSCode가 필요하시면 국가명을 함께 입력해주세요."

        message += "\n\n상세 정보는 아래 버튼을 클릭해주세요."

        return SearchResponse(
            success=True,
            query_type=query_type,
            needs_more_info=False,
            missing_info=None,
            results=hscodes,
            detail_buttons=buttons,
            message=message,
        )

    def _generate_info_request_message(
        self, missing_fields: List[str], product_name: Optional[str]
    ) -> str:
        """추가 정보 요청 메시지 생성"""
        message = "정확한 HSCode 추천을 위해 추가 정보가 필요합니다.\n\n"

        if product_name:
            message += f'"{product_name}"에 대한 다음 정보를 제공해주세요:\n'
        else:
            message += "다음 정보를 제공해주세요:\n"

        for i, field in enumerate(missing_fields, 1):
            message += f"{i}. {field}\n"

        message += '\n예시: "냉동 양념 족발, 진공포장, 1kg, 돼지고기 100%"'

        return message

    async def _cache_hscode_result(
        self,
        user_query: str,
        product_info: ProductInfo,
        hscode_results: List[HSCodeResult],
        db: AsyncSession,
    ):
        """HSCode 검색 결과 캐싱"""
        try:
            # 한국 코드 우선, 없으면 첫 번째 결과
            primary_result = next(
                (r for r in hscode_results if r.country == "KR"),
                hscode_results[0] if hscode_results else None,
            )

            if not primary_result:
                return

            # 임베딩 생성을 위한 텍스트
            text_to_embed = f"""
            제품명: {product_info.name}
            물리적 상태: {product_info.physical_state}
            가공 상태: {product_info.processing_state}
            원재료: {', '.join(product_info.materials) if product_info.materials else ''}
            설명: {primary_result.description}
            사용자 질문: {user_query}
            """.strip()

            # 벡터 임베딩 생성
            embedding_vector = await self.embeddings.aembed_query(text_to_embed)

            # 데이터베이스에 저장
            hscode_vector = HscodeVector(
                hscode=primary_result.hscode,
                product_name=product_info.name or "",
                description=primary_result.description,
                embedding=embedding_vector,
                metadata_=product_info.model_dump(exclude_none=True),
                confidence_score=primary_result.confidence,
                classification_basis="LLM analysis with web search",
                web_search_context=user_query,
                verified=False,
            )

            db.add(hscode_vector)
            await db.commit()

            logger.info(f"HSCode 결과 캐싱 완료: {primary_result.hscode}")

        except Exception as e:
            logger.error(f"HSCode 캐싱 중 오류: {e}", exc_info=True)
            await db.rollback()

    def _is_food(self, product_name: str) -> bool:
        """식품 여부 확인"""
        food_keywords = [
            "족발",
            "김치",
            "고기",
            "과일",
            "야채",
            "음식",
            "식품",
            "농산물",
            "수산물",
        ]
        return any(keyword in product_name for keyword in food_keywords)
