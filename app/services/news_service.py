import asyncio
import logging
import re
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, HttpUrl, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession
from rapidfuzz import fuzz, process, utils

from app.chains.prompt_chains import create_trade_news_prompt
from app.core.config import settings
from app.core.llm_provider import llm_provider
from app.db import crud
from app.models.schemas import TradeNewsCreate
from app.utils.llm_response_parser import (
    extract_citation_urls_from_ai_message,
    extract_json_from_ai_message,
)

if TYPE_CHECKING:
    from app.models.db_models import Bookmark

logger = logging.getLogger(__name__)


def _normalize_title(title: str) -> str:
    """뉴스 제목을 비교 가능하도록 정규화"""
    if not title:
        return ""

    # RapidFuzz의 기본 처리기 사용하여 정규화
    # 대소문자 변환, 특수문자 제거, 여러 공백을 하나로 합침
    return utils.default_process(title) or ""


def _calculate_content_similarity(
    item1: Dict[str, Any], item2: Dict[str, Any]
) -> float:
    """두 뉴스 항목 간의 종합적인 유사도 계산"""

    # 제목 유사도 (가중치 60%)
    title1 = item1.get("title", "")
    title2 = item2.get("title", "")
    title_similarity = fuzz.WRatio(title1, title2, processor=utils.default_process)

    # 요약 유사도 (가중치 30%)
    summary1 = item1.get("summary", "")
    summary2 = item2.get("summary", "")
    summary_similarity = fuzz.WRatio(
        summary1, summary2, processor=utils.default_process
    )

    # 소스명 유사도 (가중치 10%)
    source1 = item1.get("source_name", "")
    source2 = item2.get("source_name", "")
    source_similarity = fuzz.WRatio(source1, source2, processor=utils.default_process)

    # 가중 평균 계산
    weighted_similarity = (
        title_similarity * 0.6 + summary_similarity * 0.3 + source_similarity * 0.1
    )

    return weighted_similarity


def _is_duplicate_content(
    item1: Dict[str, Any], item2: Dict[str, Any], similarity_threshold: float = 85.0
) -> bool:
    """두 뉴스 항목이 중복인지 판단"""

    # URL이 같으면 확실히 중복
    url1 = item1.get("source_url", "")
    url2 = item2.get("source_url", "")
    if url1 and url2 and url1 == url2:
        return True

    # 내용 유사도 기반 중복 검사
    similarity = _calculate_content_similarity(item1, item2)

    # 디버깅 로그
    if similarity > 70.0:  # 높은 유사도 항목들만 로그
        logger.debug(
            f"Content similarity: {similarity:.1f}% - "
            f"Title1: '{item1.get('title', '')[:50]}...' vs "
            f"Title2: '{item2.get('title', '')[:50]}...'"
        )

    return similarity >= similarity_threshold


def _remove_duplicates_from_new_items(
    new_items: List[Dict[str, Any]], new_urls: List[str]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """신규 뉴스 항목들 내에서 중복 제거"""

    if not new_items:
        return [], []

    unique_items = []
    unique_urls = []

    for i, item in enumerate(new_items):
        is_duplicate = False

        # 이미 추가된 항목들과 비교
        for existing_item in unique_items:
            if _is_duplicate_content(item, existing_item):
                logger.debug(
                    f"Removing duplicate within new items: '{item.get('title', '')[:50]}...'"
                )
                is_duplicate = True
                break

        if not is_duplicate:
            unique_items.append(item)
            unique_urls.append(new_urls[i] if i < len(new_urls) else "")

    logger.info(
        f"Removed {len(new_items) - len(unique_items)} duplicates within new items. "
        f"Final count: {len(unique_items)}"
    )

    return unique_items, unique_urls


def _filter_against_existing_news(
    new_items: List[Dict[str, Any]], new_urls: List[str], existing_news: List[Any]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """기존 뉴스와 비교하여 중복 제거"""

    if not new_items or not existing_news:
        return new_items, new_urls

    # 기존 뉴스 데이터를 딕셔너리 형태로 변환
    existing_items = []
    existing_urls = set()

    for news in existing_news:
        existing_item = {
            "title": str(news.title) if news.title else "",
            "summary": str(news.summary) if news.summary else "",
            "source_name": str(news.source_name) if news.source_name else "",
            "source_url": str(news.source_url) if news.source_url else "",
        }
        existing_items.append(existing_item)
        if news.source_url:
            existing_urls.add(str(news.source_url))

    unique_items = []
    unique_urls = []

    for i, new_item in enumerate(new_items):
        is_duplicate = False
        new_url = new_urls[i] if i < len(new_urls) else ""

        # 1차: URL 중복 검사 (빠른 검사)
        if new_url in existing_urls:
            logger.debug(f"URL duplicate found: {new_url}")
            is_duplicate = True
        else:
            # 2차: 내용 유사도 기반 중복 검사
            for existing_item in existing_items:
                if _is_duplicate_content(new_item, existing_item):
                    logger.debug(
                        f"Content duplicate found: '{new_item.get('title', '')[:50]}...' vs "
                        f"'{existing_item.get('title', '')[:50]}...'"
                    )
                    is_duplicate = True
                    break

        if not is_duplicate:
            unique_items.append(new_item)
            unique_urls.append(new_url)

    logger.info(
        f"Filtered against existing news: {len(new_items)} -> {len(unique_items)} "
        f"({len(new_items) - len(unique_items)} duplicates removed)"
    )

    return unique_items, unique_urls


class NewsService:
    """
    LLM의 웹 검색 기능을 활용하여 최신 무역 뉴스를 생성하고,
    북마크 관련 업데이트를 찾는 비즈니스 로직을 처리.
    """

    def __init__(self):
        # llm_provider에서 웹 검색 기능이 바인딩된 모델을 가져옴
        self.llm_with_native_search = llm_provider.news_llm_with_native_search
        self.anthropic_chat_model = llm_provider.news_chat_model

    def _create_news_dtos_from_response(
        self, news_items_from_llm: List[Dict[str, Any]], citation_urls: List[str]
    ) -> List[TradeNewsCreate]:
        """LLM 응답과 URL 리스트를 TradeNewsCreate DTO 리스트로 변환"""
        final_news_list: List[TradeNewsCreate] = []
        url_validator = TypeAdapter(HttpUrl)

        num_items_to_process = min(len(news_items_from_llm), len(citation_urls))
        if len(news_items_from_llm) != len(citation_urls):
            logger.warning(
                "Mismatch between number of news items (%d) and available URLs (%d). Processing %d items.",
                len(news_items_from_llm),
                len(citation_urls),
                num_items_to_process,
            )

        logger.info(f"Processing {num_items_to_process} news items.")
        fetched_time = datetime.now(timezone.utc)

        for i in range(num_items_to_process):
            item_data = news_items_from_llm[i]
            source_url = citation_urls[i]
            logger.debug(f"Processing item {i}: data={item_data}, url='{source_url}'")
            try:
                # 타입 안전성을 위한 None 값 검증
                published_at_str = item_data.get("published_at")
                if not published_at_str or not isinstance(published_at_str, str):
                    logger.warning(
                        f"Invalid published_at for item {i}: {published_at_str}"
                    )
                    continue

                published_at_dt = datetime.fromisoformat(published_at_str)
                if published_at_dt.tzinfo is None:
                    published_at_dt = published_at_dt.replace(tzinfo=timezone.utc)

                # 필수 필드 검증
                title = item_data.get("title")
                summary = item_data.get("summary")
                source_name = item_data.get("source_name")

                if not title or not isinstance(title, str):
                    logger.warning(f"Invalid title for item {i}: {title}")
                    continue

                if not summary or not isinstance(summary, str):
                    logger.warning(f"Invalid summary for item {i}: {summary}")
                    continue

                if not source_name or not isinstance(source_name, str):
                    logger.warning(f"Invalid source_name for item {i}: {source_name}")
                    continue

                final_news_list.append(
                    TradeNewsCreate(
                        title=title,
                        summary=summary,
                        source_name=source_name,
                        published_at=published_at_dt,
                        source_url=url_validator.validate_python(source_url),
                        category=item_data.get("category", "General"),
                        priority=item_data.get("priority", 1),
                        fetched_at=fetched_time,
                    )
                )
            except Exception as e:
                logger.warning("Skipping item %d due to invalid data. Error: %s", i, e)
                continue

        if not final_news_list:
            logger.warning("No news items were successfully created after processing.")

        return final_news_list

    async def create_news_via_claude(self, db: AsyncSession) -> List[TradeNewsCreate]:
        """
        Claude의 웹 검색 기능과 RapidFuzz 기반 중복 제거 로직을 결합하여
        신뢰성 높은 최신 무역 뉴스를 생성.
        """
        try:
            # 1. 기존 뉴스 데이터 조회 (중복 제거용)
            seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
            recent_news = await crud.trade_news.get_recent_trade_news(
                db, since=seven_days_ago
            )

            logger.info(
                f"Loaded {len(recent_news)} recent news items for duplicate detection."
            )

            # 2. LLM을 통한 뉴스 생성
            now_utc = datetime.now(timezone.utc)
            three_days_ago_utc = now_utc - timedelta(days=3)
            date_format = "%Y-%m-%d"
            current_date_str = now_utc.strftime(date_format)
            start_date_str = three_days_ago_utc.strftime(date_format)

            logger.info(
                f"News generation started for period: {start_date_str} ~ {current_date_str}"
            )

            prompt = create_trade_news_prompt(start_date_str, current_date_str)
            chain = prompt | self.llm_with_native_search

            logger.info("Initiating single-call news generation...")
            response_message = await chain.ainvoke({})
            logger.debug(
                "LLM response received.",
                extra={
                    "response_content": response_message.content,
                    "response_metadata": response_message.response_metadata,
                },
            )
            logger.info("News generation call completed.")

            # BaseMessage를 AIMessage로 캐스팅
            if isinstance(response_message, AIMessage):
                ai_message = response_message
            else:
                # BaseMessage를 AIMessage로 변환
                ai_message = AIMessage(
                    content=response_message.content,
                    response_metadata=getattr(
                        response_message, "response_metadata", {}
                    ),
                    id=getattr(response_message, "id", None),
                )

            json_string = extract_json_from_ai_message(ai_message)
            if not json_string:
                logger.error(
                    "Failed to extract clean JSON from LLM response.",
                    extra={"raw_response": response_message.content},
                )
                return []

            parser = JsonOutputParser()
            parsed_json = parser.parse(json_string)
            news_items_from_llm = parsed_json.get("news_items", [])
            logger.info(
                f"Found {len(news_items_from_llm)} news items in JSON response."
            )

            citation_urls = extract_citation_urls_from_ai_message(ai_message)

            # 3. 신규 뉴스 항목들 내에서 중복 제거
            logger.info("Starting duplicate removal within new items...")
            unique_new_items, unique_new_urls = _remove_duplicates_from_new_items(
                news_items_from_llm, citation_urls
            )

            # 4. 기존 뉴스와 비교하여 중복 제거
            logger.info("Starting duplicate removal against existing news...")
            final_unique_items, final_unique_urls = _filter_against_existing_news(
                unique_new_items, unique_new_urls, recent_news
            )

            original_count = len(news_items_from_llm)
            final_count = len(final_unique_items)
            logger.info(
                f"Advanced duplicate removal completed. "
                f"Original: {original_count}, Final: {final_count} "
                f"({original_count - final_count} duplicates removed)"
            )

            if not final_unique_items:
                logger.info("No new unique news items found after advanced filtering.")
                return []

            # 5. DTO 생성 및 반환
            final_news_list = self._create_news_dtos_from_response(
                final_unique_items, final_unique_urls
            )

            logger.info(f"Successfully created {len(final_news_list)} news items.")
            return final_news_list

        except Exception as e:
            logger.error(
                "An error occurred while creating news via Claude.", exc_info=True
            )
            traceback.print_exc()
            return []

    async def find_updates_for_bookmark(
        self, bookmark: "Bookmark"
    ) -> Optional[Dict[str, Any]]:
        """
        주어진 북마크 객체에 대한 최신 업데이트를 웹에서 검색하고,
        UpdateFeedCreate 스키마에 맞는 딕셔너리를 반환.
        """
        prompt_text = (
            f"Find any updates (news, regulation changes, tariff adjustments) related to '{bookmark.target_value}' "
            f"(type: {bookmark.type.value}) within the last 24 hours. "
            "If you find a significant update, provide a concise Korean title for the update, "
            "a detailed summary in Korean, the source URL, and rate its importance ('HIGH', 'MEDIUM', 'LOW'). "
            "Format the output as a JSON object with 'title', 'content', 'source_url', and 'importance' keys. "
            "If no significant update is found, return an empty JSON object {}."
        )

        class UpdateInfo(BaseModel):
            title: Optional[str] = None
            content: Optional[str] = None
            source_url: Optional[str] = None
            importance: Optional[str] = None

        # ChatAnthropic 모델에서 structured output 사용
        try:
            # 프롬프트와 함께 일반 호출 후 결과 파싱
            prompt_template = ChatPromptTemplate.from_template(prompt_text)
            chain = prompt_template | self.anthropic_chat_model

            response = await chain.ainvoke({})

            # 응답에서 JSON 추출 시도
            if isinstance(response, AIMessage):
                ai_message = response
            else:
                ai_message = AIMessage(
                    content=response.content,
                    response_metadata=getattr(response, "response_metadata", {}),
                    id=getattr(response, "id", None),
                )

            json_string = extract_json_from_ai_message(ai_message)
            if not json_string:
                return None

            parser = JsonOutputParser()
            parsed_json = parser.parse(json_string)

            # UpdateInfo 모델로 검증
            update_info = UpdateInfo(**parsed_json)

        except Exception as e:
            logger.error(f"Error in find_updates_for_bookmark: {e}")
            return None

        if not update_info.title or not update_info.content:
            return None

        return {
            "user_id": bookmark.user_id,
            "feed_type": "TRADE_NEWS",
            "target_type": bookmark.type.value,
            "target_value": bookmark.target_value,
            "title": update_info.title,
            "content": update_info.content,
            "source_url": update_info.source_url,
            "importance": update_info.importance or "MEDIUM",
        }
