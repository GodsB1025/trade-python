import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.models.db_models import WebSearchCache

logger = logging.getLogger(__name__)


class WebSearchService:
    """웹 검색 서비스 - 실제 웹 검색 및 캐싱 처리"""

    def __init__(self):
        self.cache_ttl_hours = 24  # 캐시 유지 시간 (24시간)
        self.max_results_per_search = 10

    async def search_hscode_info(
        self, query: str, db: AsyncSession, product_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """HSCode 관련 정보를 웹에서 검색"""

        # 검색 쿼리 생성
        search_query = self._build_hscode_search_query(query, product_name)
        search_hash = self._get_search_hash(search_query)

        # 캐시 확인
        cached_result = await self._get_cached_result(db, search_hash)
        if cached_result:
            logger.info(f"캐시된 HSCode 검색 결과 반환: {search_hash[:8]}...")
            return cached_result

        # 실제 웹 검색 수행
        search_results = await self._perform_web_search(search_query, "hscode")

        # 결과 처리 및 HSCode 추출
        processed_results = self._process_hscode_results(search_results)

        # 캐시에 저장
        await self._save_to_cache(
            db, search_hash, search_query, "hscode", processed_results, "web_search_api"
        )

        return processed_results

    async def search_regulation_info(
        self, hscode: str, db: AsyncSession, country: str = "KR"
    ) -> Dict[str, Any]:
        """규제 정보를 웹에서 검색"""

        search_query = f"HSCode {hscode} 규제 관세 {country} 수출입"
        search_hash = self._get_search_hash(search_query)

        # 캐시 확인
        cached_result = await self._get_cached_result(db, search_hash)
        if cached_result:
            logger.info(f"캐시된 규제 정보 검색 결과 반환: {search_hash[:8]}...")
            return cached_result

        # 실제 웹 검색 수행
        search_results = await self._perform_web_search(search_query, "regulation")

        # 결과 처리
        processed_results = self._process_regulation_results(search_results, hscode)

        # 캐시에 저장
        await self._save_to_cache(
            db,
            search_hash,
            search_query,
            "regulation",
            processed_results,
            "web_search_api",
        )

        return processed_results

    def _build_hscode_search_query(
        self, query: str, product_name: Optional[str] = None
    ) -> str:
        """HSCode 검색 쿼리 생성"""
        base_query = f"{query} HSCode 품목번호"

        if product_name:
            base_query += f" {product_name}"

        # 한국 관세청 사이트 우선 검색
        base_query += " site:customs.go.kr OR 관세청 OR 품목분류"

        return base_query

    def _get_search_hash(self, query: str) -> str:
        """검색 쿼리의 SHA256 해시 생성"""
        return hashlib.sha256(query.encode("utf-8")).hexdigest()

    async def _get_cached_result(
        self, db: AsyncSession, search_hash: str
    ) -> Optional[Dict[str, Any]]:
        """캐시된 검색 결과 조회"""
        try:
            # 만료되지 않은 캐시 조회
            stmt = select(WebSearchCache).where(
                WebSearchCache.search_query_hash == search_hash,
                WebSearchCache.expires_at > datetime.utcnow(),
            )
            result = await db.execute(stmt)
            cache_entry = result.scalars().first()

            if cache_entry:
                # JSONB 컬럼 값을 직접 반환 (타입 체킹 무시)
                return cache_entry.search_results  # type: ignore

            return None

        except Exception as e:
            logger.warning(f"캐시 조회 중 오류: {e}")
            return None

    async def _perform_web_search(
        self, query: str, search_type: str
    ) -> List[Dict[str, Any]]:
        """실제 웹 검색 수행 (시뮬레이션 + 실제 구현 준비)"""

        logger.info(f"웹 검색 수행: {query}")

        # 현재는 시뮬레이션 데이터를 반환하지만,
        # 실제로는 Google Search API, Bing Search API 등을 사용할 수 있음
        await asyncio.sleep(0.5)  # 네트워크 지연 시뮬레이션

        # 실제 검색 결과를 시뮬레이션
        mock_results = self._generate_mock_search_results(query, search_type)

        return mock_results

    def _generate_mock_search_results(
        self, query: str, search_type: str
    ) -> List[Dict[str, Any]]:
        """모의 검색 결과 생성 (실제 API 연동 전까지 사용)"""

        if search_type == "hscode":
            if "스마트폰" in query or "휴대폰" in query:
                return [
                    {
                        "title": "휴대전화 및 기타 무선 네트워크용 전화기 - 관세청",
                        "url": "https://customs.go.kr/tariff/8517.12.00",
                        "snippet": "HSCode 8517.12.00 - 휴대전화 및 기타 무선 네트워크용 전화기. 일반적인 스마트폰은 이 코드로 분류됩니다. 관세율: 기본 8%, FTA 협정세율 적용 시 0~3%",
                        "hscode": "8517.12.00",
                        "confidence": 0.95,
                    },
                    {
                        "title": "스마트폰 수출입 품목분류 상세 가이드 - KOTRA",
                        "url": "https://kotra.or.kr/guide/smartphone-classification-detailed",
                        "snippet": "스마트폰 HSCode 8517.12.00 적용 기준: ①무선 통신 기능 ②음성통화 기능 ③데이터 통신 기능을 모두 갖춘 휴대용 단말기",
                        "hscode": "8517.12.00",
                        "confidence": 0.90,
                    },
                    {
                        "title": "산업용 방폭 스마트폰 품목분류 특례 - 관세청",
                        "url": "https://customs.go.kr/special/atex-smartphone-classification",
                        "snippet": "ATEX/IECEx 방폭 인증 스마트폰도 통신 기능이 주된 목적이면 8517.12.00으로 분류. 방폭 기능은 안전 기준이지 별도 HSCode 사유가 아님",
                        "hscode": "8517.12.00",
                        "confidence": 0.85,
                    },
                    {
                        "title": "무전기 기능 스마트폰 분류 기준 - 관세청 품목분류과",
                        "url": "https://customs.go.kr/classification/radio-smartphone",
                        "snippet": "PTT(Push-to-Talk) 기능이 추가된 스마트폰은 주기능이 휴대전화이면 8517.12.00, 무전기가 주기능이면 8517.62.00으로 분류",
                        "hscode": "8517.12.00",
                        "confidence": 0.80,
                    },
                ]
            elif "노트북" in query or "laptop" in query:
                return [
                    {
                        "title": "휴대용 자동자료처리기계(노트북) - 관세청",
                        "url": "https://customs.go.kr/tariff/8471.30.00",
                        "snippet": "HSCode 8471.30.00 - 휴대용 자동자료처리기계. 노트북 컴퓨터가 해당됩니다. 관세율: 기본 0%, FTA 협정세율 0%",
                        "hscode": "8471.30.00",
                        "confidence": 0.95,
                    },
                    {
                        "title": "게이밍 노트북 분류기준 - 관세청",
                        "url": "https://customs.go.kr/classification/gaming-laptop",
                        "snippet": "고성능 그래픽카드 탑재 게이밍 노트북도 자동자료처리기계로 분류. GPU 성능이 아닌 주된 용도로 판단",
                        "hscode": "8471.30.00",
                        "confidence": 0.90,
                    },
                ]
            elif "자동차" in query:
                return [
                    {
                        "title": "승용자동차 품목분류 - 관세청",
                        "url": "https://customs.go.kr/tariff/8703.00.00",
                        "snippet": "HSCode 8703류 - 승용자동차 및 기타 차량. 배기량, 연료 종류에 따라 세부 분류",
                        "hscode": "8703.21.00",
                        "confidence": 0.90,
                    }
                ]

        elif search_type == "regulation":
            return [
                {
                    "title": "전자제품 수출입 규제 현황 - 관세청",
                    "url": "https://customs.go.kr/regulation/electronics",
                    "snippet": "전자제품 수출입 시 주의해야 할 규제사항과 인증 요구사항",
                    "confidence": 0.85,
                },
                {
                    "title": "통신기기 전파인증 가이드 - 방송통신위원회",
                    "url": "https://kcc.go.kr/certification/guide",
                    "snippet": "스마트폰 등 통신기기 수입 시 필요한 전파인증 절차",
                    "confidence": 0.80,
                },
            ]

        return []

    def _process_hscode_results(
        self, search_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """HSCode 검색 결과 처리"""

        # HSCode 추출 및 신뢰도 기반 정렬
        hscode_candidates = []
        source_urls = []

        for result in search_results:
            if "hscode" in result:
                hscode_candidates.append(
                    {
                        "hscode": result["hscode"],
                        "confidence": result.get("confidence", 0.5),
                        "source": result.get("title", ""),
                        "url": result.get("url", ""),
                    }
                )

            source_urls.append(
                {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("snippet", ""),
                }
            )

        # 신뢰도 순으로 정렬
        hscode_candidates.sort(key=lambda x: x["confidence"], reverse=True)

        # 가장 신뢰도 높은 HSCode 선택
        primary_hscode = hscode_candidates[0]["hscode"] if hscode_candidates else None

        return {
            "primary_hscode": primary_hscode,
            "hscode_candidates": hscode_candidates,
            "source_urls": source_urls,
            "search_performed": True,
            "result_count": len(search_results),
            "processed_at": datetime.utcnow().isoformat(),
        }

    def _process_regulation_results(
        self, search_results: List[Dict[str, Any]], hscode: str
    ) -> Dict[str, Any]:
        """규제 정보 검색 결과 처리"""

        regulation_info = []
        source_urls = []

        for result in search_results:
            regulation_info.append(
                {
                    "type": "regulation",
                    "title": result.get("title", ""),
                    "description": result.get("snippet", ""),
                    "confidence": result.get("confidence", 0.5),
                }
            )

            source_urls.append(
                {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("snippet", ""),
                }
            )

        return {
            "hscode": hscode,
            "regulation_info": regulation_info,
            "source_urls": source_urls,
            "search_performed": True,
            "result_count": len(search_results),
            "processed_at": datetime.utcnow().isoformat(),
        }

    async def _save_to_cache(
        self,
        db: AsyncSession,
        search_hash: str,
        search_query: str,
        search_type: str,
        search_results: Dict[str, Any],
        provider: str,
    ) -> None:
        """검색 결과를 캐시에 저장"""
        try:
            expires_at = datetime.utcnow() + timedelta(hours=self.cache_ttl_hours)

            cache_entry = WebSearchCache(
                search_query_hash=search_hash,
                search_query=search_query,
                search_type=search_type,
                search_results=search_results,
                result_count=search_results.get("result_count", 0),
                search_provider=provider,
                expires_at=expires_at,
            )

            db.add(cache_entry)
            await db.flush()

            logger.info(f"검색 결과를 캐시에 저장: {search_hash[:8]}...")

        except Exception as e:
            logger.error(f"캐시 저장 중 오류: {e}")

    async def cleanup_expired_cache(self, db: AsyncSession) -> int:
        """만료된 캐시 엔트리 정리"""
        try:
            stmt = delete(WebSearchCache).where(
                WebSearchCache.expires_at <= datetime.utcnow()
            )
            result = await db.execute(stmt)
            deleted_count = result.rowcount

            await db.commit()

            logger.info(f"만료된 캐시 {deleted_count}개 정리 완료")
            return deleted_count

        except Exception as e:
            logger.error(f"캐시 정리 중 오류: {e}")
            await db.rollback()
            return 0
