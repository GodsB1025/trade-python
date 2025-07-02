from langchain_anthropic import ChatAnthropic
from langchain_voyageai import VoyageAIEmbeddings
from langchain_postgres.vectorstores import PGVector

from app.core.config import settings


class LLMProvider:
    """
    LLM 관련 핵심 컴포넌트(LLM, 임베딩, 벡터 저장소)의 생성 및 설정을 중앙에서 관리.
    이 클래스의 인스턴스는 애플리케이션의 여러 서비스에서 공유되어 일관된 LLM 구성을 보장.
    """

    def __init__(self):
        # 1. 앤트로픽 챗 모델 초기화
        self.anthropic_chat_model = ChatAnthropic(
            model=settings.ANTHROPIC_MODEL,
            temperature=1,
            max_tokens=100_000,
            api_key=settings.ANTHROPIC_API_KEY,
            default_headers={
                "anthropic-beta": "interleaved-thinking-2025-05-14,extended-cache-ttl-2025-04-11",
                "anthropic-version": "2023-06-01"
            },
            thinking={"type": "enabled", "budget_tokens": 40_000},
        )

        # 2. Anthropic의 네이티브 웹 검색 도구 정의
        self.native_web_search_tool = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 10,

            "allowed_domains": [
                # 글로벌 사이트들
                "www.cnbc.com/shipping/",
                "www.supplychaindive.com/",
                "www.supplychainbrain.com/",
                "supplychaindigital.com/",
                "www.globaltrademag.com/",
                "www.freightwaves.com/",
                "www.maritime-executive.com/",
                "aircargoworld.com/",
                "theloadstar.com/",
                "finance.yahoo.com/news/",
                "indiashippingnews.com/",
                "www.ajot.com/",
                "www.scdigest.com/",
                "www.inboundlogistics.com/",
                "www.railjournal.com/",
                "www.transportjournal.com/",
                "landline.media/",
                "www.aircargoweek.com/",
                "www.automotivelogistics.media/",
                "breakbulk.com/",
                "gcaptain.com/",
                "www.marinelink.com/",
                "splash247.com/",

                # 한국 사이트들
                "dream.kotra.or.kr/kotranews/index.do",
                "www.kita.net/board/totalTradeNews/totalTradeNewsList.do",
                "www.kita.net/mberJobSport/shippers/board/list.do",
                "www.klnews.co.kr",
                "www.kcnews.org/",
                "www.maritimepress.co.kr",
                "www.weeklytrade.co.kr/",
                "www.shippingnewsnet.com",
                "www.cargotimes.net/"
            ],
        }

        # 3. 모델에 네이티브 웹 검색 기능 바인딩
        self.llm_with_native_search = self.anthropic_chat_model.bind_tools(
            tools=[self.native_web_search_tool]
        )

        # 4. Voyage AI 임베딩 모델 초기화
        self.embeddings = VoyageAIEmbeddings(
            voyage_api_key=settings.VOYAGE_API_KEY,
            model="voyage-large-2-instruct"
        )

        # 5. PGVector 벡터 저장소 초기화
        self.vector_store = PGVector(
            embeddings=self.embeddings,
            collection_name="hscode_vectors",
            connection=settings.SYNC_DATABASE_URL,
            use_jsonb=True,
        )


# 애플리케이션 전체에서 공유될 단일 LLMProvider 인스턴스
llm_provider = LLMProvider()
