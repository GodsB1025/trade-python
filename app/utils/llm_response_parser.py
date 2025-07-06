import logging
import re
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timedelta, timezone

import dateparser
from langchain_core.messages import AIMessage, ToolCall

from app.models.monitoring_models import SearchResult

logger = logging.getLogger(__name__)


def _extract_results_from_tool_content(
    content: List[Dict[str, Any]]
) -> List[SearchResult]:
    """Tool content 블록에서 검색 결과를 추출하는 헬퍼 함수."""
    results = []
    for item in content:
        if not isinstance(item, dict):
            continue

        # TypeScript 타입(encrypted_content)과 기존 필드(content)를 모두 고려
        item_content = item.get("encrypted_content") or item.get("content")

        # 필수 필드(title, url, content) 존재 여부 확인
        if "url" in item and "title" in item and item_content is not None:
            # 날짜 정보: TypeScript 타입(page_age)을 우선적으로 사용하고, 기존 필드들을 fallback으로 사용
            date_info = (
                item.get("page_age") or item.get("published_date") or item.get("date")
            )

            results.append(
                SearchResult(
                    title=item["title"],
                    url=item["url"],
                    content=item_content,
                    published_date=date_info,
                )
            )
    return results


def extract_search_results_from_ai_message(ai_message: AIMessage) -> List[SearchResult]:
    """
    AIMessage에서 웹 검색 도구의 결과물을 지능적으로 추출.

    AIMessage의 `tool_calls`와 `content` 블록을 모두 검사하여
    웹 검색 결과로 추정되는 데이터를 수집하고 파싱함. Anthropic Claude 모델의
    응답 구조에 최적화됨.

    Args:
        ai_message: LLM이 반환한 AIMessage 객체.

    Returns:
        파싱된 SearchResult 객체의 리스트.
    """
    if not isinstance(ai_message, AIMessage):
        logger.warning("AIMessage가 아닌 객체가 입력되어 검색 결과를 추출할 수 없음.")
        return []

    all_results: List[SearchResult] = []
    processed_urls = set()

    def add_result(result: SearchResult):
        if result.url not in processed_urls:
            all_results.append(result)
            processed_urls.add(str(result.url))
            logger.debug(f"추출된 검색 결과: {result.title}")

    # 1. AIMessage.tool_calls에서 직접적으로 도구 결과 추출 (하위 호환성)
    if hasattr(ai_message, "tool_calls") and isinstance(ai_message.tool_calls, list):
        for tool_call in ai_message.tool_calls:
            # Anthropic의 tool_use와 유사한 구조를 처리할 수 있지만, 주된 결과는 content 블록에 있음
            if (
                isinstance(tool_call, dict)
                and tool_call.get("name", "").lower() == "web_search"
            ):
                # 'args'에 실제 결과가 포함된 경우 (일부 모델/통합 방식)
                if "documents" in tool_call.get("args", {}):
                    results = _extract_results_from_tool_content(
                        tool_call["args"]["documents"]
                    )
                    for res in results:
                        add_result(res)

    # 2. AIMessage.content 블록 리스트에서 결과 추출 (Anthropic Claude 모델의 표준 방식)
    if hasattr(ai_message, "content") and isinstance(ai_message.content, list):
        for block in ai_message.content:
            if not isinstance(block, dict):
                continue

            # 2a. 'tool_result' 타입의 블록에서 직접 추출
            # 사용자가 제공한 TypeScript 타입에 따르면, content는 검색 결과 객체의 배열임.
            if block.get("type") == "tool_result" and "content" in block:
                content = block["content"]
                # 내용이 문자열화된 JSON일 수 있음
                if isinstance(content, str):
                    try:
                        import json

                        content = json.loads(content)
                    except json.JSONDecodeError:
                        logger.warning(
                            "tool_result의 content가 JSON 형태가 아니어서 파싱할 수 없음."
                        )
                        continue

                if isinstance(content, list):
                    # content 자체가 결과 리스트인 경우 (표준 Anthropic 응답)
                    results = _extract_results_from_tool_content(content)
                    for res in results:
                        add_result(res)

            # 2b. 사용자가 제공한 타입과 유사한 구조 탐색
            elif block.get("type") == "web_search_tool_result":
                if isinstance(block.get("content"), list):
                    results = _extract_results_from_tool_content(block["content"])
                    for res in results:
                        add_result(res)

    logger.info(f"총 {len(all_results)}개의 고유한 검색 결과를 추출했습니다.")
    return all_results


def extract_json_from_ai_message(ai_message: AIMessage) -> str:
    """
    AIMessage에서 JSON 문자열을 지능적으로 추출.

    - content가 리스트인 경우, thinking 블록을 제외하고 text 타입 블록만 처리
    - 마크다운 코드 블록(```json ... ```)을 자동으로 처리.
    - LLM이 JSON 앞에 추가적인 텍스트를 포함하는 경우도 처리.
    """
    if not isinstance(ai_message, AIMessage) or not ai_message.content:
        logger.error("Invalid or empty AIMessage received for JSON extraction.")
        return ""

    content = ai_message.content

    if isinstance(content, list):
        text_blocks = []
        for block in content:
            if isinstance(block, dict):
                # thinking 블록은 제외하고 text 타입만 처리
                if block.get("type") == "text" and block.get("text", "").strip():
                    text_blocks.append(block.get("text", "").strip())
                # type이 명시되지 않았지만 text 필드가 있는 경우 (thinking 제외)
                elif (
                    block.get("type") != "thinking"
                    and "text" in block
                    and block.get("text", "").strip()
                ):
                    text_blocks.append(block.get("text", "").strip())

        if not text_blocks:
            logger.error("No text content found in AIMessage response list.")
            return ""
        # 모든 텍스트 블록을 합쳐서 JSON 추출 시도
        raw_text = "\n".join(text_blocks)
    elif isinstance(content, str):
        raw_text = content.strip()
    else:
        logger.error(f"Unexpected content type in AIMessage: {type(content)}")
        return ""

    if not raw_text:
        return ""

    # 1. 마크다운 코드 블록(```json ... ```)에서 JSON 추출 시도
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 2. 마크다운이 없는 경우, 문자열에서 첫 '{'와 마지막 '}' 사이의 내용을 추출
    # LLM이 JSON 앞뒤에 부가적인 설명을 붙이는 경우에 대응
    match = re.search(r"({[\s\S]*})", raw_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    logger.warning(
        "Failed to extract JSON from AIMessage content. Raw text: %s", raw_text[:200]
    )
    return ""


def extract_citation_urls_from_ai_message(ai_message: AIMessage) -> List[str]:
    """
    AIMessage 객체에서 웹 검색 결과(citation)의 URL들을 지능적으로 추출.

    LLM 응답의 다양한 위치에 포함될 수 있는 URL들을 중복 없이 수집.
    - `content`가 리스트인 경우, `tool_result` 블록과 `text` 블록의 `citations`를 모두 확인.
    - `response_metadata`의 `citations` 필드도 하위 호환성을 위해 확인.

    Args:
        ai_message: LLM이 반환한 AIMessage 객체.

    Returns:
        추출된 고유한 URL 문자열의 리스트.
    """
    if not isinstance(ai_message, AIMessage):
        logger.warning("AIMessage가 아닌 객체가 입력되어 URL을 추출할 수 없음.")
        return []

    citation_urls: List[str] = []
    processed_urls = set()

    def add_url(url: str):
        if url and url not in processed_urls:
            citation_urls.append(url)
            processed_urls.add(url)
            logger.debug(f"Found citation URL: {url}")

    # 1. content 블록 리스트에서 URL 추출
    if hasattr(ai_message, "content") and isinstance(ai_message.content, list):
        for block in ai_message.content:
            if not isinstance(block, dict):
                continue

            # 1a. tool_result 블록 (Anthropic Native Search Tool 결과)
            if block.get("type") == "tool_use" and block.get("name") == "web_search":
                # 이 블록은 도구 '호출' 자체이며, 실제 결과는 다른 블록에 있을 수 있음.
                # 그러나 안전을 위해 내부 구조도 확인
                if isinstance(block.get("input", {}).get("documents"), list):
                    for doc in block["input"]["documents"]:
                        if isinstance(doc, dict) and "url" in doc:
                            add_url(doc["url"])

            # 1b. text 블록의 citations에서 URL 추출 (새로운 Claude 3 모델 형식)
            elif block.get("type") == "text" and isinstance(
                block.get("citations"), list
            ):
                for citation in block.get("citations", []):
                    source = citation.get("source", {})
                    if isinstance(source, dict) and "url" in source:
                        add_url(source["url"])

            # 1c. 레거시/다른 형식의 tool_result 블록 (web_search_tool_result)
            elif block.get("type") == "web_search_tool_result" and isinstance(
                block.get("content"), list
            ):
                for result_item in block.get("content", []):
                    if isinstance(result_item, dict) and "url" in result_item:
                        add_url(result_item["url"])

    # 2. response_metadata에서도 추가로 확인 (하위 호환)
    if (
        hasattr(ai_message, "response_metadata")
        and "citations" in ai_message.response_metadata
    ):
        for citation in ai_message.response_metadata["citations"]:
            source = citation.get("source", {})
            if isinstance(source, dict) and "url" in source:
                add_url(source["url"])

    logger.info(f"Found {len(citation_urls)} unique citation URLs in total.")
    return citation_urls


def extract_text_content_safely(content: Any) -> str:
    """
    LangChain Anthropic 응답의 content를 안전하게 문자열로 변환

    langchain-anthropic 0.3.14+에서 chunk.content가 다양한 형태로 반환될 수 있음:
    - str: 직접 텍스트
    - List[dict]: [{"type": "thinking", ...}, {"type": "text", "text": "내용"}] 형태
    - List[str]: ["텍스트"] 형태
    - List[object]: text 속성을 가진 객체들

    Args:
        content: LangChain response의 content 속성

    Returns:
        안전하게 추출된 텍스트 문자열
    """
    if not content:
        return ""

    # 이미 문자열인 경우
    if isinstance(content, str):
        return content

    # 리스트인 경우
    if isinstance(content, list):
        if not content:
            return ""

        text_parts = []

        for item in content:
            # 문자열인 경우
            if isinstance(item, str):
                text_parts.append(item)
                continue

            # 딕셔너리인 경우 - type 필드 확인하여 "text" 타입만 처리
            if isinstance(item, dict):
                # type이 "text"인 블록만 처리 (thinking, signature 등은 제외)
                if item.get("type") == "text" and "text" in item:
                    text_parts.append(str(item["text"]))
                elif item.get("type") == "text" and "content" in item:
                    text_parts.append(str(item["content"]))
                elif "text" in item and item.get("type") != "thinking":
                    # type이 명시되지 않았지만 text 필드가 있고 thinking이 아닌 경우
                    text_parts.append(str(item["text"]))
                elif "content" in item and item.get("type") != "thinking":
                    # type이 명시되지 않았지만 content 필드가 있고 thinking이 아닌 경우
                    text_parts.append(str(item["content"]))
                continue

            # 객체인 경우 (text 속성 확인)
            if hasattr(item, "text"):
                text_parts.append(str(getattr(item, "text", "")))
            elif hasattr(item, "content"):
                text_parts.append(str(getattr(item, "content", "")))
            else:
                # 마지막 폴백으로 문자열 변환 (thinking 제외)
                item_str = str(item)
                if not item_str.startswith(
                    "{'type': 'thinking'"
                ) and not item_str.startswith("EoYJCk"):
                    text_parts.append(item_str)

        # 모든 텍스트 부분을 결합 (줄바꿈 보존을 위해 공백 없이 연결)
        result = "".join(text_parts).strip()

        # 결과가 비어있다면 첫 번째 요소 처리 (하위 호환성)
        if not result and content:
            first_item = content[0]
            if isinstance(first_item, str):
                result = first_item
            elif isinstance(first_item, dict):
                if "text" in first_item:
                    result = str(first_item["text"])
                elif "content" in first_item:
                    result = str(first_item["content"])

        return result

    # 딕셔너리인 경우
    if isinstance(content, dict):
        # type이 "text"인 경우만 처리
        if content.get("type") == "text" and "text" in content:
            return str(content["text"])
        elif "text" in content and content.get("type") != "thinking":
            return str(content["text"])
        elif "content" in content and content.get("type") != "thinking":
            return str(content["content"])
        else:
            return str(content)

    # 객체인 경우
    if hasattr(content, "text"):
        return str(getattr(content, "text", ""))

    if hasattr(content, "content"):
        return str(getattr(content, "content", ""))

    # 최종 폴백: 문자열 변환
    try:
        return str(content)
    except Exception as e:
        logger.warning(f"Content 변환 중 오류: {e}, content type: {type(content)}")
        return ""


def extract_text_from_anthropic_response(response: Any) -> str:
    """
    Anthropic 응답 객체에서 텍스트를 안전하게 추출

    Args:
        response: Anthropic 응답 객체 (AIMessage 등)

    Returns:
        추출된 텍스트 문자열
    """
    if not response:
        return ""

    # content 속성이 있는 경우
    if hasattr(response, "content"):
        return extract_text_content_safely(response.content)

    # 직접 텍스트인 경우
    if isinstance(response, str):
        return response

    # 기타 경우 문자열 변환
    return str(response)


def extract_text_from_stream_chunk(chunk: Any) -> str:
    """
    스트림 청크에서 텍스트를 안전하게 추출

    Args:
        chunk: 스트림 청크 객체

    Returns:
        추출된 텍스트 문자열
    """
    if not chunk:
        return ""

    # content 속성 확인
    if hasattr(chunk, "content"):
        content = chunk.content
        if content:
            return extract_text_content_safely(content)

    # 직접 텍스트인 경우
    if isinstance(chunk, str):
        return chunk

    return ""
