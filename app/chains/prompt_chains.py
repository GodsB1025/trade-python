"""
프롬프트 체이닝 구현
"""
from typing import List, Dict, Any, Optional
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.output_parsers import StrOutputParser

from ..models.schemas import SearchType, SearchResult
from ..models.chat_models import PromptChainContext
from ..services.anthropic_service import AnthropicService


class PromptChainOrchestrator:
    """프롬프트 체이닝 오케스트레이터"""

    def __init__(self, anthropic_service: AnthropicService):
        self.anthropic_service = anthropic_service
        self.chain_templates = self._initialize_chain_templates()

    def _initialize_chain_templates(self) -> Dict[str, ChatPromptTemplate]:
        """체인 템플릿 초기화"""
        return {
            "query_analysis": ChatPromptTemplate.from_messages([
                ("system", """사용자의 질문을 분석하여 다음을 결정:
1. 어떤 타입의 검색이 필요한지 (general, news, academic, technical)
2. 검색 우선순위
3. 예상되는 답변 복잡도

분석 결과를 구조화하여 반환."""),
                ("human", "{query}")
            ]),

            "search_synthesis": ChatPromptTemplate.from_messages([
                ("system", """제공된 검색 결과들을 종합하여 중간 답변을 생성.

검색 결과:
{search_results}

규칙:
- 정보의 신뢰성 평가
- 상충되는 정보 식별
- 핵심 포인트 추출"""),
                ("human",
                 "원본 질문: {original_query}\n\n위 검색 결과를 바탕으로 중간 분석을 제공해주세요.")
            ]),

            "final_synthesis": ChatPromptTemplate.from_messages([
                ("system", """모든 정보를 종합하여 최종 답변 생성.

이전 분석:
{previous_analysis}

추가 컨텍스트:
{additional_context}

규칙:
- 명확하고 구조화된 답변
- 출처 명시
- 실용적인 정보 제공
- 한국어로 응답"""),
                ("human", "{final_query}")
            ])
        }

    async def execute_prompt_chain(
        self,
        user_query: str,
        search_results: List[SearchResult],
        conversation_context: Optional[Dict[str, Any]] = None
    ) -> PromptChainContext:
        """프롬프트 체이닝 실행"""

        context = PromptChainContext(original_query=user_query)
        context.add_search_results(search_results)

        # 1단계: 쿼리 분석
        analysis_result = await self._execute_query_analysis(user_query)
        context.add_reasoning_step("쿼리 분석 완료", 0.8)

        # 2단계: 검색 결과 종합
        synthesis_result = await self._execute_search_synthesis(
            user_query, search_results, analysis_result
        )
        context.add_reasoning_step("검색 결과 종합 완료", 0.85)
        context.intermediate_responses.append(synthesis_result)

        # 3단계: 최종 종합
        final_result = await self._execute_final_synthesis(
            user_query, synthesis_result, conversation_context
        )
        context.add_reasoning_step("최종 답변 생성 완료", 0.9)
        context.intermediate_responses.append(final_result)

        return context

    async def _execute_query_analysis(self, query: str) -> str:
        """쿼리 분석 실행"""
        chain = (
            self.chain_templates["query_analysis"] |
            self.anthropic_service.llm |
            StrOutputParser()
        )

        result = await chain.ainvoke({"query": query})
        return result

    async def _execute_search_synthesis(
        self,
        original_query: str,
        search_results: List[SearchResult],
        analysis_result: str
    ) -> str:
        """검색 결과 종합 실행"""
        # 검색 결과를 텍스트로 변환
        results_text = self._format_search_results(search_results)

        chain = (
            self.chain_templates["search_synthesis"] |
            self.anthropic_service.llm |
            StrOutputParser()
        )

        result = await chain.ainvoke({
            "original_query": original_query,
            "search_results": results_text,
            "analysis": analysis_result
        })

        return result

    async def _execute_final_synthesis(
        self,
        final_query: str,
        previous_analysis: str,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """최종 종합 실행"""
        context_text = ""
        if additional_context:
            context_text = f"대화 맥락: {additional_context.get('conversation_summary', '')}"

        chain = (
            self.chain_templates["final_synthesis"] |
            self.anthropic_service.llm |
            StrOutputParser()
        )

        result = await chain.ainvoke({
            "final_query": final_query,
            "previous_analysis": previous_analysis,
            "additional_context": context_text
        })

        return result

    def _format_search_results(self, search_results: List[SearchResult]) -> str:
        """검색 결과를 텍스트 형식으로 변환"""
        if not search_results:
            return "검색 결과가 없습니다."

        formatted_results = []
        for i, result in enumerate(search_results, 1):
            formatted_result = f"""
{i}. 제목: {result.title}
   유형: {result.search_type.value}
   요약: {result.snippet}
   출처: {result.url}
   관련성: {result.relevance_score or 'N/A'}
"""
            formatted_results.append(formatted_result)

        return "\n".join(formatted_results)

    async def create_adaptive_chain(
        self,
        query_complexity: str,
        search_types: List[SearchType]
    ) -> Any:
        """적응형 체인 생성"""
        # 쿼리 복잡도와 검색 타입에 따른 동적 체인 구성
        if query_complexity == "simple" and SearchType.GENERAL in search_types:
            # 단순한 일반 검색용 체인
            return self._create_simple_chain()
        elif query_complexity == "complex" or SearchType.ACADEMIC in search_types:
            # 복잡한 분석용 체인
            return self._create_complex_chain()
        else:
            # 기본 체인
            return self._create_default_chain()

    def _create_simple_chain(self):
        """단순 체인 생성"""
        template = ChatPromptTemplate.from_messages([
            ("system", "간단하고 명확한 답변을 제공하는 AI입니다."),
            ("human", "{query}")
        ])
        return template | self.anthropic_service.llm | StrOutputParser()

    def _create_complex_chain(self):
        """복잡한 체인 생성"""
        template = ChatPromptTemplate.from_messages([
            ("system", """상세하고 분석적인 답변을 제공하는 전문 AI입니다.
- 다각도 분석
- 근거 제시
- 결론 도출"""),
            ("human", "{query}")
        ])
        return template | self.anthropic_service.llm | StrOutputParser()

    def _create_default_chain(self):
        """기본 체인 생성"""
        template = ChatPromptTemplate.from_messages([
            ("system", "균형잡힌 정보와 분석을 제공하는 AI입니다."),
            ("human", "{query}")
        ])
        return template | self.anthropic_service.llm | StrOutputParser()
