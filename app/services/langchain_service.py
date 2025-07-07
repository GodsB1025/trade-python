import logging
import re  # re 모듈 임포트
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Literal

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import (
    Runnable,
    RunnablePassthrough,
    chain as as_runnable,
)
from langchain_core.output_parsers import StrOutputParser
from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field
from langchain_core.documents import Document
from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr

from app.core.llm_provider import llm_provider
from app.models.monitoring_models import MonitoringUpdate, SearchResult
from app.vector_stores.hscode_retriever import get_hscode_retriever
from app.core.config import settings


logger = logging.getLogger(__name__)


class LLMMonitoringOutput(BaseModel):
    """LLM의 JSON 출력을 검증하기 위한 Pydantic 모델."""

    status: Literal["UPDATE_FOUND", "NO_UPDATE"] = Field(
        ...,
        description="LLM이 판단한 작업 상태 ('UPDATE_FOUND' 또는 'NO_UPDATE').",
    )
    summary: Optional[str] = Field(
        None,
        description="업데이트가 발견된 경우 생성된 요약. 상태가 'NO_UPDATE'이면 null.",
    )
    sources: List[SearchResult] = Field(
        default_factory=list, description="요약의 근거가 된 소스 목록."
    )


class QuestionClassification(BaseModel):
    """질문 분류 결과를 나타내는 모델"""

    is_trade_related: bool = Field(description="무역 관련 질문 여부")
    confidence: float = Field(description="분류 신뢰도 (0.0-1.0)")
    category: str = Field(
        description="질문 카테고리: 'hscode', 'trade_general', 'cargo_tracking', 'non_trade'"
    )
    reasoning: str = Field(description="분류 근거")


class LLMService:
    """
    LangChain을 활용하여 복잡한 AI 기반 작업을 처리하는 서비스.
    - HSCode 모니터링 체인
    - 일반 채팅 및 RAG 체인
    """

    def __init__(self):
        self.retry_config = llm_provider.retry_config
        self.monitoring_chain = self._create_monitoring_chain()
        self.chat_chain = self._create_chat_chain()
        # Claude 3.5 Haiku 모델 초기화
        self.question_classifier = ChatAnthropic(
            model_name="claude-3-5-haiku-latest",
            api_key=SecretStr(settings.ANTHROPIC_API_KEY),
            temperature=0.1,
            streaming=True,
            max_tokens_to_sample=300,
            timeout=300.0,
            stop=None,
        )

    async def _classify_question_with_llm(
        self, question: str
    ) -> QuestionClassification:
        """
        Claude 3.5 Haiku 모델을 사용하여 질문이 무역 관련인지 지능적으로 판단

        Args:
            question: 분류할 질문

        Returns:
            QuestionClassification: 분류 결과
        """
        try:
            classification_prompt = f"""당신은 무역 및 수출입 전문 분류 AI입니다. 주어진 질문을 정확히 분류하세요.

질문: "{question}"

다음 기준으로 분류하세요:

**무역 관련 질문 기준:**
- 수출입, 무역, 통관, 관세, 세율 관련
- HSCode, 품목분류, 원산지, FTA 관련  
- 수출입 규제, 허가, 검역 관련
- 무역 실무, 무역 계약, 무역 금융 관련
- 국가별 무역 정책, 무역 협정 관련
- 물류, 운송, 통관 절차 관련
- 무역 분쟁, 덤핑, 세이프가드 관련

**카테고리 정의:**
- "hscode": HSCode 번호가 포함된 질문 (예: 8471.30, 6109.10 등)
- "trade_general": 무역 관련이지만 HSCode가 없는 일반 질문
- "cargo_tracking": 화물통관 조회 관련 질문 (화물번호, 통관조회, 배송추적 등)
- "non_trade": 무역과 무관한 질문 (일반상식, 개인조언, 오락, 요리, 여행 등)

**신뢰도 기준:**
- 0.9-1.0: 매우 확실 (명확한 무역 용어 포함)
- 0.7-0.9: 확실 (무역 관련 맥락 명확)
- 0.5-0.7: 보통 (무역 관련 가능성 있음)
- 0.3-0.5: 낮음 (모호한 경우)
- 0.0-0.3: 매우 낮음 (명확히 무역 외 질문)

아래 JSON 형식으로 정확히 응답하세요:
{{
    "is_trade_related": true/false,
    "confidence": 0.0-1.0,
    "category": "hscode/trade_general/non_trade",
    "reasoning": "분류 근거 설명"
}}"""

            # Claude 3.5 Haiku 모델 호출 - langchain 사용
            from langchain_core.messages import HumanMessage

            response = await self.question_classifier.ainvoke(
                [HumanMessage(content=classification_prompt)]
            )

            # 응답 파싱 (타입 안전)
            from app.utils.llm_response_parser import (
                extract_text_from_anthropic_response,
            )

            response_text = extract_text_from_anthropic_response(response).strip()

            # JSON 파싱 시도
            import json

            try:
                result_dict = json.loads(response_text)
                return QuestionClassification(
                    is_trade_related=result_dict.get("is_trade_related", False),
                    confidence=result_dict.get("confidence", 0.0),
                    category=result_dict.get("category", "non_trade"),
                    reasoning=result_dict.get("reasoning", "분류 실패"),
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"LLM 분류 응답 파싱 실패: {e}, 응답: {response_text}")
                # 폴백: 기본 키워드 기반 분류
                return self._fallback_classification(question)

        except Exception as e:
            logger.error(f"LLM 기반 질문 분류 중 오류 발생: {e}")
            # 폴백: 기본 키워드 기반 분류
            return self._fallback_classification(question)

    def _fallback_classification(self, question: str) -> QuestionClassification:
        """LLM 분류 실패 시 폴백 분류 로직"""
        question_lower = question.lower()

        # HSCode 패턴 확인
        hscode_pattern = r"\b(\d{4}\.\d{2}|\d{6}|\d{10})\b"
        if re.search(hscode_pattern, question):
            return QuestionClassification(
                is_trade_related=True,
                confidence=0.95,
                category="hscode",
                reasoning="HSCode 패턴 감지됨",
            )

        # 화물통관 조회 키워드 확인 (무역 키워드보다 먼저 체크)
        cargo_tracking_keywords = [
            "화물",
            "통관조회",
            "조회",
            "추적",
            "운송",
            "배송",
            "컨테이너",
            "선적",
            "화물번호",
            "추적번호",
            "운송장번호",
            "선적번호",
            "bl",
            "awb",
            "tracking",
            "cargo",
            "shipment",
            "container",
        ]

        for keyword in cargo_tracking_keywords:
            if keyword in question_lower:
                return QuestionClassification(
                    is_trade_related=True,
                    confidence=0.8,
                    category="cargo_tracking",
                    reasoning=f"화물통관 조회 키워드 '{keyword}' 감지됨",
                )

        # 기본 무역 키워드 확인
        basic_trade_keywords = [
            "무역",
            "수출",
            "수입",
            "관세",
            "통관",
            "원산지",
            "fta",
            "trade",
            "export",
            "import",
            "tariff",
            "customs",
        ]

        for keyword in basic_trade_keywords:
            if keyword in question_lower:
                return QuestionClassification(
                    is_trade_related=True,
                    confidence=0.7,
                    category="trade_general",
                    reasoning=f"무역 키워드 '{keyword}' 감지됨",
                )

        return QuestionClassification(
            is_trade_related=False,
            confidence=0.8,
            category="non_trade",
            reasoning="무역 관련 키워드 미발견",
        )

    # --- 채팅 체인 생성 로직 ---

    def _create_chat_chain(self) -> Runnable:
        """
        LLM 기반 질문 분류와 RAG, 웹 검색 폴백, 일반 대화를 처리하는 채팅 체인을 생성.
        Claude 3.5 Haiku 모델을 사용한 지능형 질문 분류 적용.
        """
        # 1. 체인 구성 요소들
        retriever = get_hscode_retriever()
        output_parser = StrOutputParser()
        llm = llm_provider.news_chat_model
        llm_with_web_search = llm_provider.news_llm_with_native_search

        # 2. 프롬프트 템플릿들
        # 무역 전문가 프롬프트
        general_chat_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "당신은 대한민국의 무역 및 수출입 전문가입니다. 다음 지침을 엄격히 준수하세요:\n\n"
                    "1. **무역 관련 질문만 답변**: 무역, 수출입, 관세, 통관, 원산지, FTA, 무역규제, 품목분류, HSCode 등과 관련된 질문에만 답변합니다.\n\n"
                    "2. **무역 외 질문 거부**: 무역과 관련이 없는 질문(일반상식, 개인적 조언, 오락, 요리, 여행 등)에 대해서는 다음과 같이 정중히 거부합니다:\n"
                    "   '죄송하지만 저는 무역 및 수출입 전문 AI입니다. 무역, 관세, 통관, 수출입 규제 등과 관련된 질문만 답변할 수 있습니다. 무역 관련 질문이 있으시면 언제든지 문의해 주세요.'\n\n"
                    "3. **전문적 답변**: 무역 관련 질문에 대해서는 정확하고 전문적인 정보를 제공하며, 최신 규정과 정책 변화를 반영합니다.\n\n"
                    "4. **한국어 답변**: 모든 답변은 한국어로 제공합니다.\n\n"
                    "5. **안전성**: 불법적이거나 유해한 무역 행위에 대해서는 조언하지 않습니다.",
                ),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{question}"),
            ]
        )

        rag_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "당신은 대한민국의 무역 및 수출입 전문가입니다. 제공된 문서를 바탕으로 사용자의 질문에 정확하고 전문적으로 답변하세요.\n\n"
                    "문서 내용:\n{context}",
                ),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{question}"),
            ]
        )

        web_search_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "당신은 대한민국의 무역 및 수출입 전문가입니다. 내부 데이터베이스에 정보가 없어 웹 검색을 통해 답변을 제공합니다. "
                    "무역, 수출입, 관세, 통관 관련 정보만 검색하고 답변하세요.",
                ),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{question}"),
            ]
        )

        # 3. 헬퍼 함수들
        @as_runnable
        def format_docs(docs: List[Document]) -> str:
            """검색된 문서 리스트를 단일 문자열로 포맷"""
            return "\n\n".join(doc.page_content for doc in docs)

        @as_runnable
        async def classify_question(input_dict: Dict[str, Any]) -> Dict[str, Any]:
            """질문을 LLM으로 분류"""
            question = input_dict.get("question", "")
            classification = await self._classify_question_with_llm(question)
            return {**input_dict, "classification": classification}

        @as_runnable
        def route_by_classification(input_dict: Dict[str, Any]) -> Dict[str, Any]:
            """분류 결과에 따라 라우팅 결정"""
            classification = input_dict.get("classification")
            if not classification:
                return {**input_dict, "route": "non_trade"}

            if classification.category == "hscode":
                return {**input_dict, "route": "hscode"}
            elif classification.category == "trade_general":
                return {**input_dict, "route": "trade_general"}
            elif classification.category == "cargo_tracking":
                return {**input_dict, "route": "cargo_tracking"}
            else:
                return {**input_dict, "route": "non_trade"}

        # 4. 세부 체인들
        # 4a. 무역 관련 일반 대화 체인
        general_chain = (
            RunnablePassthrough.assign(chat_history=lambda x: x.get("chat_history", []))
            | RunnablePassthrough.assign(
                answer=general_chat_prompt | llm | output_parser
            )
            | (lambda x: {"answer": x["answer"], "source": "llm", "docs": []})
        )

        # 4b. RAG 성공 시 체인
        rag_chain_success = (
            RunnablePassthrough.assign(
                context=lambda x: format_docs.invoke(x["docs"]),
                chat_history=lambda x: x.get("chat_history", []),
            )
            | rag_prompt
            | llm
            | output_parser
        )

        # 4c. RAG 실패 시 웹 검색 체인
        rag_chain_fallback_web_search = (
            RunnablePassthrough.assign(chat_history=lambda x: x.get("chat_history", []))
            | web_search_prompt
            | llm_with_web_search
        )

        # 4d. HSCode 질문 처리 체인 (RAG + 웹 검색 폴백)
        @as_runnable
        def hscode_chain(input_dict: Dict[str, Any]) -> Dict[str, Any]:
            """HSCode 질문 처리"""
            # 문서 검색
            docs = retriever.invoke(input_dict["question"])
            input_with_docs = {**input_dict, "docs": docs}

            # 문서가 있으면 RAG 체인, 없으면 웹 검색 체인
            if docs:
                result = rag_chain_success.invoke(input_with_docs)
                return {"answer": result, "source": "rag", "docs": docs}
            else:
                result = rag_chain_fallback_web_search.invoke(input_with_docs)
                web_docs = []
                if (
                    isinstance(result, AIMessage)
                    and hasattr(result, "tool_calls")
                    and result.tool_calls
                ):
                    web_docs = [
                        Document(
                            page_content=t["web_search_20250305"]["snippet"],
                            metadata={"url": t["web_search_20250305"]["url"]},
                        )
                        for t in result.tool_calls
                        if "web_search_20250305" in t
                    ]
                return {"answer": result.content, "source": "web", "docs": web_docs}

        # 5. 최종 라우팅 체인
        @as_runnable
        def final_routing(input_dict: Dict[str, Any]) -> Dict[str, Any]:
            """최종 라우팅 및 응답 생성"""
            route = input_dict.get("route", "non_trade")

            if route == "hscode":
                return hscode_chain.invoke(input_dict)
            elif route == "trade_general":
                return general_chain.invoke(input_dict)
            elif route == "cargo_tracking":
                # 화물통관 조회는 특별한 표시를 남김 (상위 레이어에서 처리)
                return {
                    "answer": "CARGO_TRACKING_DETECTED",
                    "source": "cargo_tracking",
                    "docs": [],
                    "cargo_tracking": True,
                    "original_question": input_dict.get("question", ""),
                }
            else:
                # 무역 관련이 아닌 질문에 대한 거부 응답
                return {
                    "answer": "죄송하지만 저는 무역 및 수출입 전문 AI입니다. 무역, 관세, 통관, 수출입 규제, HSCode 등과 관련된 질문만 답변할 수 있습니다. 무역 관련 질문이 있으시면 언제든지 문의해 주세요.",
                    "source": "restriction",
                    "docs": [],
                }

        # 6. 전체 체인 구성
        final_chain = classify_question | route_by_classification | final_routing

        return final_chain

    # --- 모니터링 체인 생성 로직 (기존과 거의 동일) ---

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
                    summary=None,
                    error_message="LLM이 구조화된 출력을 생성하지 못했습니다. (No tool call)",
                )

            if llm_output.status == "UPDATE_FOUND":
                if not llm_output.summary or not llm_output.sources:
                    return MonitoringUpdate(
                        status="ERROR",
                        hscode=hscode,
                        summary=None,
                        sources=[],
                        error_message="'UPDATE_FOUND' 상태이지만 summary 또는 sources가 누락되었습니다.",
                    )
                return MonitoringUpdate(
                    status="UPDATE_FOUND",
                    hscode=hscode,
                    summary=llm_output.summary,
                    sources=llm_output.sources,
                    error_message=None,
                )

            if llm_output.status == "NO_UPDATE":
                return MonitoringUpdate(
                    status="NO_UPDATE",
                    hscode=hscode,
                    summary=None,
                    sources=[],
                    error_message=None,
                )

            # "UPDATE_FOUND", "NO_UPDATE" 이외의 상태값 처리 (이론적으로는 발생하지 않음)
            return MonitoringUpdate(
                status="ERROR",
                hscode=hscode,
                summary=None,
                sources=[],
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

        return RunnablePassthrough.assign(parsed_tools=chain).pipe(
            format_final_response
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
                    f"HSCode '{hscode}' 모니터링 중 오류 상태 반환: {result.error_message}"
                )
            return result
        except Exception as e:
            logger.error(
                f"HSCode '{hscode}' 모니터링 체인 실행 중 예외 발생: {e}", exc_info=True
            )
            return MonitoringUpdate(
                status="ERROR",
                hscode=hscode,
                summary=None,
                sources=[],
                error_message=str(e),
            )
