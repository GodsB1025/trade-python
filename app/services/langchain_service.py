import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import (
    Runnable,
    RunnablePassthrough,
)
from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from pydantic import BaseModel, Field

from app.core.llm_provider import llm_provider
from app.models.monitoring_models import MonitoringUpdate, SearchResult

logger = logging.getLogger(__name__)


class LLMMonitoringOutput(BaseModel):
    """LLM의 JSON 출력을 검증하기 위한 Pydantic 모델."""

    status: str = Field(
        ...,
        description="LLM이 판단한 작업 상태 ('UPDATE_FOUND' 또는 'NO_UPDATE').",
        enum=["UPDATE_FOUND", "NO_UPDATE"],
    )
    summary: Optional[str] = Field(
        None, description="업데이트가 발견된 경우 생성된 요약. 상태가 'NO_UPDATE'이면 null."
    )
    sources: List[SearchResult] = Field(
        default_factory=list, description="요약의 근거가 된 소스 목록."
    )


class LangChainService:
    """
    LangChain을 활용하여 복잡한 AI 기반 작업을 처리하는 서비스.

    주로 웹 검색, 정보 요약, 특정 형식의 데이터 추출 등
    LLM의 고급 기능이 필요한 로직을 담당함.
    """

    def __init__(self):
        """
        서비스 초기화.

        웹 검색 기능이 강화된 LLM을 `llm_provider`로부터 가져와 초기화하고,
        효율화된 단일 호출 모니터링 체인을 생성함.
        """
        # self.llm_with_search는 _create_monitoring_chain 내부에서 직접 생성되므로 제거.
        self.retry_config = llm_provider.retry_config
        self.monitoring_chain = self._create_monitoring_chain()

    def _create_monitoring_chain(self) -> Runnable:
        """
        HSCode 모니터링을 위한 단일 LLM 호출 기반의 `Runnable` 체인을 생성.

        이 체인은 다음 단계를 포함.
        1.  네이티브 `web_search` 도구와 구조화된 출력을 위한 Pydantic 도구(`LLMMonitoringOutput`)를
            하나의 목록으로 묶어 LLM에 바인딩.
        2.  LLM이 생성한 `tool_calls`에서 `PydanticToolsParser`를 사용하여 `LLMMonitoringOutput`
            인스턴스를 안전하게 추출.
        3.  추출된 Pydantic 객체를 최종 `MonitoringUpdate` 객체로 변환.
        """
        unified_prompt = self._get_unified_monitoring_prompt()

        def format_final_response(result: Dict[str, Any]) -> MonitoringUpdate:
            """체인의 최종 결과를 바탕으로 MonitoringUpdate 객체를 생성."""
            hscode = result["hscode"]
            parsed_tools: List[BaseModel] = result.get("parsed_tools", [])

            # LLM이 LLMMonitoringOutput 도구를 호출했는지 확인
            llm_output = next(
                (p for p in parsed_tools if isinstance(p, LLMMonitoringOutput)),
                None,
            )

            if not llm_output:
                return MonitoringUpdate(
                    status="ERROR",
                    hscode=hscode,
                    error_message="LLM이 구조화된 출력을 생성하지 못했습니다. (No tool call)",
                )

            if llm_output.status == "UPDATE_FOUND":
                if not llm_output.summary or not llm_output.sources:
                    return MonitoringUpdate(
                        status="ERROR",
                        hscode=hscode,
                        error_message="'UPDATE_FOUND' 상태이지만 summary 또는 sources가 누락되었습니다.",
                    )
                return MonitoringUpdate(
                    status="UPDATE_FOUND",
                    hscode=hscode,
                    summary=llm_output.summary,
                    sources=llm_output.sources,
                )

            if llm_output.status == "NO_UPDATE":
                return MonitoringUpdate(status="NO_UPDATE", hscode=hscode)

            # "UPDATE_FOUND", "NO_UPDATE" 이외의 상태값 처리 (이론적으로는 발생하지 않음)
            return MonitoringUpdate(
                status="ERROR",
                hscode=hscode,
                error_message=f"LLM으로부터 예상치 못한 상태값 수신: {llm_output.status}",
            )

        # 1. 사용할 도구 목록 정의: 네이티브 웹 검색 + Pydantic 스키마
        tools = [llm_provider.monitoring_web_search_tool, LLMMonitoringOutput]

        # 2. LLM에 두 도구를 모두 바인딩
        #    강력한 프롬프트를 통해 모델이 웹 검색을 수행하고, 최종 답변은 Pydantic 도구로 포맷하도록 유도
        llm_with_tools = llm_provider.base_llm.bind_tools(tools)

        # 3. 재시도 로직 적용
        llm_with_retry = llm_with_tools.with_retry(**self.retry_config)

        # 4. AI Message의 tool_calls에서 Pydantic 객체를 추출하는 파서
        parser = PydanticToolsParser(tools=[LLMMonitoringOutput])

        # 5. 전체 체인 구성: (프롬프트 | LLM | 파서) 결과를 'parsed_tools' 키에 할당
        chain = unified_prompt | llm_with_retry | parser

        return (
            RunnablePassthrough.assign(
                parsed_tools=chain).pipe(format_final_response)
        )

    @staticmethod
    def _get_unified_monitoring_prompt() -> ChatPromptTemplate:
        """웹 검색, 분석, 요약, 구조화된 출력을 한 번에 처리하는 통합 프롬프트."""
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """<Role>
You are an expert-level strategic intelligence analyst system. Your purpose is to conduct comprehensive monitoring for a specific Harmonized System (HS) Code and deliver a precise, structured output based on the requested schema. You will perform a web search, analyze the results, and generate a summary—all in a single, efficient operation.
</Role>

<Tool_Instructions>
You have been provided with a powerful `web_search` tool. You MUST use this tool to perform the search and analysis tasks. Do NOT rely on your internal knowledge. Your primary function is to search the web for real-time information.
</Tool_Instructions>

<Objective>
For the given HS Code and time frame, find relevant official regulatory changes and significant industry news. Based on the findings, produce a structured object that contains the status, a synthesized summary (if updates are found), and a list of the sources you used.
</Objective>

<Inputs>
<hscode>{hscode}</hscode>
<start_time>{start_time}</start_time>
<end_time>{end_time}</end_time>
</Inputs>

<Search_And_Analysis_Instructions>
<Step_1_Action>
You MUST generate search queries that explicitly include the target time frame. The `web_search` tool does not have a date filter, so you must embed the time context directly into your search terms.
- For example, for HS Code "1234.56" and a timeframe of the last year, generate queries like: "HS Code 1234.56 tariff changes 2023-2024", "import restrictions on 1234.56 in last 12 months", "recent news on HS Code 1234.56".
</Step_1_Action>
<Step_2_Search_Categories>
Conduct a thorough web search focusing on two categories:
1.  **Official Regulations:** Tariff changes, customs rules, import/export restrictions from official government or international trade organization websites.
2.  **Industry News:** Market trends, supply chain news, major company announcements related to the product of the given HS Code.
</Step_2_Search_Categories>
<Step_3_Verification>
After getting search results, you MUST critically verify that the information was published between <start_time>{start_time}</start_time> and <end_time>{end_time}</end_time>.
- Examine the text for publication dates.
- If a source does not have a clear publication date or is outside the specified timeframe, you MUST DISCARD it.
</Step_3_Verification>
<Step_4_Analysis>
- If, after verification, you find NO credible, relevant information within the timeframe, determine the status as "NO_UPDATE".
- If you find relevant information, identify the most significant updates, determine the status as "UPDATE_FOUND", and proceed to the next step. Prioritize official regulations over general news.
</Step_4_Analysis>
<Step_5_Summarization>
If updates were found (status is "UPDATE_FOUND"), synthesize the information into a coherent, fact-based summary in Korean. The summary must ONLY be based on the information you found and verified. Also, collect the source information (URL and a brief snippet of content) for every piece of information used in the summary.
</Step_5_Summarization>
</Search_And_Analysis_Instructions>

<Output_Instructions>
You MUST generate an output that strictly conforms to the provided Pydantic schema. Do not include any other text or explanation. The system will automatically handle the JSON formatting.
- If status is 'UPDATE_FOUND', you must provide a non-empty 'summary' and at least one item in 'sources'.
- If status is 'NO_UPDATE', the 'summary' should be null and 'sources' should be an empty list.
</Output_Instructions>""",
                ),
                (
                    "human",
                    """<Task>
Execute the intelligence monitoring task for the inputs below and provide the result in the specified JSON format.
<Inputs>
    <hscode>{hscode}</hscode>
    <start_time>{start_time}</start_time>
    <end_time>{end_time}</end_time>
</Inputs>
</Task>""",
                ),
            ]
        )

    async def get_hscode_update_and_sources(self, hscode: str) -> MonitoringUpdate:
        """
        주어진 HSCode에 대한 최신 정보를 웹에서 검색, 검증, 요약하여 구조화된 객체로 반환.

        효율화된 단일 호출 `monitoring_chain`을 사용하여 전체 프로세스를 실행.

        Args:
            hscode: 검색할 HSCode (예: '6109.10')

        Returns:
            MonitoringUpdate Pydantic 모델 객체.
        """
        logger.info(f"HSCode '{hscode}'에 대한 통합 모니터링 체인을 시작합니다.")
        now_utc = datetime.now(timezone.utc)
        # 검색 기간을 365일로 유지
        start_time_utc = now_utc - timedelta(days=7)

        try:
            result: MonitoringUpdate = await self.monitoring_chain.ainvoke(
                {
                    "hscode": hscode,
                    "start_time": start_time_utc.isoformat(),
                    "end_time": now_utc.isoformat(),
                }
            )
            if result.status == "UPDATE_FOUND":
                logger.info(f"HSCode '{hscode}'에 대한 최신 정보를 발견했습니다.")
            elif result.status == "NO_UPDATE":
                logger.info(f"HSCode '{hscode}'에 대한 최신 정보가 없습니다.")
            else:  # ERROR case
                logger.warning(
                    f"HSCode '{hscode}' 모니터링 중 오류 상태 반환: {result.error_message}")
            return result
        except Exception as e:
            logger.error(
                f"HSCode '{hscode}' 모니터링 체인 실행 중 예외 발생: {e}", exc_info=True
            )
            return MonitoringUpdate(
                status="ERROR", hscode=hscode, error_message=str(e)
            )
