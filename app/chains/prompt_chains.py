from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field


# 뉴스 생성을 위한 모델 정의
# 이 모델은 LLM이 생성할 JSON의 구조와 일치해야 함
class NewsItem(BaseModel):
    title: str = Field(description="기사 제목")
    summary: str = Field(description="기사 요약")
    source_name: str = Field(
        description="출처. 'Reuters' -> '로이터'와 같이 주요 외신은 번역")
    published_at: str = Field(description="기사 발행일 (ISO 8601 형식)")
    category: str = Field(
        description="카테고리: 'Tariff', 'Regulation', 'SupplyChain', 'TradeAgreement', 'Geopolitics', 'Technology', 'Environment', 'General' 중 하나"
    )
    priority: int = Field(description="중요도 (1-3)")


class NewsList(BaseModel):
    news_items: list[NewsItem]


def create_trade_news_prompt(start_date: str, current_date: str) -> ChatPromptTemplate:
    """
    최신 무역 뉴스를 생성하기 위한 ChatPromptTemplate을 생성.

    Args:
        start_date (str): 뉴스 검색 시작일 (YYYY-MM-DD 형식).
        current_date (str): 현재 날짜 (YYYY-MM-DD 형식).

    Returns:
        ChatPromptTemplate: 뉴스 생성용 프롬프트 템플릿.
    """
    return ChatPromptTemplate.from_messages([
        SystemMessage(
            content="You are a top-tier trade analyst. Your primary output language is Korean.\n"
                    f"Today's date is {current_date}. Your mission is to perform these steps in order within a single turn:\n\n"
                    "**Step 1: Web Search**\n"
                    "First, use your `web_search` tool to find recent and significant news articles on global trade "
                    f"only published between {start_date} and {current_date}. "
                    "Focus on tariffs, regulations, and supply chain disruptions relevant to South Korean SMEs.\n\n"
                    "**Step 2: Analyze and Format to JSON**\n"
                    "After you get the search results, you MUST analyze them and create a single, raw JSON object. Do not output any other text, just the JSON. "
                    "It is CRITICAL that you follow these rules:\n"
                    "1.  **Maintain Strict Order**: The order of the news items you create MUST EXACTLY correspond to the order of the web search results. Do not change the order.\n"
                    "2.  **Field Accuracy**: Populate the fields based *only* on the content of each specific article. DO NOT generate URLs.\n"
                    "3.  **JSON Schema**: The final output MUST be a single raw JSON object. The schema should be:\n"
                    "    `{{\"news_items\": [{{\"title\": \"...\", \"summary\": \"...\", \"source_name\": \"...\", \"published_at\": \"...\", \"category\": \"...\", \"priority\": ...}}]}}`\n"
                    "    - `title`: A professional Korean title.\n"
                    "    - `summary`: A concise Korean summary (2-3 sentences) of the impact on Korean businesses.\n"
                    "    - `source_name`: The news source's name. Translate major outlets (e.g., 'Reuters' -> '로이터').\n"
                    "    - `published_at`: The exact publication date from the article (ISO 8601 format).\n"
                    "    - `category`: Classify the article into one of these categories: 'Tariff', 'Regulation', 'SupplyChain', 'TradeAgreement', 'Geopolitics', 'Technology', 'Environment', 'General'.\n"
                    "    - `priority`: Assign an integer priority: 3 for critical impact, 2 for moderate, 1 for informational.\n\n"
                    "Now, proceed with the web search and then generate the final JSON object.",
            additional_kwargs={"cache-control": {"type": "ephemeral"}}
        ),
        HumanMessage(
            content="Please find the latest trade news and format it as a JSON object.")
    ])


def create_summary_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([
        ("system",
         "You are a helpful assistant that summarizes the provided text in Korean. Please summarize the key points concisely."),
        ("human", "{text}")
    ])
