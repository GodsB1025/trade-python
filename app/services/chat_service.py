import logging
from typing import AsyncGenerator, Dict, Any

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.messages import SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_provider import llm_provider
from app.models.schemas import ChatRequest
from app.services.chat_history_service import ChatHistoryService


logger = logging.getLogger(__name__)


class ChatService:
    """
    대화형 RAG(Retrieval-Augmented Generation) 챗봇 관련 비즈니스 로직을 처리.
    """

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.chat_history_service = ChatHistoryService(self.db_session)
        # LLMProvider로부터 필요한 컴포넌트를 가져옴
        self.vector_store = llm_provider.vector_store
        self.anthropic_chat_model = llm_provider.news_chat_model
        self.llm_with_native_search = llm_provider.news_llm_with_native_search

    async def get_conversational_chain(self) -> RunnableWithMessageHistory:
        """
        채팅 기록을 고려하는 RAG 체인을 생성.

        - History-aware retriever가 채팅 기록을 바탕으로 질문을 재구성.
        - 웹 검색 기능이 포함된 LLM을 사용하여 답변 생성.
        """
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

        question_answer_chain = create_stuff_documents_chain(
            self.llm_with_native_search, qa_prompt)

        rag_chain = create_retrieval_chain(
            history_aware_retriever, question_answer_chain)

        conversational_rag_chain = RunnableWithMessageHistory(
            rag_chain,
            self.chat_history_service.get_chat_history,
            input_messages_key="input",
            history_messages_key="chat_history",
            output_messages_key="answer",
        ).with_types(input_type=dict, output_type=dict)

        return conversational_rag_chain

    async def stream_chat_response(
        self, chat_request: ChatRequest
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """채팅 요청을 처리하고, 응답을 비동기 제너레이터로 스트리밍."""
        chain_with_history = await self.get_conversational_chain()

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
                if "answer" in chunk and (content := chunk["answer"].get("content")):
                    yield {"data": content}

            yield {"event": "end", "data": "Stream ended"}

        except Exception as e:
            logger.error(f"Error during chat stream: {e}", exc_info=True)
            error_message = f"Error during stream: {e}"
            yield {"event": "error", "data": error_message}
