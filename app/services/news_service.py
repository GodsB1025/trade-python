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

from app.core.config import settings
from app.core.llm_provider import llm_provider
from app.models.schemas import NewsCreate

logger = logging.getLogger(__name__)


class NewsService:
    """
    LLM의 웹 검색 기능을 활용하여 최신 무역 뉴스를 생성하고,
    북마크 관련 업데이트를 찾는 비즈니스 로직을 처리.
    """

    def __init__(self):
        # llm_provider에서 웹 검색 기능이 바인딩된 모델을 가져옴
        self.llm_with_native_search = llm_provider.llm_with_native_search
        self.native_web_search_tool = llm_provider.native_web_search_tool
        self.anthropic_chat_model = llm_provider.anthropic_chat_model

    def _extract_json_from_ai_message(self, ai_message: AIMessage) -> str:
        """
        AIMessage에서 JSON 문자열을 지능적으로 추출.

        - content가 리스트인 경우, 마지막 텍스트 블록을 주 대상으로 삼음.
        - 마크다운 코드 블록(```json ... ```)을 자동으로 처리.
        - LLM이 JSON 앞에 추가적인 텍스트를 포함하는 경우도 처리.
        """
        if not isinstance(ai_message, AIMessage) or not ai_message.content:
            logger.error(
                "Invalid or empty AIMessage received for JSON extraction.")
            return ""

        content = ai_message.content

        if isinstance(content, list):
            text_blocks = [
                block.get("text", "").strip()
                for block in content
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip()
            ]
            if not text_blocks:
                logger.error(
                    "No text content found in AIMessage response list.")
                return ""
            raw_text = text_blocks[-1]
        elif isinstance(content, str):
            raw_text = content.strip()
        else:
            logger.error(
                f"Unexpected content type in AIMessage: {type(content)}")
            return ""

        if not raw_text:
            return ""

        # 1. 마크다운 코드 블록(```json ... ```)에서 JSON 추출 시도
        match = re.search(
            r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 2. 마크다운이 없는 경우, 문자열에서 첫 '{'와 마지막 '}' 사이의 내용을 추출
        # LLM이 JSON 앞뒤에 부가적인 설명을 붙이는 경우에 대응
        match = re.search(r"({[\s\S]*})", raw_text, re.DOTALL)
        if match:
            return match.group(1).strip()

        logger.warning(
            "Failed to extract JSON from AIMessage content. Raw text: %s", raw_text)
        return ""

    async def _get_text_from_url(self, url: str) -> str:
        """URL에서 주요 텍스트 콘텐츠를 가져와 파싱."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0, follow_redirects=True)
                response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            paragraphs = soup.find_all('p')
            return " ".join([p.get_text() for p in paragraphs])
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning(f"Failed to fetch content from URL {url}: {e}")
            return ""

    async def create_news_via_claude(self) -> List[NewsCreate]:
        """
        Claude의 웹 검색 기능과 API의 citation 메타데이터를 결합하여
        신뢰성 높은 최신 무역 뉴스를 생성.

        LLM은 URL 없는 콘텐츠만 생성하고, API 응답의 'citations' 메타데이터와
        'content' 블록에서 정확한 URL을 가져와 결합하여 환각(hallucination)을 방지.
        """
        now_utc = datetime.now(timezone.utc)
        two_days_ago_utc = now_utc - timedelta(days=3)
        date_format = "%Y-%m-%d"
        current_date_str = now_utc.strftime(date_format)
        start_date_str = two_days_ago_utc.strftime(date_format)

        logger.info(
            f"News generation started for period: {start_date_str} ~ {current_date_str}")

        # 프롬프트 수정: LLM이 source_url을 생성하지 않고, JSON만 출력하도록 명확히 지시.
        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content="You are a top-tier trade analyst. Your primary output language is Korean.\n"
                          f"Today's date is {current_date_str}. Your mission is to perform these steps in order within a single turn:\n\n"
                          "**Step 1: Web Search**\n"
                          "First, use your `web_search` tool to find recent and significant news articles on global trade "
                          f"only published between {start_date_str} and {current_date_str}. "
                          "Focus on tariffs, regulations, and supply chain disruptions relevant to South Korean SMEs.\n\n"
                          "**Step 2: Analyze and Format to JSON**\n"
                          "After you get the search results, you MUST analyze them and create a single, raw JSON object. Do not output any other text, just the JSON. "
                          "It is CRITICAL that you follow these rules:\n"
                          "1.  **Maintain Strict Order**: The order of the news items you create MUST EXACTLY correspond to the order of the web search results. Do not change the order.\n"
                          "2.  **Field Accuracy**: Populate the fields based *only* on the content of each specific article. DO NOT generate URLs.\n"
                          "3.  **JSON Schema**: The final output MUST be a single raw JSON object (not a string, not wrapped in markdown). The schema should be:\n"
                          "    `{{\"news_items\": [{{\"title\": \"...\", \"summary\": \"...\", \"source_name\": \"...\", \"published_at\": \"...\"}}]}}`\n"
                          "    - `title`: A professional Korean title.\n"
                          "    - `summary`: A concise Korean summary (2-3 sentences) of the impact on Korean businesses.\n"
                          "    - `source_name`: The news source's name. Translate major outlets (e.g., 'Reuters' -> '로이터').\n"
                          "    - `published_at`: The exact publication date from the article (ISO 8601 format).\n\n"
                          "Now, proceed with the web search and then generate the final JSON object.", additional_kwargs={"cache-control": {"type": "ephemeral"}}),
            HumanMessage(
                content="Please find the latest trade news and format it as a JSON object.")
        ])

        chain = prompt | self.llm_with_native_search

        try:
            logger.info("Initiating single-call news generation...")
            response_message = await chain.ainvoke({})
            logger.debug(
                "LLM response received.",
                extra={"response_content": response_message.content,
                       "response_metadata": response_message.response_metadata}
            )
            logger.info("News generation call completed.")

            json_string = self._extract_json_from_ai_message(response_message)
            logger.debug(
                f"Extracted clean JSON string: '{json_string}'")

            if not json_string:
                logger.error(
                    "Failed to extract clean JSON from LLM response.", extra={"raw_response": response_message.content})
                return []

            parser = JsonOutputParser()
            parsed_json = parser.parse(json_string)
            logger.debug(f"Parsed JSON object: {parsed_json}")

            news_items_from_llm = parsed_json.get("news_items", [])
            logger.info(
                f"Found {len(news_items_from_llm)} news items in JSON response.")

            # 견고한 URL 추출 로직: content의 모든 블록과 metadata를 모두 확인
            citation_urls = []
            if hasattr(response_message, 'content') and isinstance(response_message.content, list):
                for block in response_message.content:
                    if not isinstance(block, dict):
                        continue

                    # 1. tool_result 블록에서 URL 추출 (API 응답에 맞춰 "web_search_tool_result"로 수정)
                    if block.get("type") == "web_search_tool_result" and isinstance(block.get("content"), list):
                        for result_item in block.get("content", []):
                            if isinstance(result_item, dict) and result_item.get("type") == "web_search_result":
                                url = result_item.get("url")
                                if url and url not in citation_urls:
                                    citation_urls.append(url)
                                    logger.debug(
                                        f"Found URL in tool_result: {url}")

                    # 2. text 블록의 citations에서 URL 추출
                    elif block.get("type") == "text" and isinstance(block.get("citations"), list):
                        for citation in block.get("citations", []):
                            source = citation.get('source', {})
                            if isinstance(source, dict) and source.get('type') == 'web_search_result':
                                url = source.get('url')
                                if url and url not in citation_urls:
                                    citation_urls.append(url)
                                    logger.debug(
                                        f"Found URL in text block citation: {url}")

            # 3. response_metadata에서도 추가로 확인 (하위 호환)
            if hasattr(response_message, 'response_metadata') and 'citations' in response_message.response_metadata:
                for citation in response_message.response_metadata['citations']:
                    source = citation.get('source', {})
                    if isinstance(source, dict) and source.get('type') == 'web_search_result':
                        url = source.get('url')
                        if url and url not in citation_urls:
                            citation_urls.append(url)
                            logger.debug(
                                f"Found URL in response_metadata: {url}")

            logger.info(
                f"Found {len(citation_urls)} unique citation URLs in total.")

            final_news_list: List[NewsCreate] = []
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
            for i in range(num_items_to_process):
                item_data = news_items_from_llm[i]
                source_url = citation_urls[i]
                logger.debug(
                    f"Processing item {i}: data={item_data}, url='{source_url}'")
                try:
                    url_validator.validate_python(source_url)
                    final_news_list.append(NewsCreate(
                        title=item_data.get("title"),
                        summary=item_data.get("summary"),
                        source_name=item_data.get("source_name"),
                        published_at=item_data.get("published_at"),
                        source_url=source_url
                    ))
                except Exception as e:
                    logger.warning(
                        "Skipping item %d due to invalid data or URL '%s'. Error: %s", i, source_url, e)
                    continue

            if not final_news_list:
                logger.warning(
                    "No news items were successfully created after processing.")

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
