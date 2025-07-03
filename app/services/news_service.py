import asyncio
import logging
import re
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, HttpUrl, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.chains.prompt_chains import create_trade_news_prompt
from app.core.config import settings
from app.core.llm_provider import llm_provider
from app.db import crud
from app.models.schemas import TradeNewsCreate
from app.utils.llm_response_parser import (
    extract_citation_urls_from_ai_message, extract_json_from_ai_message
)

logger = logging.getLogger(__name__)


def _normalize_title(title: str) -> str:
    """뉴스 제목을 비교 가능하도록 정규화. 소문자 변환, 공백/특수문자 제거."""
    if not title:
        return ""
    # 소문자로 변환
    title = title.lower()
    # 모든 비-단어 문자(알파벳, 숫자 제외)를 공백으로 대체
    title = re.sub(r'\W+', '', title)
    # 앞뒤 공백 제거
    return title.strip()


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
        self,
        news_items_from_llm: List[Dict[str, Any]],
        citation_urls: List[str]
    ) -> List[TradeNewsCreate]:
        """LLM 응답과 URL 리스트를 TradeNewsCreate DTO 리스트로 변환."""
        final_news_list: List[TradeNewsCreate] = []
        url_validator = TypeAdapter(HttpUrl)

        num_items_to_process = min(
            len(news_items_from_llm), len(citation_urls))
        if len(news_items_from_llm) != len(citation_urls):
            logger.warning(
                "Mismatch between number of news items (%d) and available URLs (%d). Processing %d items.",
                len(news_items_from_llm), len(
                    citation_urls), num_items_to_process
            )

        logger.info(f"Processing {num_items_to_process} news items.")
        fetched_time = datetime.now(timezone.utc)

        for i in range(num_items_to_process):
            item_data = news_items_from_llm[i]
            source_url = citation_urls[i]
            logger.debug(
                f"Processing item {i}: data={item_data}, url='{source_url}'")
            try:
                published_at_str = item_data.get("published_at")
                published_at_dt = datetime.fromisoformat(published_at_str)
                if published_at_dt.tzinfo is None:
                    published_at_dt = published_at_dt.replace(
                        tzinfo=timezone.utc)

                final_news_list.append(TradeNewsCreate(
                    title=item_data.get("title"),
                    summary=item_data.get("summary"),
                    source_name=item_data.get("source_name"),
                    published_at=published_at_dt,
                    source_url=url_validator.validate_python(source_url),
                    category=item_data.get("category", "General"),
                    priority=item_data.get("priority", 1),
                    fetched_at=fetched_time,
                ))
            except Exception as e:
                logger.warning(
                    "Skipping item %d due to invalid data. Error: %s", i, e)
                continue

        if not final_news_list:
            logger.warning(
                "No news items were successfully created after processing.")

        return final_news_list

    async def create_news_via_claude(self, db: AsyncSession) -> List[TradeNewsCreate]:
        """
        TODO: 기존 뉴스 데이터 중복 제거하는 로직, 지금은 중복 제거도 잘 안 되고 조금 비효율적인 것 같음.
        TODO: 중복 제거 로직을 더 효율적으로 구현해야 함.
        """

        """
        Claude의 웹 검색 기능과 DB 중복 제거 로직을 결합하여
        신뢰성 높은 최신 무역 뉴스를 생성.
        """
        try:
            # 1. 기존 뉴스 데이터 조회 (중복 제거용)
            seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
            recent_news = await crud.trade_news.get_recent_trade_news(db, since=seven_days_ago)
            existing_urls = {str(news.source_url)
                             for news in recent_news if news.source_url}
            existing_titles = {_normalize_title(
                news.title) for news in recent_news if news.title}
            logger.info(
                f"Loaded {len(existing_urls)} existing URLs and {len(existing_titles)} titles for deduplication.")

            # 2. LLM을 통한 뉴스 생성
            now_utc = datetime.now(timezone.utc)
            three_days_ago_utc = now_utc - timedelta(days=3)
            date_format = "%Y-%m-%d"
            current_date_str = now_utc.strftime(date_format)
            start_date_str = three_days_ago_utc.strftime(date_format)

            logger.info(
                f"News generation started for period: {start_date_str} ~ {current_date_str}")

            prompt = create_trade_news_prompt(start_date_str, current_date_str)
            chain = prompt | self.llm_with_native_search

            logger.info("Initiating single-call news generation...")
            response_message = await chain.ainvoke({})
            logger.debug(
                "LLM response received.",
                extra={"response_content": response_message.content,
                       "response_metadata": response_message.response_metadata}
            )
            logger.info("News generation call completed.")

            json_string = extract_json_from_ai_message(response_message)
            if not json_string:
                logger.error("Failed to extract clean JSON from LLM response.", extra={
                             "raw_response": response_message.content})
                return []

            parser = JsonOutputParser()
            parsed_json = parser.parse(json_string)
            news_items_from_llm = parsed_json.get("news_items", [])
            logger.info(
                f"Found {len(news_items_from_llm)} news items in JSON response.")

            citation_urls = extract_citation_urls_from_ai_message(
                response_message)

            # 3. 중복 뉴스 필터링
            unique_news_items = []
            unique_citation_urls = []

            num_items_to_process = min(
                len(news_items_from_llm), len(citation_urls))

            for i in range(num_items_to_process):
                item_data = news_items_from_llm[i]
                source_url = citation_urls[i]
                title = item_data.get("title", "")

                # 1차: URL로 중복 검사
                if source_url in existing_urls:
                    logger.debug(
                        f"Skipping news item with existing URL: {source_url}")
                    continue

                # 2차: 정규화된 제목으로 중복 검사
                normalized_title = _normalize_title(title)
                if normalized_title in existing_titles:
                    logger.debug(
                        f"Skipping news item with existing title: '{title}' (normalized: '{normalized_title}')")
                    continue

                unique_news_items.append(item_data)
                unique_citation_urls.append(source_url)

            original_count = len(news_items_from_llm)
            filtered_count = len(unique_news_items)
            logger.info(
                f"Deduplication finished. Original items: {original_count}, Unique items: {filtered_count}.")

            if not unique_news_items:
                logger.info("No new unique news items found after filtering.")
                return []

            # 4. DTO 생성 및 반환
            final_news_list = self._create_news_dtos_from_response(
                unique_news_items, unique_citation_urls)

            logger.info(
                f"Successfully created {len(final_news_list)} news items.")
            return final_news_list

        except Exception as e:
            logger.error(
                "An error occurred while creating news via Claude.", exc_info=True)
            traceback.print_exc()
            return []

    async def find_updates_for_bookmark(self, bookmark: "Bookmark") -> Optional[Dict[str, Any]]:
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

        structured_llm = self.anthropic_chat_model.with_structured_output(
            UpdateInfo)
        chain = ChatPromptTemplate.from_template(prompt_text) | structured_llm
        update_info = await chain.ainvoke({})

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
