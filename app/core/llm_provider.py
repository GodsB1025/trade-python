import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_voyageai import VoyageAIEmbeddings
from langchain_postgres.vectorstores import PGVector

from app.core.config import settings


class LLMProvider:
    """
    LLM 관련 핵심 컴포넌트(LLM, 임베딩, 벡터 저장소)의 생성 및 설정을 중앙에서 관리.
    이 클래스의 인스턴스는 애플리케이션의 여러 서비스에서 공유되어 일관된 LLM 구성을 보장함.
    """

    def __init__(self):
        # 0. Anthropic API 공유 속도 제한기 생성
        # Anthropic API의 분당 토큰 제한(TPM)을 고려하여 모든 모델의 요청 속도를 제어.
        # 분당 출력 토큰 제한(16,000)을 기반으로 초당 요청 수를 계산함.
        # - 북마크 1개당 최대 출력 토큰: ~2,300 (검색 결과 2,000 + 요약 300)
        # - 분당 처리 가능 북마크: 16,000 / 2,300 ~= 6.9개. 안전 마진 적용 -> 6개/분
        # - 분당 요청(RPM): 6개 북마크/분 * 2회 호출/북마크 = 12 RPM
        # - 초당 요청(RPS): 12 RPM / 60초 = 0.2 RPS
        anthropic_rate_limiter = InMemoryRateLimiter(
            requests_per_second=0.2, check_every_n_seconds=0.1
        )

        # 1. 앤트로픽 챗 모델 초기화
        base_llm = ChatAnthropic(
            model=settings.ANTHROPIC_MODEL,
            temperature=1,
            max_tokens=12000,
            api_key=settings.ANTHROPIC_API_KEY,
            default_headers={
                "anthropic-beta": "extended-cache-ttl-2025-04-11",
                "anthropic-version": "2023-06-01"
            },
            thinking={"type": "enabled", "budget_tokens": 4_000},
            rate_limiter=anthropic_rate_limiter,  # 모든 모델에 공유 속도 제한기 적용
        )

        # 2. Anthropic 네이티브 웹 검색 도구 정의
        self.basic_web_search_tool = {
            "type": "web_search_20250305",
            "name": "web_search",
            "cache_control": {"type": "ephemeral"},
            "max_uses": 5,
        }

        # 'news'용 웹 검색 도구 (특정 도메인 제한 기능 포함)
        self.news_web_search_tool = {
            **self.basic_web_search_tool,
            # "allowed_domains": [
            #     # 프롬프트 수정 전 까지는 나머지 사이트들 전부 주석처리 ( 최신 내용을 못 가져옴 )
            #     # 할 일.md 파일 참조.
            #
            #     # 글로벌 사이트들
            #     "www.cnbc.com/shipping/",
            #     "www.supplychaindive.com/",
            #     "www.supplychainbrain.com/",
            #     "supplychaindigital.com/",
            #     "www.globaltrademag.com/",
            #     "www.freightwaves.com/",
            #     "www.maritime-executive.com/",
            #     "aircargoworld.com/",
            #     "theloadstar.com/",
            #     "finance.yahoo.com/news/",
            #     "indiashippingnews.com/",
            #     "www.ajot.com/",
            #     "www.scdigest.com/",
            #     "www.inboundlogistics.com/",
            #     "www.railjournal.com/",
            #     "www.transportjournal.com/",
            #     "landline.media/",
            #     "www.aircargoweek.com/",
            #     "www.automotivelogistics.media/",
            #     "breakbulk.com/",
            #     "gcaptain.com/",
            #     "www.marinelink.com/",
            #     "splash247.com/",
            #
            #     # 한국 사이트들
            #     "dream.kotra.or.kr/kotranews/index.do",
            #     "www.kita.net/board/totalTradeNews/totalTradeNewsList.do",
            #     "www.kita.net/mberJobSport/shippers/board/list.do",
            #     "www.klnews.co.kr",
            #     "www.kcnews.org/",
            #     "www.maritimepress.co.kr",
            #     "www.weeklytrade.co.kr/",
            #     "www.shippingnewsnet.com",
            #     "www.cargotimes.net/"
            # ],
        }

        # 'monitoring'용 웹 검색 도구 (기본 설정 사용)
        self.monitoring_web_search_tool = self.basic_web_search_tool

        # 3. 모델에 네이티브 웹 검색 기능 바인딩 -> 서비스 레이어에서 책임지도록 변경
        # 서비스 레이어에서 각 용도에 맞게 네이티브 도구(웹 검색)와 Pydantic 도구(구조화된 출력)를
        # 함께 바인딩해야 하므로, 프로바이더는 순수한 모델과 도구만 제공
        self.base_llm = base_llm
        self.news_llm_with_native_search = base_llm.bind_tools(
            tools=[self.news_web_search_tool]
        )

        # 4. 재시도 로직 정의
        # 529 과부하 에러와 같은 특정 오류에 대해 지수 백오프를 사용한 재시도를 적용.
        # 모든 모델에 일관되게 적용하여 안정성 확보.
        self.retry_config = {
            "stop_after_attempt": 10,
            "wait_exponential_jitter": True,  # 지수적으로 대기 시간 증가 (jitter 포함)
            "retry_if_exception_type": (anthropic.InternalServerError, anthropic.RateLimitError),
        }

        # 5. 용도별 LLM 모델 최종 생성
        # 모든 모델에 재시도 로직을 적용하여 안정성 강화
        self.news_chat_model = self.base_llm.with_retry(**self.retry_config)
        self.monitoring_chat_model = self.base_llm.with_retry(
            **self.retry_config)

        self.news_llm_with_native_search = self.news_llm_with_native_search.with_retry(
            **self.retry_config
        )

        # monitoring_llm_with_native_search는 서비스 레이어에서 직접 생성하도록 책임을 위임함.
        # self.monitoring_llm_with_native_search = monitoring_model_with_tools_bound

        # 6. Voyage AI 임베딩 모델 초기화
        self.embedding_model = VoyageAIEmbeddings(
            voyage_api_key=settings.VOYAGE_API_KEY,
            model="voyage-3-large"
        )

        # 7. PGVector 벡터 저장소 초기화
        self.vector_store = PGVector(
            embeddings=self.embedding_model,
            collection_name="hscode_vectors",
            connection=settings.SYNC_DATABASE_URL,
            use_jsonb=True,
        )


# 애플리케이션 전체에서 공유될 단일 LLMProvider 인스턴스
llm_provider = LLMProvider()
