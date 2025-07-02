"""
Anthropic 서비스 테스트
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pytest_mock import MockerFixture
from typing import List, Dict, Any, Tuple

from app.services.anthropic_service import AnthropicService
from app.models.schemas import SearchResult, SearchType, WebSearchResults
from app.models.chat_models import PromptChainContext


class TestAnthropicService:
    """Anthropic 서비스 테스트 클래스"""

    @pytest.fixture
    def mock_anthropic_service(self) -> AnthropicService:
        """Mock Anthropic 서비스 인스턴스 생성"""
        # 환경 변수와 외부 의존성을 Mock으로 패치
        with patch.multiple(
            'app.services.anthropic_service',
            ChatAnthropic=MagicMock(),
            settings=MagicMock(
                anthropic_model="claude-3-sonnet-20240229",
                claude_api_key="test-api-key",
                web_search_max_uses=5
            )
        ):
            service = AnthropicService()

            # LLM Mock 설정
            service.llm = AsyncMock()
            service.llm_with_search = AsyncMock()

            return service

    @pytest.fixture
    def mock_prompt_context(self) -> PromptChainContext:
        """Mock PromptChainContext 생성"""
        context = PromptChainContext()
        context.search_results = [
            SearchResult(
                title="무역 규제 최신 동향",
                url="https://example.com/trade1",
                snippet="2024년 무역 규제 변경사항에 대한 정보",
                search_type=SearchType.NEWS,
                relevance_score=0.9
            )
        ]
        context.reasoning_steps = ["검색 실행", "결과 분석"]
        context.confidence_scores = [0.8, 0.9]
        return context

    @pytest.mark.asyncio
    async def test_perform_web_search_success(
        self,
        mock_anthropic_service: AnthropicService,
        mocker: MockerFixture
    ):
        """웹 검색 성공 테스트"""
        # Given: Mock 검색 데이터 준비
        query = "한국 무역 규제 최신 동향"
        search_types = [SearchType.NEWS, SearchType.GENERAL]

        # Mock 검색 결과
        mock_search_results = [
            SearchResult(
                title="무역 규제 업데이트",
                url="https://example.com/trade1",
                snippet="최신 무역 규제 변경사항",
                search_type=SearchType.NEWS,
                relevance_score=0.9
            ),
            SearchResult(
                title="일반 무역 정보",
                url="https://example.com/trade2",
                snippet="무역 관련 일반 정보",
                search_type=SearchType.GENERAL,
                relevance_score=0.7
            )
        ]

        # Mock 메서드들 설정
        mock_anthropic_service._enhance_query_for_type = AsyncMock(
            side_effect=lambda q, t: f"{q} {t.value}")
        mock_anthropic_service._execute_web_search = AsyncMock(
            return_value=MagicMock(content="Mock response"))
        mock_anthropic_service._parse_search_results = AsyncMock(side_effect=[
            [mock_search_results[0]],  # NEWS 결과
            [mock_search_results[1]]   # GENERAL 결과
        ])

        # When: 웹 검색 실행
        result = await mock_anthropic_service.perform_web_search(query, search_types)

        # Then: 결과 검증
        assert isinstance(result, WebSearchResults)
        assert result.query == query
        assert result.total_results == 2
        assert len(result.results) == 2
        assert result.search_duration_ms > 0

        # Mock 호출 검증
        assert mock_anthropic_service._enhance_query_for_type.call_count == 2
        assert mock_anthropic_service._execute_web_search.call_count == 2
        assert mock_anthropic_service._parse_search_results.call_count == 2

    @pytest.mark.asyncio
    async def test_enhance_query_for_type(self, mock_anthropic_service: AnthropicService):
        """검색 타입별 쿼리 개선 테스트"""
        # Given: 기본 쿼리
        base_query = "무역 규제"

        # When & Then: 각 검색 타입별 쿼리 개선 테스트
        general_query = await mock_anthropic_service._enhance_query_for_type(base_query, SearchType.GENERAL)
        assert general_query == base_query

        news_query = await mock_anthropic_service._enhance_query_for_type(base_query, SearchType.NEWS)
        assert "latest news recent updates" in news_query

        academic_query = await mock_anthropic_service._enhance_query_for_type(base_query, SearchType.ACADEMIC)
        assert "research papers academic study" in academic_query

        technical_query = await mock_anthropic_service._enhance_query_for_type(base_query, SearchType.TECHNICAL)
        assert "technical documentation implementation guide" in technical_query

    @pytest.mark.asyncio
    async def test_execute_web_search(self, mock_anthropic_service: AnthropicService):
        """웹 검색 실행 테스트"""
        # Given: 검색 쿼리
        query = "테스트 검색 쿼리"

        # Mock LLM 응답 설정
        mock_response = MagicMock()
        mock_response.content = "검색 결과 내용"
        mock_anthropic_service.llm_with_search.ainvoke.return_value = mock_response

        # When: 웹 검색 실행
        result = await mock_anthropic_service._execute_web_search(query)

        # Then: 결과 검증
        assert result == mock_response
        mock_anthropic_service.llm_with_search.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_parse_search_results(self, mock_anthropic_service: AnthropicService):
        """검색 결과 파싱 테스트"""
        # Given: Mock 검색 응답
        mock_response = MagicMock()
        mock_response.content = "검색 결과 내용입니다. 무역 규제에 대한 정보를 포함합니다."
        search_type = SearchType.NEWS

        # When: 검색 결과 파싱
        results = await mock_anthropic_service._parse_search_results(mock_response, search_type)

        # Then: 결과 검증
        assert len(results) == 1
        assert results[0].search_type == search_type
        assert "검색 결과 for news" in results[0].title
        assert results[0].relevance_score == 0.8

    @pytest.mark.asyncio
    async def test_generate_response_with_context_success(
        self,
        mock_anthropic_service: AnthropicService,
        mock_prompt_context: PromptChainContext
    ):
        """컨텍스트를 활용한 응답 생성 성공 테스트"""
        # Given: Mock 데이터 준비
        user_message = "무역 규제에 대해 설명해주세요"
        conversation_history = [
            {"role": "user", "content": "안녕하세요"},
            {"role": "assistant", "content": "안녕하세요! 무엇을 도와드릴까요?"}
        ]

        # Mock LLM 응답 설정
        mock_response = MagicMock()
        mock_response.content = "무역 규제는 국가 간 거래를 규율하는 법률입니다."
        mock_anthropic_service.llm.ainvoke.return_value = mock_response

        # When: 응답 생성 실행
        response, reasoning, confidence = await mock_anthropic_service.generate_response_with_context(
            user_message, mock_prompt_context, conversation_history
        )

        # Then: 결과 검증
        assert response == "무역 규제는 국가 간 거래를 규율하는 법률입니다."
        assert "최종 응답 생성 완료" in reasoning
        assert 0.8 <= confidence <= 1.0  # 신뢰도 범위 확인

        # Mock 호출 검증
        mock_anthropic_service.llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_updates_for_bookmark_with_update(
        self,
        mock_anthropic_service: AnthropicService
    ):
        """북마크 업데이트 검색 - 업데이트 있음 테스트"""
        # Given: Mock 업데이트 데이터 준비
        bookmark_target_value = "HS Code 8517"
        expected_summary = "8517 품목에 대한 새로운 관세율이 적용됩니다."

        # Mock LLM 응답 설정
        mock_response = MagicMock()
        mock_response.content = expected_summary
        mock_anthropic_service.llm_with_search.ainvoke.return_value = mock_response

        # When: 북마크 업데이트 검색 실행
        result = await mock_anthropic_service.find_updates_for_bookmark(bookmark_target_value)

        # Then: 결과 검증
        assert result == expected_summary
        mock_anthropic_service.llm_with_search.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_updates_for_bookmark_no_update(
        self,
        mock_anthropic_service: AnthropicService
    ):
        """북마크 업데이트 검색 - 업데이트 없음 테스트"""
        # Given: Mock 업데이트 없음 상황 준비
        bookmark_target_value = "HS Code 1234"

        # Mock LLM 응답 설정 (업데이트 없음)
        mock_response = MagicMock()
        mock_response.content = "업데이트 없음"
        mock_anthropic_service.llm_with_search.ainvoke.return_value = mock_response

        # When: 북마크 업데이트 검색 실행
        result = await mock_anthropic_service.find_updates_for_bookmark(bookmark_target_value)

        # Then: 결과 검증 (업데이트 없으면 None 반환)
        assert result is None

    @pytest.mark.asyncio
    async def test_find_updates_for_bookmark_short_response(
        self,
        mock_anthropic_service: AnthropicService
    ):
        """북마크 업데이트 검색 - 짧은 응답 테스트"""
        # Given: Mock 짧은 응답 상황 준비
        bookmark_target_value = "HS Code 5678"

        # Mock LLM 응답 설정 (너무 짧은 응답)
        mock_response = MagicMock()
        mock_response.content = "없음"  # 10자 미만
        mock_anthropic_service.llm_with_search.ainvoke.return_value = mock_response

        # When: 북마크 업데이트 검색 실행
        result = await mock_anthropic_service.find_updates_for_bookmark(bookmark_target_value)

        # Then: 결과 검증 (짧은 응답은 None 반환)
        assert result is None

    def test_build_system_prompt_with_context(
        self,
        mock_anthropic_service: AnthropicService,
        mock_prompt_context: PromptChainContext
    ):
        """컨텍스트가 있는 시스템 프롬프트 구성 테스트"""
        # When: 시스템 프롬프트 구성
        prompt = mock_anthropic_service._build_system_prompt(
            mock_prompt_context)

        # Then: 결과 검증
        assert "AI 어시스턴트입니다" in prompt
        assert "검색 결과 (1개)" in prompt
        assert "무역 규제 최신 동향" in prompt
        assert "이전 추론 과정" in prompt
        assert "검색 실행" in prompt
        assert "결과 분석" in prompt

    def test_build_system_prompt_without_context(self, mock_anthropic_service: AnthropicService):
        """컨텍스트가 없는 시스템 프롬프트 구성 테스트"""
        # Given: 빈 컨텍스트
        empty_context = PromptChainContext()

        # When: 시스템 프롬프트 구성
        prompt = mock_anthropic_service._build_system_prompt(empty_context)

        # Then: 결과 검증 (기본 프롬프트만 포함)
        assert "AI 어시스턴트입니다" in prompt
        assert "검색 결과" not in prompt
        assert "이전 추론 과정" not in prompt

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_anthropic_service: AnthropicService):
        """헬스 체크 성공 테스트"""
        # Given: Mock LLM 정상 응답 설정
        mock_response = MagicMock()
        mock_response.content = "안녕하세요!"
        mock_anthropic_service.llm.ainvoke.return_value = mock_response

        # When: 헬스 체크 실행
        result = await mock_anthropic_service.health_check()

        # Then: 결과 검증
        assert result is True
        mock_anthropic_service.llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_anthropic_service: AnthropicService):
        """헬스 체크 실패 테스트"""
        # Given: Mock LLM 에러 상황 설정
        mock_anthropic_service.llm.ainvoke.side_effect = Exception("API 연결 실패")

        # When: 헬스 체크 실행
        result = await mock_anthropic_service.health_check()

        # Then: 결과 검증
        assert result is False

    def test_service_initialization_success(self):
        """서비스 초기화 성공 테스트"""
        # Given & When: 서비스 초기화 (mock_anthropic_service fixture에서 이미 수행)
        with patch.multiple(
            'app.services.anthropic_service',
            ChatAnthropic=MagicMock(),
            settings=MagicMock(
                anthropic_model="claude-3-sonnet-20240229",
                claude_api_key="test-api-key",
                web_search_max_uses=5
            )
        ):
            service = AnthropicService()

        # Then: 서비스가 정상적으로 초기화됨
        assert service.llm is not None
        assert service.llm_with_search is not None
        assert service.web_search_tool is not None

    @pytest.mark.asyncio
    async def test_perform_web_search_default_types(
        self,
        mock_anthropic_service: AnthropicService,
        mocker: MockerFixture
    ):
        """웹 검색 기본 타입 테스트"""
        # Given: Mock 설정 (search_types=None)
        query = "무역 규제"

        mock_anthropic_service._enhance_query_for_type = AsyncMock(
            return_value=query)
        mock_anthropic_service._execute_web_search = AsyncMock(
            return_value=MagicMock(content="Mock"))
        mock_anthropic_service._parse_search_results = AsyncMock(
            return_value=[])

        # When: 검색 타입 지정 없이 웹 검색 실행
        result = await mock_anthropic_service.perform_web_search(query, None)

        # Then: 기본 타입(GENERAL)으로 검색됨
        assert result.query == query
        mock_anthropic_service._enhance_query_for_type.assert_called_once_with(
            query, SearchType.GENERAL)

    @pytest.mark.asyncio
    async def test_generate_response_without_history(
        self,
        mock_anthropic_service: AnthropicService,
        mock_prompt_context: PromptChainContext
    ):
        """대화 히스토리 없이 응답 생성 테스트"""
        # Given: Mock 데이터 준비 (conversation_history=None)
        user_message = "무역 규제 설명"

        mock_response = MagicMock()
        mock_response.content = "응답 내용"
        mock_anthropic_service.llm.ainvoke.return_value = mock_response

        # When: 히스토리 없이 응답 생성
        response, reasoning, confidence = await mock_anthropic_service.generate_response_with_context(
            user_message, mock_prompt_context, None
        )

        # Then: 정상 응답 생성됨
        assert response == "응답 내용"
        assert len(reasoning) > 0
        assert confidence > 0
