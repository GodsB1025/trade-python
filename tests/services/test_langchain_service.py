"""
LangChain 서비스 테스트
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pytest_mock import MockerFixture
from typing import AsyncGenerator, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime

from app.services.langchain_service import LangChainService
from app.models.schemas import ChatRequest, NewsItem, NewsReport
from app.models.db_models import ChatSession
from sqlalchemy.ext.asyncio import AsyncSession


class TestLangChainService:
    """LangChain 서비스 테스트 클래스"""

    @pytest.fixture
    def mock_db_session(self) -> AsyncMock:
        """Mock 데이터베이스 세션 생성"""
        session = AsyncMock(spec=AsyncSession)
        return session

    @pytest.fixture
    def mock_chat_session(self) -> ChatSession:
        """Mock 채팅 세션 생성"""
        session = ChatSession()
        session.session_uuid = uuid4()
        session.created_at = datetime.now()
        session.user_id = 1
        session.session_title = "Test Session"
        session.message_count = 0
        return session

    @pytest.fixture
    def mock_langchain_service(self, mock_db_session: AsyncMock) -> LangChainService:
        """Mock LangChain 서비스 인스턴스 생성"""
        # 환경 변수와 외부 의존성을 Mock으로 패치
        with patch.multiple(
            'app.services.langchain_service',
            ChatAnthropic=MagicMock(),
            VoyageAIEmbeddings=MagicMock(),
            PGVector=MagicMock(),
            create_history_aware_retriever=MagicMock(),
            create_stuff_documents_chain=MagicMock(),
            create_retrieval_chain=MagicMock(),
            RunnableWithMessageHistory=MagicMock(),
            ChatHistoryService=MagicMock(),
            settings=MagicMock(
                ANTHROPIC_API_KEY="test-key",
                VOYAGE_API_KEY="test-key",
                DATABASE_URL="postgresql://test"
            )
        ) as mocks:
            # ChatAnthropic 인스턴스에 bind_tools 메서드 Mock 추가
            mock_anthropic_instance = mocks['ChatAnthropic'].return_value
            mock_anthropic_instance.bind_tools.return_value = AsyncMock()

            service = LangChainService(mock_db_session)

            # 주요 속성 Mock 설정
            service.anthropic_chat_model = mock_anthropic_instance
            service.llm_with_native_search = mock_anthropic_instance.bind_tools.return_value
            service.vector_store = MagicMock()
            service.vector_store.as_retriever.return_value = MagicMock()

            return service

    @pytest.mark.asyncio
    async def test_stream_chat_response_success(
        self,
        mock_langchain_service: LangChainService,
        mocker: MockerFixture
    ):
        """채팅 응답 스트리밍 성공 테스트"""
        # Given: Mock 데이터 준비
        chat_request = ChatRequest(
            question="무역 규제에 대해 알려줘",
            sessionId=str(uuid4()),
            userId=1
        )

        # Mock 체인 생성
        mock_chain = AsyncMock()

        # Mock 스트리밍 응답 준비
        async def mock_astream(*args, **kwargs):
            """Mock 비동기 스트리밍 제너레이터"""
            yield {"answer": "무역 규제는"}
            yield {"answer": " 국가 간 거래를"}
            yield {"answer": " 규율하는 법률입니다."}

        mock_chain.astream = mock_astream

        # Mock 체인 생성 메서드 패치
        mocker.patch.object(mock_langchain_service,
                            'get_conversational_chain', return_value=mock_chain)

        # When: 스트리밍 응답 실행
        result_chunks = []
        async for chunk in mock_langchain_service.stream_chat_response(chat_request):
            result_chunks.append(chunk)

        # Then: 결과 검증
        assert len(result_chunks) == 4
        assert result_chunks[0] == {"data": "무역 규제는"}
        assert result_chunks[1] == {"data": " 국가 간 거래를"}
        assert result_chunks[2] == {"data": " 규율하는 법률입니다."}
        assert result_chunks[3] == {"event": "end", "data": "Stream ended"}

        # Mock 호출 검증
        mock_langchain_service.get_conversational_chain.assert_called_once()
        mock_chain.astream.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_chat_response_error_handling(
        self,
        mock_langchain_service: LangChainService,
        mocker: MockerFixture
    ):
        """채팅 응답 스트리밍 에러 처리 테스트"""
        # Given: Mock 에러 상황 준비
        chat_request = ChatRequest(
            question="테스트 질문",
            sessionId="test-session",
            userId=1
        )

        mock_chain = AsyncMock()
        mock_chain.astream.side_effect = Exception("API 호출 실패")

        mocker.patch.object(mock_langchain_service,
                            'get_conversational_chain', return_value=mock_chain)

        # When: 에러 상황에서 스트리밍 실행
        result_chunks = []
        async for chunk in mock_langchain_service.stream_chat_response(chat_request):
            result_chunks.append(chunk)

        # Then: 에러 응답 검증
        assert len(result_chunks) == 1
        assert result_chunks[0]["event"] == "error"
        assert "API 호출 실패" in result_chunks[0]["data"]

    @pytest.mark.asyncio
    async def test_create_news_via_claude_success(
        self,
        mock_langchain_service: LangChainService,
    ):
        """Claude를 통한 뉴스 생성 성공 테스트"""
        # Given: Mock 뉴스 데이터 준비
        mock_news_items = [
            NewsItem(
                title="한국-미국 무역 협정 개정",
                summary="양국 간 새로운 무역 조건 합의",
                url="https://example.com/news1",
                published_date="2024-01-15"
            )
        ]
        mock_report = NewsReport(news=mock_news_items)

        # Mock 구조화된 LLM 체인 설정
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke.return_value = mock_report

        mock_langchain_service.anthropic_chat_model.with_structured_output.return_value = mock_structured_llm

        # When: 뉴스 생성 실행
        result = await mock_langchain_service.create_news_via_claude()

        # Then: 결과 검증
        assert len(result) == 1
        assert result[0].title == "한국-미국 무역 협정 개정"
        mock_langchain_service.anthropic_chat_model.with_structured_output.assert_called_once_with(
            NewsReport)
        mock_structured_llm.ainvoke.assert_called_once()

    def test_service_initialization_success(self, mock_db_session: AsyncMock):
        """서비스 초기화 성공 테스트"""
        with patch.multiple(
            'app.services.langchain_service',
            ChatAnthropic=MagicMock(),
            VoyageAIEmbeddings=MagicMock(),
            PGVector=MagicMock(),
            settings=MagicMock(
                ANTHROPIC_API_KEY="test-key",
                VOYAGE_API_KEY="test-key",
                DATABASE_URL="postgresql://test"
            )
        ):
            service = LangChainService(mock_db_session)

            # Then: 서비스가 정상적으로 초기화됨
            assert service.db_session == mock_db_session
            assert service.anthropic_chat_model is not None
            assert service.llm_with_native_search is not None
            assert service.vector_store is not None
