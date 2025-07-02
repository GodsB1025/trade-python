import asyncio
import logging
from typing import AsyncGenerator, Dict, Any, List, Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone
import httpx
import re

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser, PydanticOutputParser, JsonOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableConfig
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_voyageai import VoyageAIEmbeddings
from pydantic import BaseModel, Field, HttpUrl, TypeAdapter
from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_postgres.vectorstores import PGVector
from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.messages import AIMessage, SystemMessage
from bs4 import BeautifulSoup

from app.core.config import settings
from app.models.schemas import ChatRequest, NewsCreate, NewsList
from app.services.chat_history_service import DatabaseChatMessageHistory, ChatHistoryService
from app.db import crud


logger = logging.getLogger(__name__)


class UrlItem(BaseModel):
    """Represents a single URL item from a web search."""
    url: str = Field(...,
                     description="The direct and valid URL of the news article.")


class UrlList(BaseModel):
    """A list of news article URLs."""
    urls: List[UrlItem]


class NewsItem(BaseModel):
    """Represents a single news item to be created."""
    title: str = Field(...,
                       description="A professional and clear Korean title.")
    summary: str = Field(...,
                         description="A concise, insightful summary in Korean (2-3 sentences), focusing on the direct impact on Korean businesses.")
    source_name: str = Field(...,
                             description="The name of the news source. For major global outlets, translate into Korean (e.g., '블룸버그', '로이터'). For others, use the original name.")
    published_at: Optional[datetime] = Field(
        None, description="The exact publication date and time of the article.")


class LangChainService:
    """LangChain 관련 비즈니스 로직을 처리하는 서비스 클래스"""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.anthropic_chat_model = ChatAnthropic(
            model=settings.ANTHROPIC_MODEL,
            temperature=1,

            max_tokens_to_sample=50_000,
            thinking={"type": "enabled", "budget_tokens": 20_000},
            api_key=settings.ANTHROPIC_API_KEY,
        )

        # Anthropic의 네이티브 웹 검색 도구 정의
        self.native_web_search_tool = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 10,
        }

        # 모델에 네이티브 웹 검색 기능 바인딩
        self.llm_with_native_search = self.anthropic_chat_model.bind_tools(
            tools=[self.native_web_search_tool]
        )

        self.vector_store = self._init_vector_store()

    def _init_vector_store(self) -> PGVector:
        embeddings = VoyageAIEmbeddings(
            voyage_api_key=settings.VOYAGE_API_KEY,
            model="voyage-large-2-instruct"
        )

        vectorstore = PGVector(
            embeddings=embeddings,
            collection_name="hscode_vectors",
            connection=settings.SYNC_DATABASE_URL,
            use_jsonb=True,
        )
        return vectorstore

    async def get_conversational_chain(
        self, session_id: str
    ) -> RunnableWithMessageHistory:
        retriever = self.vector_store.as_retriever(search_kwargs={"k": 5})

        ### Contextualize Question Chain ###
        contextualize_q_system_prompt = (
            "Given a chat history and the latest user question "
            "which might reference context in the chat history, "
            "formulate a standalone question which can be understood "
            "without the chat history. Do NOT answer the question, "
            "just reformulate it if needed and otherwise return it as is."
        )
        contextualize_q_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(
                    content=[
                        {
                            "type": "text",
                            "text": contextualize_q_system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                ),
                MessagesPlaceholder("chat_history"),
                ("human", "{input}"),
            ]
        )
        history_aware_retriever = create_history_aware_retriever(
            self.anthropic_chat_model, retriever, contextualize_q_prompt
        )

        ### Answer Chain ###
        qa_system_prompt = """You are an expert on HS codes, trade regulations, and import/export. 
            Your goal is to provide the most accurate and up-to-date information to users.
            If you have sufficient information from the provided context (documents) to answer the question, please use that context.
            If the context is insufficient, or if the user is asking for very recent information, news, or real-time data, use your web search capabilities.
            Answer the user's question based on the below context and your knowledge.
            Be concise and clear.

            <context>
            {context}
            </context>
            """
        qa_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(
                    content=[
                        {
                            "type": "text",
                            "text": qa_system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                ),
                MessagesPlaceholder("chat_history"),
                ("human", "{input}"),
            ]
        )

        # 네이티브 검색 기능이 바인딩된 LLM을 사용하여 문서 체인 생성
        question_answer_chain = create_stuff_documents_chain(
            self.llm_with_native_search, qa_prompt)

        rag_chain = create_retrieval_chain(
            history_aware_retriever, question_answer_chain)

        chat_history_service = ChatHistoryService(self.db_session)

        conversational_rag_chain = RunnableWithMessageHistory(
            rag_chain,
            chat_history_service.get_chat_history,
            input_messages_key="input",
            history_messages_key="chat_history",
            output_messages_key="answer",
        ).with_types(input_type=dict, output_type=dict)

        return conversational_rag_chain

    async def stream_chat_response(
        self, chat_request: ChatRequest
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """채팅 요청을 처리하고, 응답을 비동기 제너레이터로 스트리밍"""
        chain_with_history = await self.get_conversational_chain(
            chat_request.sessionId or "guest-session"
        )

        session_id = chat_request.sessionId or "guest-session"
        config = RunnableConfig(
            configurable={
                "session_id": session_id,
                "user_id": chat_request.userId,
            }
        )

        try:
            async for chunk in chain_with_history.astream(
                {"input": chat_request.question},
                config=config,
            ):
                if content := chunk.content:
                    yield {"data": content}

            yield {"event": "end", "data": "Stream ended"}

        except Exception as e:
            error_message = f"Error during stream: {e}"
            yield {"event": "error", "data": error_message}

    def _extract_json_from_ai_message(self, ai_message: AIMessage) -> str:
        """
        AIMessage에서 JSON 문자열을 지능적으로 추출.

        - content가 리스트인 경우, 마지막 텍스트 블록을 주 대상으로 삼음.
        - 마크다운 코드 블록(```json ... ```)을 자동으로 처리.
        """
        if not isinstance(ai_message, AIMessage) or not ai_message.content:
            logger.error(
                "Invalid or empty AIMessage received for JSON extraction.")
            return ""

        content = ai_message.content

        if isinstance(content, list):
            # content 리스트에서 비어있지 않은 'text' 블록만 필터링
            text_blocks = [
                block.get("text", "").strip()
                for block in content
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip()
            ]
            if not text_blocks:
                logger.error(
                    "No text content found in AIMessage response list.")
                return ""
            # 마지막 텍스트 블록을 주된 파싱 대상으로 삼음
            raw_text = text_blocks[-1]
        elif isinstance(content, str):
            raw_text = content.strip()
        else:
            logger.error(
                f"Unexpected content type in AIMessage: {type(content)}")
            return ""

        if not raw_text:
            return ""

        # 마크다운 json 코드 블록(```json ... ```)이 있는지 확인하고 내용물만 추출
        match = re.search(r"```(json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
        if match:
            # 그룹 2가 실제 JSON 콘텐츠
            return match.group(2).strip()
        else:
            # 코드 블록이 없다면, 텍스트 자체를 JSON으로 간주
            return raw_text

    async def _get_text_from_url(self, url: str) -> str:
        """Fetch and parse the main text content from a URL."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0, follow_redirects=True)
                response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            # 간단한 방법: <p> 태그의 텍스트를 모두 가져옴
            paragraphs = soup.find_all('p')
            return " ".join([p.get_text() for p in paragraphs])
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"URL {url}에서 컨텐츠를 가져오는 데 실패했습니다: {e}")
            return ""

    async def create_news_via_claude(self) -> List[NewsCreate]:
        """
        Claude의 웹 검색 기능을 사용하여 최신 무역 뉴스를 생성.
        LLM의 생성 능력과 API의 citation 메타데이터를 결합하여 신뢰성을 보장.
        """
        # 해결: LLM에서 생성한 콘텐츠와, 응답 메타데이터로 제공되는 공식 citation URL을 결합하여 신뢰성 확보.
        # 원인: LLM이 JSON에 URL을 포함하여 생성하도록 요청하는 방식은 부정확한 URL을 생성(환각)할 위험이 있음.
        # 해결책: LLM은 URL 없는 콘텐츠만 생성하고, API 응답의 'citations' 메타데이터에서 정확한 URL을 가져와 결합.

        # 1. Pydantic 모델 수정: LLM이 생성할 데이터 구조에서 URL 필드를 제거.
        class NewsItemFromLLM(BaseModel):
            title: str = Field(...,
                               description="전문적이고 명확한 한국어 제목")
            summary: str = Field(...,
                                 description="한국 기업에 미치는 영향에 초점을 맞춘 간결하고 통찰력 있는 한국어 요약 (2-3 문장)")
            source_name: str = Field(...,
                                     description="뉴스 출처의 이름. 주요 글로벌 매체는 한국어로 번역(예: 'Reuters' -> '로이터'), 그 외에는 원어명 사용")
            published_at: Optional[datetime] = Field(
                None, description="기사의 정확한 발행 일시")

        # LLM이 생성할 전체 뉴스 목록의 구조
        class NewsListFromLLM(BaseModel):
            news_items: List[NewsItemFromLLM]

        # 구조화된 출력을 위한 전용 모델 인스턴스 생성
        structured_output_llm = ChatAnthropic(
            model=settings.ANTHROPIC_MODEL,
            temperature=1,
            max_tokens_to_sample=10_000,
            thinking={"type": "enabled", "budget_tokens": 4_000},
            api_key=settings.ANTHROPIC_API_KEY,
        )
        llm_with_native_search_for_news = structured_output_llm.bind_tools(
            tools=[self.native_web_search_tool]
        )

        now_utc = datetime.now(timezone.utc)
        two_days_ago_utc = now_utc - timedelta(days=2)
        date_format = "%Y-%m-%d"
        current_date_str = now_utc.strftime(date_format)
        start_date_str = two_days_ago_utc.strftime(date_format)

        print(f"=== 뉴스 생성 시작 ===")
        print(f"검색 기간: {start_date_str} ~ {current_date_str}")

        # 2. 프롬프트 수정: LLM이 source_url을 생성하지 않고, JSON만 출력하도록 명확히 지시.
        prompt_text = (
            "You are a top-tier trade analyst. Your primary output language is Korean.\n"
            f"Today's date is {current_date_str}. Your mission is to perform these steps:\n\n"
            "**Step 1: Web Search**\n"
            "Use your `web_search` tool to find the top 10 most recent and significant news articles on global trade "
            f"published between {start_date_str} and {current_date_str}. "
            "Focus on tariffs, regulations, and supply chain disruptions relevant to South Korean SMEs.\n\n"
            "**Step 2: Analyze and Format**\n"
            "Based on the search results, create a JSON object for a list of news items. It is CRITICAL that you follow these rules:\n\n"
            "1.  **Maintain Strict Order**: The order of the news items you create MUST EXACTLY correspond to the order of the web search results you used. Do not change the order.\n"
            "2.  **Field Accuracy**: Populate the fields based *only* on the content of each specific article.\n"
            "3.  **Output Format**: Respond with ONLY the raw JSON object, nothing else. Do not wrap it in markdown, text, or any other formatting.\n\n"
            "**JSON Schema (for each item in `news_items` list):**\n"
            "   - `title`: A professional Korean title.\n"
            "   - `summary`: A concise Korean summary (2-3 sentences) of the impact on Korean businesses.\n"
            "   - `source_name`: The news source's name. Translate major outlets (e.g., 'Reuters' -> '로이터').\n"
            "   - `published_at`: The exact publication date from the article (ISO 8601 format).\n\n"
            "Your final output must be a single JSON object conforming to the `NewsListFromLLM` schema."
        )

        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=prompt_text),
            ("human", "Please proceed to find and format the top 10 global trade news stories.")
        ])

        # 3. 코드 로직 변경: `with_structured_output` 대신 `JsonOutputParser` 사용
        # `with_structured_output`은 다른 도구(web_search)의 사용을 방해하므로,
        # LLM이 텍스트로 JSON을 생성하게 한 후 파싱하는 방식으로 변경.
        # 이렇게 하면 web_search가 먼저 호출되고, 그 결과를 바탕으로 LLM이 콘텐츠를 생성하며,
        # 응답 메타데이터에 citation이 포함될 수 있게 됨.
        parser = JsonOutputParser(pydantic_object=NewsListFromLLM)
        chain = prompt | llm_with_native_search_for_news

        try:
            print("=== LLM 체인 호출 시작 ===")
            # LLM 체인을 호출하여 원시 AIMessage 응답을 받음
            raw_response_message = await chain.ainvoke({})
            print(f"=== LLM 응답 수신 완료 ===")
            print(f"응답 타입: {type(raw_response_message)}")

            # 디버깅을 위해 raw_response_message 출력
            print("=== RAW RESPONSE MESSAGE DEBUG ===")
            print(f"Type: {type(raw_response_message)}")
            print(f"Content: {raw_response_message.content}")
            print(
                f"Response Metadata: {raw_response_message.response_metadata}")
            print("=== END DEBUG ===")

            json_string = self._extract_json_from_ai_message(
                raw_response_message)
            print(f"=== 추출된 JSON 문자열 ===")
            print(f"JSON 길이: {len(json_string) if json_string else 0}")
            print(f"JSON 내용: {json_string[:500]}..." if json_string and len(
                json_string) > 500 else json_string)

            if not json_string:
                logger.error(
                    "Failed to extract JSON string from LLM response.",
                    extra={"response": raw_response_message}
                )
                return []

            # 응답 콘텐츠(JSON 문자열)를 Pydantic 객체로 파싱
            try:
                print("=== JSON 파싱 시작 ===")
                parsed_output = parser.parse(json_string)
                print(f"파싱 결과 타입: {type(parsed_output)}")

                # JsonOutputParser가 dict를 반환하는 경우 수동으로 Pydantic 객체로 변환
                if isinstance(parsed_output, dict):
                    parsed_output = NewsListFromLLM(**parsed_output)

                print(f"파싱된 뉴스 아이템 수: {len(parsed_output.news_items)}")
            except Exception as e:
                logger.error(
                    "Error parsing JSON string. Content: '%s'",
                    json_string,
                    exc_info=True
                )
                raise e  # Re-raise the exception after logging

            # content에서 웹 검색 결과와 citation 정보 추출
            web_search_urls = []
            citation_urls = []

            print("=== URL 추출 시작 ===")
            # raw_response_message.content를 순회하여 URL 정보 추출
            # TypeScript 타입 정의에 따른 올바른 파싱 로직
            for i, content_block in enumerate(raw_response_message.content):
                print(f"Content Block {i}: {type(content_block)}")
                if isinstance(content_block, dict):
                    print(f"  Content Block {i} keys: {content_block.keys()}")
                    print(
                        f"  Content Block {i} type: {content_block.get('type')}")

                    # 사용자 제공 타입 정의에 따른 URL 추출
                    # RawResponseMessageContent.content가 Content[] 배열인 경우
                    if content_block.get("content") and isinstance(content_block.get("content"), list):
                        print(
                            f"  Found nested content array with {len(content_block.get('content', []))} items")
                        for j, content_item in enumerate(content_block.get("content", [])):
                            if isinstance(content_item, dict):
                                print(
                                    f"    Content Item {j}: type={content_item.get('type')}, url={content_item.get('url')}")
                                # Content 타입의 객체에서 직접 URL 추출
                                if content_item.get("type") == "web_search_result" and content_item.get("url"):
                                    web_search_urls.append(
                                        content_item.get("url"))
                                    print(
                                        f"    ✓ Added web search URL: {content_item.get('url')}")

                    # 웹 검색 도구 결과에서 URL 추출 (tool_result 타입)
                    elif content_block.get("type") == "tool_result":
                        print(f"  Found tool_result block")
                        # tool_result 블록에서 실제 검색 결과 추출
                        tool_content = content_block.get("content", [])
                        if isinstance(tool_content, list):
                            print(
                                f"    Tool content is list with {len(tool_content)} items")
                            for k, result_item in enumerate(tool_content):
                                if isinstance(result_item, dict) and result_item.get("type") == "web_search_result":
                                    url = result_item.get("url")
                                    print(f"      Result Item {k}: url={url}")
                                    if url:
                                        web_search_urls.append(url)
                                        print(
                                            f"      ✓ Added web search URL from tool result: {url}")
                        elif isinstance(tool_content, str):
                            # 문자열 형태의 응답인 경우 - 실제 구조 확인 필요
                            print(
                                f"    Tool result content is string: {tool_content[:200]}...")

                    # 기존 방식도 유지 (하위 호환성)
                    elif content_block.get("type") == "web_search_tool_result":
                        print(f"  Found web_search_tool_result block")
                        search_content = content_block.get("content", [])
                        for search_result in search_content:
                            if isinstance(search_result, dict) and search_result.get("type") == "web_search_result":
                                url = search_result.get("url")
                                if url:
                                    web_search_urls.append(url)
                                    print(
                                        f"    ✓ Added web search URL (legacy): {url}")

                    # text 블록의 citations에서 URL 추출
                    elif content_block.get("type") == "text":
                        citations = content_block.get("citations", [])
                        print(
                            f"  Found text block with {len(citations)} citations")
                        for citation in citations:
                            if isinstance(citation, dict) and citation.get("type") == "web_search_result_location":
                                url = citation.get("url")
                                if url:
                                    citation_urls.append(url)
                                    print(f"    ✓ Added citation URL: {url}")

            print("=== URL DEBUG ===")
            print(f"Web search URLs: {web_search_urls}")
            print(f"Citation URLs: {citation_urls}")
            print("=== END URL DEBUG ===")

            news_items_from_llm = parsed_output.news_items

            # 사용 가능한 URL 목록 (citation URLs 우선, 없으면 web search URLs 사용)
            available_urls = citation_urls if citation_urls else web_search_urls

            print(f"=== 최종 URL 매칭 ===")
            print(f"뉴스 아이템 수: {len(news_items_from_llm)}")
            print(f"사용 가능한 URL 수: {len(available_urls)}")
            print(f"사용할 URL 목록: {available_urls}")

            # LLM이 생성한 뉴스 아이템과 URL을 결합
            final_news_list: List[NewsCreate] = []
            url_validator = TypeAdapter(HttpUrl)

            # 뉴스 아이템과 URL의 개수가 다를 경우에 대비하여 둘 중 적은 수를 기준으로 순회
            num_items_to_process = min(
                len(news_items_from_llm), len(available_urls))
            if len(news_items_from_llm) != len(available_urls):
                logger.warning(
                    "Mismatch between number of news items (%d) and available URLs (%d). Processing %d items.",
                    len(news_items_from_llm),
                    len(available_urls),
                    num_items_to_process
                )

            print(f"=== 뉴스 아이템 처리 시작 ===")
            print(f"처리할 아이템 수: {num_items_to_process}")

            for i in range(num_items_to_process):
                item = news_items_from_llm[i]
                source_url = available_urls[i]

                print(f"\n--- 아이템 {i+1} 처리 ---")
                print(f"제목: {item.title}")
                print(f"URL: {source_url}")

                if not source_url:
                    logger.warning(
                        "Skipping item %d due to missing URL.", i)
                    print(f"  ❌ URL이 없어서 건너뜀")
                    continue

                try:
                    # URL의 유효성을 검사하고 최종 객체를 생성
                    url_validator.validate_python(source_url)
                    news_data = item.model_dump()
                    news_data['source_url'] = source_url
                    final_news_list.append(NewsCreate(**news_data))
                    print(f"  ✓ 뉴스 아이템 생성 성공")
                except Exception as e:
                    # 유효성 검사 실패 시 해당 항목은 무시하고 다음으로 진행
                    logger.warning(
                        "Skipping item %d due to invalid URL '%s'. Error: %s",
                        i,
                        source_url,
                        e,
                    )
                    print(f"  ❌ URL 유효성 검사 실패: {e}")
                    continue

            print(f"\n=== 최종 결과 ===")
            print(f"생성된 뉴스 아이템 수: {len(final_news_list)}")
            for i, news in enumerate(final_news_list):
                print(f"{i+1}. {news.title} - {news.source_url}")

            return final_news_list

        except Exception as e:
            logger.error(
                "An error occurred while creating news via Claude.",
                exc_info=True
            )
            print(f"=== 오류 발생 ===")
            print(f"오류 내용: {str(e)}")
            import traceback
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
            "feed_type": "TRADE_NEWS",  # 예시, 실제로는 더 동적으로 결정해야 할 수 있음
            "target_type": bookmark.type.value,
            "target_value": bookmark.target_value,
            "title": update_info.title,
            "content": update_info.content,
            "source_url": update_info.source_url,
            "importance": update_info.importance or "MEDIUM",
        }
