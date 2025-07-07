"""
Enhanced Detail Page Information Generator
HSCode 파악 시 상세페이지에 필요한 모든 정보를 생성하는 고급 서비스
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import SecretStr

from app.core.config import settings

# from app.services.web_search_service import WebSearchService # 이 줄을 삭제합니다.

logger = logging.getLogger(__name__)


class EnhancedDetailGenerator:
    """상세페이지 정보 생성 서비스 - AI 기반 종합 분석"""

    def __init__(self):
        # 하드코딩된 ChatAnthropic 모델
        from langchain_anthropic import ChatAnthropic
        from pydantic import SecretStr

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
        # self.web_search_service = WebSearchService() # 이 줄을 삭제합니다.

        # 주요 수출입 대상국
        self.major_countries = {
            "KR": "한국",
            "CN": "중국",
            "US": "미국",
            "JP": "일본",
            "VN": "베트남",
            "DE": "독일",
            "TH": "태국",
            "IN": "인도",
        }

    async def generate_comprehensive_detail_info(
        self, hscode: str, product_description: str, user_context: str, db_session=None
    ) -> Dict[str, Any]:
        """
        HSCode에 대한 종합적인 상세 정보 생성

        Args:
            hscode: HSCode (예: "8517.12.00")
            product_description: 제품 설명
            user_context: 사용자 질문 맥락
            db_session: 데이터베이스 세션 (웹 검색 캐싱용)

        Returns:
            상세 정보가 담긴 딕셔너리
        """
        start_time = time.time()
        logger.info(f"Starting comprehensive detail generation for HSCode: {hscode}")

        try:
            # 병렬로 여러 정보 생성
            tasks = [
                self._generate_tariff_info(
                    hscode, product_description
                ),  # db_session 제거
                self._generate_trade_agreement_info(
                    hscode, product_description
                ),  # db_session 제거
                self._generate_regulation_info(
                    hscode, product_description
                ),  # db_session 제거
                self._generate_non_tariff_info(
                    hscode, product_description
                ),  # db_session 제거
                self._generate_similar_hscodes(hscode, product_description),
                self._generate_market_analysis(
                    hscode, product_description
                ),  # db_session 제거
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 결과 조합
            detail_info = {
                "tariff_info": (
                    results[0] if not isinstance(results[0], Exception) else {}
                ),
                "trade_agreement_info": (
                    results[1] if not isinstance(results[1], Exception) else {}
                ),
                "regulation_info": (
                    results[2] if not isinstance(results[2], Exception) else {}
                ),
                "non_tariff_info": (
                    results[3] if not isinstance(results[3], Exception) else {}
                ),
                "similar_hscodes_detailed": (
                    results[4] if not isinstance(results[4], Exception) else {}
                ),
                "market_analysis": (
                    results[5] if not isinstance(results[5], Exception) else {}
                ),
                "verification_status": "ai_generated",
                "data_quality_score": self._calculate_quality_score(results),
                "needs_update": False,
                "last_verified_at": datetime.utcnow().isoformat(),
                "expert_opinion": None,
                "generation_metadata": {
                    "generation_time_ms": int((time.time() - start_time) * 1000),
                    "ai_model": "claude-3-5-sonnet-20241022",
                    "generation_method": "comprehensive_parallel",
                    "data_sources": ["ai_analysis", "web_search"],
                    "quality_indicators": self._get_quality_indicators(results),
                },
            }

            logger.info(
                f"Detail generation completed in {detail_info['generation_metadata']['generation_time_ms']}ms"
            )
            return detail_info

        except Exception as e:
            logger.error(
                f"Error generating comprehensive detail info: {e}", exc_info=True
            )
            return self._get_fallback_detail_info(hscode, product_description)

    async def _generate_tariff_info(
        self, hscode: str, product_description: str
    ) -> Dict[str, Any]:
        """관세율 정보 생성"""

        prompt = f"""You are a trade expert specializing in tariff analysis. Generate comprehensive tariff information for HSCode {hscode} ({product_description}).

Provide detailed tariff information in the following JSON structure. Your response MUST be only the JSON object, without any additional text, explanations, or markdown formatting.

{{
    "countries": {{
        "KR": {{
            "basic_rate": "percentage or amount",
            "preferential_rates": {{}},
            "seasonal_rates": {{}},
            "notes": "special conditions"
        }},
        "CN": {{}},
        "US": {{}},
        "JP": {{}},
        "VN": {{}},
        "DE": {{}},
        "TH": {{}},
        "IN": {{}}
    }},
    "global_trends": {{
        "average_rate": "percentage",
        "rate_trend": "increasing/decreasing/stable",
        "affecting_factors": []
    }},
    "special_considerations": {{
        "wto_bound_rates": {{}},
        "anti_dumping": {{}},
        "safeguard_measures": {{}}
    }},
    "calculation_examples": [
        {{
            "country": "country_code",
            "product_value": 10000,
            "calculated_duty": 1500,
            "explanation": "calculation details"
        }}
    ]
}}
"""

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            # AI 응답에서 JSON 추출
            tariff_info = self._extract_json_from_response(response.content)

            # JSON 추출 실패 시 폴백 데이터 사용
            if not tariff_info or not isinstance(tariff_info, dict):
                logger.warning(
                    f"AI 응답에서 유효한 JSON 추출 실패, 폴백 데이터 사용: {hscode}"
                )
                tariff_info = self._get_fallback_tariff_info(hscode)

            # 웹 검색 보강 로직은 삭제됨

            return tariff_info

        except Exception as e:
            logger.error(f"Error generating tariff info: {e}")
            return self._get_fallback_tariff_info(hscode)

    async def _generate_trade_agreement_info(
        self, hscode: str, product_description: str
    ) -> Dict[str, Any]:
        """무역협정 정보 생성"""

        prompt = f"""Generate comprehensive trade agreement information for HSCode {hscode} ({product_description}).

Focus on FTA (Free Trade Agreement) benefits and EPA (Economic Partnership Agreement) advantages.

Provide information in this JSON structure. Your response MUST be only the JSON object, without any additional text, explanations, or markdown formatting.

{{
    "applicable_agreements": {{
        "KOREA_US_FTA": {{
            "preferential_rate": "percentage",
            "origin_requirements": "manufacturing requirements",
            "effective_date": "date",
            "phase_out_schedule": "immediate/5years/10years",
            "benefits": []
        }},
        "KOREA_EU_FTA": {{}},
        "RCEP": {{}},
        "CPTPP": {{}},
        "KOREA_CHINA_FTA": {{}},
        "KOREA_ASEAN_FTA": {{}}
    }},
    "origin_determination": {{
        "general_rules": [],
        "product_specific_rules": [],
        "cumulation_possibilities": []
    }},
    "certification_requirements": {{
        "certificate_of_origin": "required/not_required",
        "self_certification": "allowed/not_allowed",
        "supporting_documents": []
    }},
    "practical_benefits": {{
        "duty_savings_potential": "high/medium/low",
        "market_access_improvements": [],
        "procedural_simplifications": []
    }}
}}
"""

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            trade_info = self._extract_json_from_response(response.content)

            # 웹 검색 보강 로직은 삭제됨

            return trade_info

        except Exception as e:
            logger.error(f"Error generating trade agreement info: {e}")
            return self._get_fallback_trade_agreement_info(hscode)

    async def _generate_regulation_info(
        self, hscode: str, product_description: str
    ) -> Dict[str, Any]:
        """규제 정보 생성"""

        prompt = f"""Generate comprehensive regulatory information for HSCode {hscode} ({product_description}).

Cover import/export regulations, certification requirements, and compliance issues.

Provide information in this JSON structure. Your response MUST be only the JSON object, without any additional text, explanations, or markdown formatting.

{{
    "import_regulations": {{
        "korea": {{
            "licensing_required": true/false,
            "restricted_items": [],
            "certification_requirements": [
                {{
                    "type": "KC_certification",
                    "mandatory": true/false,
                    "validity_period": "duration",
                    "issuing_authority": "authority_name"
                }}
            ],
            "customs_procedures": [],
            "special_requirements": []
        }},
        "major_export_destinations": {{
            "china": {{}},
            "usa": {{}},
            "japan": {{}},
            "vietnam": {{}}
        }}
    }},
    "export_regulations": {{
        "export_licenses": [],
        "strategic_goods_control": {{}},
        "documentation_requirements": []
    }},
    "safety_standards": {{
        "product_safety": [],
        "environmental_compliance": [],
        "labeling_requirements": []
    }},
    "prohibited_restricted": {{
        "prohibited_countries": [],
        "restricted_quantities": {{}},
        "seasonal_restrictions": []
    }},
    "compliance_timeline": {{
        "immediate_requirements": [],
        "upcoming_changes": [
            {{
                "effective_date": "date",
                "change_description": "description",
                "impact_level": "high/medium/low"
            }}
        ]
    }}
}}
"""

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            regulation_info = self._extract_json_from_response(response.content)

            # 웹 검색 보강 로직은 삭제됨

            return regulation_info

        except Exception as e:
            logger.error(f"Error generating regulation info: {e}")
            return self._get_fallback_regulation_info(hscode)

    async def _generate_non_tariff_info(
        self, hscode: str, product_description: str
    ) -> Dict[str, Any]:
        """비관세 정보 생성"""

        prompt = f"""Generate comprehensive non-tariff trade barriers (NTBs) information for HSCode {hscode} ({product_description}).

Identify and describe various non-tariff trade barriers, including:
- Technical barriers (standards, regulations, conformity assessment procedures)
- Sanitary and phytosanitary measures (SPS)
- Customs procedures and documentation requirements
- Non-monetary measures (e.g., voluntary export restraints, voluntary import restraints)
- Trade remedies (anti-dumping, countervailing, safeguards)
- Trade restrictions (embargoes, prohibitions, quantitative restrictions)
- Trade sanctions

Provide information in this JSON structure. Your response MUST be only the JSON object, without any additional text, explanations, or markdown formatting.

{{
    "ntbs": {{
        "technical_barriers": {{
            "standards": [],
            "regulations": [],
            "conformity_assessment": []
        }},
        "sanitary_phytosanitary_measures": {{
            "general_requirements": [],
            "specific_requirements": []
        }},
        "customs_procedures": {{
            "documentation_requirements": [],
            "procedures": []
        }},
        "non_monetary_measures": {{
            "voluntary_export_restraints": [],
            "voluntary_import_restraints": []
        }},
        "trade_remedies": {{
            "anti_dumping": {{}},
            "countervailing": {{}},
            "safeguard": {{}}
        }},
        "trade_restrictions": {{
            "embargoes": [],
            "prohibitions": [],
            "quantitative_restrictions": []
        }},
        "trade_sanctions": []
    }},
    "practical_impact": {{
        "duty_savings_potential": "high/medium/low",
        "market_access_challenges": [],
        "procedural_simplifications": []
    }}
}}
"""

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            non_tariff_info = self._extract_json_from_response(response.content)

            # 웹 검색 보강 로직은 삭제됨

            return non_tariff_info

        except Exception as e:
            logger.error(f"Error generating non-tariff info: {e}")
            return self._get_fallback_non_tariff_info(hscode)

    async def _generate_similar_hscodes(
        self, hscode: str, product_description: str
    ) -> Dict[str, Any]:
        """유사 HSCode 정보 생성"""

        prompt = f"""Find and analyze similar HSCodes to {hscode} ({product_description}).

Identify related codes that users might be interested in or that could be alternative classifications.

Provide information in this JSON structure. Your response MUST be only the JSON object, without any additional text, explanations, or markdown formatting.

{{
    "direct_related": [
        {{
            "hscode": "similar_code",
            "description": "description",
            "similarity_score": 0.95,
            "relationship_type": "parent/child/sibling/alternative",
            "key_differences": [],
            "use_cases": []
        }}
    ],
    "category_related": [
        {{
            "hscode": "category_code",
            "description": "description", 
            "similarity_score": 0.80,
            "category": "같은 카테고리",
            "why_related": "관련성 설명"
        }}
    ],
    "functional_alternatives": [
        {{
            "hscode": "alternative_code",
            "description": "description",
            "similarity_score": 0.75,
            "functional_similarity": "기능적 유사성",
            "market_positioning": "시장에서의 위치"
        }}
    ],
    "classification_tips": {{
        "common_mistakes": [],
        "decision_tree": [],
        "expert_guidance": []
    }}
}}
"""

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            similar_info = self._extract_json_from_response(response.content)
            return similar_info

        except Exception as e:
            logger.error(f"Error generating similar HSCodes: {e}")
            return self._get_fallback_similar_hscodes(hscode)

    async def _generate_market_analysis(
        self, hscode: str, product_description: str
    ) -> Dict[str, Any]:
        """시장 분석 정보 생성"""

        prompt = f"""Generate comprehensive market analysis for HSCode {hscode} ({product_description}).

Provide trade statistics, trends, and market insights.

Structure the information as follows. Your response MUST be only the JSON object, without any additional text, explanations, or markdown formatting.

{{
    "trade_statistics": {{
        "korea_exports": {{
            "total_value_usd": 0,
            "growth_rate_yoy": 0.0,
            "top_destinations": [
                {{
                    "country": "country_name",
                    "value_usd": 0,
                    "market_share": 0.0,
                    "growth_trend": "increasing/stable/decreasing"
                }}
            ]
        }},
        "korea_imports": {{
            "total_value_usd": 0,
            "growth_rate_yoy": 0.0,
            "top_origins": []
        }},
        "global_trade": {{
            "total_market_size_usd": 0,
            "major_players": [],
            "market_concentration": "high/medium/low"
        }}
    }},
    "market_trends": {{
        "demand_drivers": [],
        "supply_factors": [],
        "price_trends": {{
            "direction": "increasing/decreasing/stable",
            "factors": [],
            "forecast": "short_term_outlook"
        }},
        "technological_developments": [],
        "regulatory_changes_impact": []
    }},
    "competitive_landscape": {{
        "key_players": [],
        "market_entry_barriers": [],
        "opportunities": [],
        "threats": []
    }},
    "future_outlook": {{
        "growth_projections": {{}},
        "emerging_markets": [],
        "disruptive_factors": [],
        "strategic_recommendations": []
    }}
}}
"""

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            market_info = self._extract_json_from_response(response.content)

            # 웹 검색 보강 로직은 삭제됨

            return market_info

        except Exception as e:
            logger.error(f"Error generating market analysis: {e}")
            return self._get_fallback_market_analysis(hscode)

    # _search_*_web_info 헬퍼 메서드들은 모두 삭제합니다.
    # async def _search_tariff_web_info...
    # async def _search_trade_agreement_web_info...
    # async def _search_regulation_web_info...
    # async def _search_market_web_info...
    # async def _search_non_tariff_web_info...

    def _extract_json_from_response(self, response_content) -> Dict[str, Any]:
        """AI 응답에서 JSON 추출 - 다양한 응답 타입 처리"""
        text = ""
        try:
            # 응답 타입에 따른 처리
            if isinstance(response_content, str):
                text = response_content
            elif isinstance(response_content, list):
                # list인 경우 첫 번째 문자열 요소 찾기
                for item in response_content:
                    if isinstance(item, str):
                        text = item
                        break
                    elif isinstance(item, dict) and "text" in item:
                        text = item["text"]
                        break
                if not text:
                    logger.warning("No text content found in list response")
                    return {"error": "No text content found in list response"}
            else:
                # 기타 타입인 경우 문자열로 변환 시도
                text = str(response_content)

            text = text.strip()

            # JSON 블록 찾기 (마크다운 코드 블록 제거)
            if text.startswith("```json"):
                text = text[len("```json") :].strip()
            if text.startswith("```"):
                text = text[len("```") :].strip()
            if text.endswith("```"):
                text = text[: -len("```")].strip()

            # 응답 시작에 있는 불필요한 텍스트 제거 (예: "Here is the JSON...")
            start_pos = text.find("{")
            if start_pos == -1:
                raise json.JSONDecodeError("No JSON object found in response", text, 0)

            # 응답 끝에 있는 불필요한 텍스트 제거
            end_pos = text.rfind("}")
            if end_pos == -1:
                raise json.JSONDecodeError("No JSON object found in response", text, 0)

            json_text = text[start_pos : end_pos + 1]

            return json.loads(json_text)

        except json.JSONDecodeError as e:
            logger.warning(
                f"Failed to decode JSON from response. Error: {e}. Raw text: '{text[:500]}...'"
            )
            return {
                "error": "JSON parsing failed",
                "reason": str(e),
                "raw_response": text[:500],
            }
        except Exception as e:
            logger.warning(
                f"An unexpected error occurred in _extract_json_from_response: {e}"
            )
            return {
                "error": "Unexpected error during JSON extraction",
                "reason": str(e),
                "raw_response": text[:500],
            }

    def _calculate_quality_score(self, results: List[Any]) -> float:
        """생성된 정보의 품질 점수 계산"""
        if not results:
            return 0.0

        successful_results = 0
        for r in results:
            if isinstance(r, dict) and "error" not in r:
                successful_results += 1

        total_results = len(results)

        if total_results == 0:
            return 0.0

        base_score = successful_results / total_results

        # 각 결과의 내용 품질 평가
        content_quality = 0.0
        for result in results:
            if isinstance(result, dict) and "error" not in result:
                # 키의 개수와 값의 존재 여부로 품질 평가
                if len(result) > 2 and any(result.values()):
                    content_quality += 0.2
                else:
                    content_quality += 0.05

        # 최종 점수는 1점을 넘지 않도록 하고, 성공한 결과가 하나도 없다면 0.1 이하로 유지
        final_score = base_score
        if successful_results > 0:
            final_score += content_quality / successful_results

        if successful_results == 0:
            return 0.1  # 모든 정보 생성 실패 시 매우 낮은 점수

        return min(final_score, 1.0)

    def _get_quality_indicators(self, results: List[Any]) -> Dict[str, Any]:
        """품질 지표 생성"""
        successful_generations = sum(
            1 for r in results if isinstance(r, dict) and "error" not in r
        )
        return {
            "successful_generations": successful_generations,
            "total_attempts": len(results),
            "error_details": [
                r for r in results if isinstance(r, dict) and "error" in r
            ],
            "data_completeness": (
                "high"
                if successful_generations == len(results)
                else ("partial" if successful_generations > 0 else "failed")
            ),
        }

    def _get_fallback_detail_info(
        self, hscode: str, product_description: str
    ) -> Dict[str, Any]:
        """폴백 상세 정보"""
        return {
            "tariff_info": self._get_fallback_tariff_info(hscode),
            "trade_agreement_info": self._get_fallback_trade_agreement_info(hscode),
            "regulation_info": self._get_fallback_regulation_info(hscode),
            "non_tariff_info": self._get_fallback_non_tariff_info(hscode),
            "similar_hscodes_detailed": self._get_fallback_similar_hscodes(hscode),
            "market_analysis": self._get_fallback_market_analysis(hscode),
            "verification_status": "fallback_generated",
            "data_quality_score": 0.3,
            "needs_update": True,
            "last_verified_at": datetime.utcnow().isoformat(),
            "expert_opinion": "Fallback data - requires expert verification",
            "generation_metadata": {
                "generation_method": "fallback",
                "note": "Generated using fallback templates due to errors",
            },
        }

    def _get_fallback_tariff_info(self, hscode: str) -> Dict[str, Any]:
        """폴백 관세율 정보"""
        return {
            "note": "Basic fallback information - requires verification",
            "countries": {
                "KR": {"basic_rate": "Variable", "notes": "Check customs.go.kr"},
                "CN": {"basic_rate": "Variable", "notes": "Check customs.gov.cn"},
                "US": {"basic_rate": "Variable", "notes": "Check hts.usitc.gov"},
            },
            "recommendation": f"Please verify current tariff rates for HSCode {hscode}",
        }

    def _get_fallback_trade_agreement_info(self, hscode: str) -> Dict[str, Any]:
        """폴백 무역협정 정보"""
        return {
            "note": "Basic fallback information - requires verification",
            "applicable_agreements": {
                "KOREA_US_FTA": {"status": "Check official sources"},
                "KOREA_EU_FTA": {"status": "Check official sources"},
                "RCEP": {"status": "Check official sources"},
            },
            "recommendation": f"Please verify FTA benefits for HSCode {hscode}",
        }

    def _get_fallback_regulation_info(self, hscode: str) -> Dict[str, Any]:
        """폴백 규제 정보"""
        return {
            "note": "Basic fallback information - requires verification",
            "import_regulations": {
                "korea": {"recommendation": "Check KATS and customs regulations"}
            },
            "export_regulations": {
                "recommendation": "Check MOTIE export control guidelines"
            },
            "recommendation": f"Please verify regulatory requirements for HSCode {hscode}",
        }

    def _get_fallback_non_tariff_info(self, hscode: str) -> Dict[str, Any]:
        """폴백 비관세 정보"""
        return {
            "note": "Basic fallback information - requires verification",
            "ntbs": {
                "technical_barriers": {
                    "recommendation": "Check WTO and national regulations"
                },
                "sanitary_phytosanitary_measures": {
                    "recommendation": "Check FAO and national standards"
                },
                "customs_procedures": {
                    "recommendation": "Check national customs procedures"
                },
                "non_monetary_measures": {
                    "recommendation": "Check WTO and national agreements"
                },
                "trade_remedies": {"recommendation": "Check WTO and national remedies"},
                "trade_restrictions": {
                    "recommendation": "Check WTO and national restrictions"
                },
                "trade_sanctions": {
                    "recommendation": "Check WTO and national sanctions"
                },
            },
            "practical_impact": {
                "recommendation": f"Please verify non-tariff barriers for HSCode {hscode}"
            },
        }

    def _get_fallback_similar_hscodes(self, hscode: str) -> Dict[str, Any]:
        """폴백 유사 HSCode 정보"""
        # HSCode의 상위 카테고리 추출
        base_code = hscode[:4] if len(hscode) >= 4 else hscode
        return {
            "note": "Basic similar codes - requires verification",
            "category_hint": f"Check other codes in {base_code}.xx series",
            "recommendation": f"Consult HSCode classification manual for {hscode}",
        }

    def _get_fallback_market_analysis(self, hscode: str) -> Dict[str, Any]:
        """폴백 시장 분석 정보"""
        return {
            "note": "Basic fallback information - requires verification",
            "data_sources": {
                "korean_statistics": "Check KITA TradeNavi",
                "global_statistics": "Check UN Comtrade",
                "market_reports": "Check industry associations",
            },
            "recommendation": f"Please gather current market data for HSCode {hscode}",
        }
