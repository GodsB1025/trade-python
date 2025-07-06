"""
고급 프롬프트 엔지니어링 기법을 사용한 의도 분류 서비스

Step-Back, Chain-of-Thought, Self-Consistency 기법 적용
"""

import logging
import json
import re
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr
import anthropic

from app.core.config import settings
from app.utils.llm_response_parser import extract_text_from_anthropic_response

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """의도 타입 열거형"""

    CARGO_TRACKING = "cargo_tracking"
    HSCODE_CLASSIFICATION = "hscode_classification"
    GENERAL_CHAT = "general_chat"
    NEWS_INQUIRY = "news_inquiry"
    REGULATORY_INQUIRY = "regulatory_inquiry"


@dataclass
class IntentClassificationResult:
    """의도 분류 결과"""

    intent_type: IntentType
    confidence_score: float
    reasoning_steps: List[str]
    extracted_entities: Dict[str, Any]
    alternative_intents: List[Tuple[IntentType, float]]


class IntentClassificationService:
    """고급 프롬프트 엔지니어링 기법을 사용한 의도 분류 서비스"""

    def __init__(self):
        self.llm = ChatAnthropic(
            model_name="claude-sonnet-4-20250514",
            api_key=SecretStr(settings.ANTHROPIC_API_KEY),
            temperature=0.1,  # 더 일관성 있는 결과를 위해 낮춤
            max_tokens_to_sample=1500,  # 토큰 수 조정
            timeout=45,  # 타임아웃 설정
            max_retries=2,  # LangChain 레벨에서도 재시도 설정
            stop=None,
        )
        # 중복 호출 방지를 위한 간단한 캐시 (메모리 기반, TTL: 60초)
        self._cache = {}
        self._cache_ttl = 60

    def _get_step_back_prompt(self) -> str:
        """Step-Back 프롬프팅: 일반적인 의도 분류 원칙 정의"""
        return """
You are an intent classification expert for a trade-related AI system.

First, let's step back and define the general principles for classifying user message intents:

## Intent Classification Principles (Step-Back Analysis)

### 1. Cargo Tracking (cargo_tracking)
**Key Features:**
- Contains clear cargo numbers or tracking numbers
- Intent to check shipping status or customs progress
- Specific waybill numbers or container number patterns exist

**Typical Patterns:**
- "Track ABCD1234567 for me"
- "Where is cargo number 123-456-789?"
- "Trace waybill number 1234567890"

### 2. HSCode Classification (hscode_classification)
**Key Features:**
- Requests customs classification for specific products
- Describes product characteristics, specifications, materials
- Combination of "HSCode", "tariff", "classification" keywords with product names

**Typical Patterns:**
- "Tell me smartphone HSCode"
- "What is the tariff classification for this product?"
- "Steel parts HSCode inquiry"

### 3. General Chat (general_chat)
**Key Features:**
- Conversation without specific business purpose
- Greetings, small talk, general questions

### 4. News Inquiry (news_inquiry)
**Key Features:**
- Inquiries about latest trade news or trends
- Requests for latest information about specific countries or industries

### 5. Regulatory Inquiry (regulatory_inquiry)
**Key Features:**
- Inquiries about trade regulations, sanctions, laws
- Questions about import/export permits, licenses

Now, let's analyze specific messages based on these principles.
"""

    def _get_chain_of_thought_prompt(self, message: str) -> str:
        """Chain-of-Thought 프롬프팅: 단계별 추론"""
        return f"""
Now let's analyze the following user message step by step to classify its intent:

**Message to analyze:** "{message}"

## Step-by-Step Analysis (Chain-of-Thought)

### Step 1: Keyword Analysis
- Identify key keywords contained in the message
- Analyze which intent each keyword is associated with
- Understand relationships between keywords

### Step 2: Entity Extraction
- Identify specific entities such as product names, model names, cargo numbers
- Analyze the form and pattern of each entity
- Evaluate the impact of entities on intent classification

### Step 3: Context Analysis
- Understand the structure and meaning of the entire sentence
- Infer the user's true intent
- Review possible misclassification scenarios

### Step 4: Pattern Matching
- Compare with typical patterns of each intent type
- Select the most appropriate intent type
- Calculate confidence score

**Return step-by-step analysis results in JSON format:**

```json
{{
    "step1_keywords": ["keyword1", "keyword2", "..."],
    "step2_entities": {{
        "product_names": ["product names"],
        "model_numbers": ["model numbers"],
        "cargo_numbers": ["cargo numbers"],
        "other_entities": ["other entities"]
    }},
    "step3_context": "Context analysis results",
    "step4_pattern_match": "Pattern matching results"
}}
```
"""

    def _get_self_consistency_prompt(self, message: str) -> str:
        """Self-Consistency 프롬프팅: 여러 관점에서 평가"""
        return f"""
Now let's analyze the following message from three different perspectives to classify its intent:

**Message to analyze:** "{message}"

## Multi-Perspective Analysis (Self-Consistency)

### Perspective 1: Linguistic Analysis
Intent identification based on sentence structure, vocabulary choice, and grammatical features

### Perspective 2: Business Context Analysis
Intent identification considering actual trade business processes and user needs

### Perspective 3: Data Pattern Analysis
Intent identification through data patterns such as numbers, codes, identifiers

**Return analysis results from each perspective in JSON format:**

```json
{{
    "perspective1_linguistic": {{
        "intent": "intent_type",
        "confidence": 0.8,
        "reasoning": "Linguistic analysis rationale"
    }},
    "perspective2_business": {{
        "intent": "intent_type",
        "confidence": 0.9,
        "reasoning": "Business context analysis rationale"
    }},
    "perspective3_data": {{
        "intent": "intent_type",
        "confidence": 0.7,
        "reasoning": "Data pattern analysis rationale"
    }},
    "final_consensus": {{
        "intent": "final_intent_type",
        "confidence": 0.85,
        "reasoning": "Comprehensive results from three perspectives"
    }}
}}
```
"""

    def _get_fallback_simple_prompt(self, message: str) -> str:
        """간단한 폴백 분류 프롬프트 (ReAct 방식)"""
        return f"""
User message: "{message}"

You are an intent classification expert for a trade-related AI system.

Classify the intent of the following message using the ReAct approach:

Thought: I need to analyze this message first to understand its core intent.
Action: Identify key keywords and patterns in the message.
Observation: [Message analysis results]

Thought: Based on the identified keywords and patterns, I need to classify the intent.
Action: Select the most appropriate one from 5 intent types (cargo_tracking, hscode_classification, general_chat, news_inquiry, regulatory_inquiry).
Observation: [Classification results]

Final Answer: Return the results in the following JSON format:

```json
{{
    "intent_type": "cargo_tracking|hscode_classification|general_chat|news_inquiry|regulatory_inquiry",
    "confidence_score": 0.7,
    "reasoning_steps": [
        "Thought: Message analysis results",
        "Action: Classification rationale",
        "Observation: Final conclusion"
    ],
    "extracted_entities": {{
        "key_entities": ["identified key entities"]
    }},
    "alternative_intents": [
        {{"intent": "alternative_intent", "confidence": 0.2}}
    ]
}}
```

Return only JSON:
"""

    def _get_cache_key(self, message: str) -> str:
        """캐시 키 생성 (메시지의 해시)"""
        import hashlib

        return hashlib.md5(message.encode("utf-8")).hexdigest()

    def _is_cache_valid(self, cache_entry: Dict[str, Any]) -> bool:
        """캐시 유효성 확인"""
        import time

        return time.time() - cache_entry.get("timestamp", 0) < self._cache_ttl

    async def classify_intent(self, message: str) -> IntentClassificationResult:
        """고급 프롬프트 엔지니어링 기법을 사용한 의도 분류 (캐싱 적용)"""
        # 캐시 확인
        cache_key = self._get_cache_key(message)
        if cache_key in self._cache and self._is_cache_valid(self._cache[cache_key]):
            logger.info(f"의도 분류 캐시 히트: {cache_key[:8]}...")
            cached_result = self._cache[cache_key]["result"]
            return cached_result

        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                result = await self._classify_intent_with_retry(message)

                # 결과를 캐시에 저장
                import time

                self._cache[cache_key] = {"result": result, "timestamp": time.time()}

                # 캐시 크기 제한 (최대 100개 항목)
                if len(self._cache) > 100:
                    # 가장 오래된 항목들 제거
                    sorted_cache = sorted(
                        self._cache.items(), key=lambda x: x[1]["timestamp"]
                    )
                    # 상위 50개만 유지
                    self._cache = dict(sorted_cache[-50:])

                return result

            except asyncio.CancelledError:
                logger.warning(
                    f"의도 분류 스트리밍이 취소됨 (시도 {attempt + 1}/{max_retries})"
                )
                if attempt == max_retries - 1:
                    logger.error("모든 재시도가 실패했습니다. 폴백 분류를 사용합니다.")
                    return await self._fallback_classification_with_llm(message)
                # 지수 백오프로 재시도
                delay = base_delay * (2**attempt)
                await asyncio.sleep(delay)
                continue
            except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
                logger.warning(
                    f"Anthropic API 연결 오류 (시도 {attempt + 1}/{max_retries}): {e}"
                )
                if attempt == max_retries - 1:
                    logger.error("모든 재시도가 실패했습니다. 폴백 분류를 사용합니다.")
                    return await self._fallback_classification_with_llm(message)
                delay = base_delay * (2**attempt)
                await asyncio.sleep(delay)
                continue
            except Exception as e:
                logger.error(f"의도 분류 중 예상치 못한 오류 발생: {e}", exc_info=True)
                return await self._fallback_classification_with_llm(message)

        # 모든 재시도 실패 시 폴백
        return await self._fallback_classification_with_llm(message)

    async def _classify_intent_with_retry(
        self, message: str
    ) -> IntentClassificationResult:
        """고급 프롬프트 엔지니어링 기법을 사용한 의도 분류 (재시도 로직 포함)"""
        try:
            # 1단계: Step-Back 프롬프팅으로 원칙 정의
            step_back_prompt = self._get_step_back_prompt()

            # 2단계: Chain-of-Thought 프롬프팅으로 단계별 분석
            cot_prompt = self._get_chain_of_thought_prompt(message)

            # 3단계: Self-Consistency 프롬프팅으로 다중 관점 분석
            sc_prompt = self._get_self_consistency_prompt(message)

            # 통합 프롬프트 생성
            combined_prompt = f"""
{step_back_prompt}

{cot_prompt}

{sc_prompt}

## Final Intent Classification

Combining all analyses, return the final intent classification result in JSON format:

```json
{{
    "intent_type": "cargo_tracking|hscode_classification|general_chat|news_inquiry|regulatory_inquiry",
    "confidence_score": 0.95,
    "reasoning_steps": [
        "Step 1: ...",
        "Step 2: ...",
        "Step 3: ..."
    ],
    "extracted_entities": {{
        "products": ["product names"],
        "models": ["model numbers"],
        "cargo_numbers": ["cargo numbers"],
        "hscode_keywords": ["HSCode related keywords"]
    }},
    "alternative_intents": [
        {{"intent": "alternative_intent1", "confidence": 0.15}},
        {{"intent": "alternative_intent2", "confidence": 0.10}}
    ],
    "risk_factors": [
        "Risk factors for misclassification"
    ]
}}
```

**Important decision criteria:**
1. Cargo Tracking: Must have clear cargo numbers/tracking numbers
2. HSCode Classification: Must have clear request for customs classification
3. Model name (e.g., SM-F761N) is a product identifier, not a cargo number
4. "Check" word alone does not indicate cargo tracking

Return only JSON:
"""

            # LLM 호출
            response = await self.llm.ainvoke(
                [
                    SystemMessage(
                        content="You are an intent classification expert for a trade-related AI system."
                    ),
                    HumanMessage(content=combined_prompt),
                ]
            )

            # 응답 텍스트 추출
            response_text = extract_text_from_anthropic_response(response)

            # JSON 파싱
            # 최종 의도 분류 JSON만 추출 (여러 JSON 블록 중 마지막 것)
            json_blocks = re.findall(
                r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL
            )

            if json_blocks:
                # 가장 마지막 JSON 블록을 사용 (최종 의도 분류 결과)
                json_str = json_blocks[-1]
            else:
                # 마크다운 없이 JSON이 있는 경우
                json_match = re.search(
                    r"(\{[^{}]*\"intent_type\"[^{}]*\})", response_text, re.DOTALL
                )
                if json_match:
                    json_str = json_match.group(1)
                else:
                    # 전체 JSON 객체를 찾아보기
                    json_blocks = re.findall(r"(\{.*?\})", response_text, re.DOTALL)
                    if json_blocks:
                        # intent_type이 포함된 JSON 블록 찾기
                        for json_block in reversed(json_blocks):  # 뒤에서부터 찾기
                            if '"intent_type"' in json_block:
                                json_str = json_block
                                break
                        else:
                            raise ValueError(
                                "intent_type이 포함된 JSON 블록을 찾을 수 없음"
                            )
                    else:
                        raise ValueError("JSON 형식을 찾을 수 없음")

            result_data = json.loads(json_str)

            # 필수 키 확인
            if "intent_type" not in result_data:
                logger.warning(f"intent_type이 없는 응답: {result_data}")
                return await self._fallback_classification_with_llm(message)

            # 결과 생성
            intent_type = IntentType(result_data["intent_type"])
            confidence_score = result_data.get("confidence_score", 0.5)
            reasoning_steps = result_data.get(
                "reasoning_steps", ["JSON parsing successful"]
            )
            extracted_entities = result_data.get("extracted_entities", {})

            alternative_intents = []
            for alt in result_data.get("alternative_intents", []):
                try:
                    alt_intent = IntentType(alt["intent"])
                    alt_confidence = alt["confidence"]
                    alternative_intents.append((alt_intent, alt_confidence))
                except (KeyError, ValueError):
                    continue

            logger.info(
                f"의도 분류 결과: {intent_type.value}, 신뢰도: {confidence_score:.3f}"
            )

            return IntentClassificationResult(
                intent_type=intent_type,
                confidence_score=confidence_score,
                reasoning_steps=reasoning_steps,
                extracted_entities=extracted_entities,
                alternative_intents=alternative_intents,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"JSON 파싱 오류: {e}, 폴백 분류를 사용합니다.")
            return await self._fallback_classification_with_llm(message)

    async def _fallback_classification_with_llm(
        self, message: str
    ) -> IntentClassificationResult:
        """LLM 기반 폴백 분류 (ReAct 방식)"""
        try:
            # 간단한 ReAct 프롬프트 사용
            fallback_prompt = self._get_fallback_simple_prompt(message)

            # LLM 호출
            response = await self.llm.ainvoke(
                [
                    SystemMessage(
                        content="You are an intent classification expert for a trade-related AI system. Classify simply and clearly."
                    ),
                    HumanMessage(content=fallback_prompt),
                ]
            )

            # 응답 텍스트 추출
            response_text = extract_text_from_anthropic_response(response)

            # JSON 파싱
            json_blocks = re.findall(
                r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL
            )

            if json_blocks:
                json_str = json_blocks[-1]
            else:
                # 마크다운 없이 JSON이 있는 경우
                json_match = re.search(
                    r"(\{[^{}]*\"intent_type\"[^{}]*\})", response_text, re.DOTALL
                )
                if json_match:
                    json_str = json_match.group(1)
                else:
                    # 전체 JSON 객체를 찾아보기
                    json_blocks = re.findall(r"(\{.*?\})", response_text, re.DOTALL)
                    if json_blocks:
                        # intent_type이 포함된 JSON 블록 찾기
                        for json_block in reversed(json_blocks):
                            if '"intent_type"' in json_block:
                                json_str = json_block
                                break
                        else:
                            raise ValueError("폴백 분류에서 JSON 블록을 찾을 수 없음")
                    else:
                        raise ValueError("폴백 분류에서 JSON 형식을 찾을 수 없음")

            result_data = json.loads(json_str)

            # 필수 키 확인
            if "intent_type" not in result_data:
                logger.warning(f"폴백 분류에서 intent_type이 없는 응답: {result_data}")
                return self._emergency_fallback_classification(message)

            # 결과 생성
            intent_type = IntentType(result_data["intent_type"])
            confidence_score = result_data.get("confidence_score", 0.5)
            reasoning_steps = result_data.get(
                "reasoning_steps", ["Fallback classification successful"]
            )
            extracted_entities = result_data.get("extracted_entities", {})

            alternative_intents = []
            for alt in result_data.get("alternative_intents", []):
                try:
                    alt_intent = IntentType(alt["intent"])
                    alt_confidence = alt["confidence"]
                    alternative_intents.append((alt_intent, alt_confidence))
                except (KeyError, ValueError):
                    continue

            logger.info(
                f"폴백 분류 결과: {intent_type.value}, 신뢰도: {confidence_score:.3f}"
            )

            return IntentClassificationResult(
                intent_type=intent_type,
                confidence_score=confidence_score,
                reasoning_steps=reasoning_steps,
                extracted_entities=extracted_entities,
                alternative_intents=alternative_intents,
            )

        except Exception as e:
            logger.error(f"폴백 분류 중 오류 발생: {e}", exc_info=True)
            return self._emergency_fallback_classification(message)

    def _emergency_fallback_classification(
        self, message: str
    ) -> IntentClassificationResult:
        """최종 비상 폴백 분류 (LLM 없이 기본값 반환)"""
        logger.warning(f"비상 폴백 분류 사용: {message}")

        # 기본값: 일반 채팅으로 분류
        return IntentClassificationResult(
            intent_type=IntentType.GENERAL_CHAT,
            confidence_score=0.3,
            reasoning_steps=[
                "Emergency fallback classification: Using default value due to all LLM call failures"
            ],
            extracted_entities={"emergency_fallback": True},
            alternative_intents=[],
        )

    async def is_cargo_tracking(self, message: str) -> Tuple[bool, float]:
        """화물통관 조회 의도인지 확인"""
        result = await self.classify_intent(message)
        is_cargo = result.intent_type == IntentType.CARGO_TRACKING
        confidence = result.confidence_score if is_cargo else 0.0

        if is_cargo:
            logger.info(f"화물통관 조회 의도 감지됨: 신뢰도 {confidence:.3f}")

        return is_cargo, confidence

    async def is_hscode_classification(self, message: str) -> Tuple[bool, float]:
        """HSCode 분류 의도인지 확인"""
        result = await self.classify_intent(message)
        is_hscode = result.intent_type == IntentType.HSCODE_CLASSIFICATION
        confidence = result.confidence_score if is_hscode else 0.0

        if is_hscode:
            logger.info(f"HSCode 분류 의도 감지됨: 신뢰도 {confidence:.3f}")

        return is_hscode, confidence
