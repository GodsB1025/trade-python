# JSON 응답 구조 상세 설계

## 📋 개요
HSCode 상세페이지 정보 준비 시스템에서 사용되는 모든 JSON 응답 구조와 데이터 스키마를 정의합니다.

## 🔄 SSE 이벤트 구조

### 1. **병렬 처리 시작 이벤트**
```json
{
  "event": "thinking",
  "data": {
    "stage": "parallel_processing_start",
    "content": "3단계 병렬 처리를 시작합니다: 자연어 응답, 상세페이지 준비, 회원 기록 저장",
    "progress": 15,
    "timestamp": "2024-01-15T10:30:00.123Z",
    "metadata": {
      "session_uuid": "550e8400-e29b-41d4-a716-446655440000",
      "user_id": 12345,
      "processing_stage": "initialization"
    }
  }
}
```

### 2. **상세페이지 버튼 준비 시작 이벤트**
```json
{
  "event": "detail_page_buttons_start",
  "data": {
    "type": "start",
    "buttonsCount": 3,
    "estimatedPreparationTime": 5000,
    "timestamp": "2024-01-15T10:30:01.456Z",
    "processingInfo": {
      "context7_enabled": true,
      "fallback_available": true,
      "cache_checked": true
    }
  }
}
```

### 3. **개별 버튼 준비 완료 이벤트**
```json
{
  "event": "detail_page_button_ready",
  "data": {
    "type": "button",
    "buttonType": "HS_CODE",
    "priority": 1,
    "url": "/detail/hscode/8517.12.00",
    "title": "HS Code 상세정보",
    "description": "관세율, 규제정보 등 상세 조회",
    "isReady": true,
    "metadata": {
      "hscode": "8517.12.00",
      "country": "KR",
      "confidence": 0.95,
      "searchTime": "2024-01-15T10:30:02.789Z",
      "analysisSource": "context7",
      "categoryInfo": {
        "chapter": "85",
        "heading": "8517",
        "subheading": "851712",
        "description": "전화기 및 기타 음성·영상·기타 자료의 송신용·수신용 기기"
      }
    },
    "actionData": {
      "queryParams": {
        "hscode": "8517.12.00",
        "source": "chat_analysis",
        "session_id": "550e8400-e29b-41d4-a716-446655440000"
      },
      "analytics": {
        "click_tracking": true,
        "conversion_target": "hscode_detail_view"
      }
    }
  }
}
```

### 4. **규제 정보 버튼 이벤트**
```json
{
  "event": "detail_page_button_ready",
  "data": {
    "type": "button",
    "buttonType": "REGULATION",
    "priority": 2,
    "url": "/regulation",
    "title": "규제 정보 상세보기",
    "description": "수출입 규제, 허가사항 등",
    "isReady": true,
    "metadata": {
      "hscode": "8517.12.00",
      "regulationTypes": ["수출규제", "인증요구사항", "라벨링"],
      "affectedCountries": ["US", "EU", "JP"],
      "riskLevel": "medium",
      "lastUpdated": "2024-01-10T15:20:00Z"
    },
    "actionData": {
      "queryParams": {
        "hscode": "8517.12.00",
        "country": "ALL",
        "regulation_type": "export"
      }
    }
  }
}
```

### 5. **무역 통계 버튼 이벤트**
```json
{
  "event": "detail_page_button_ready",
  "data": {
    "type": "button",
    "buttonType": "STATISTICS",
    "priority": 3,
    "url": "/statistics",
    "title": "무역 통계 상세보기",
    "description": "수출입 현황, 트렌드 분석",
    "isReady": true,
    "metadata": {
      "hscode": "8517.12.00",
      "statisticsAvailable": {
        "export": true,
        "import": true,
        "trends": true,
        "countries": 45
      },
      "dataRange": {
        "startDate": "2023-01-01",
        "endDate": "2024-01-15",
        "latestUpdate": "2024-01-15T00:00:00Z"
      }
    },
    "actionData": {
      "queryParams": {
        "hscode": "8517.12.00",
        "period": "latest",
        "view": "summary"
      }
    }
  }
}
```

### 6. **모든 버튼 준비 완료 이벤트**
```json
{
  "event": "detail_page_buttons_complete",
  "data": {
    "type": "complete",
    "totalPreparationTime": 4850,
    "buttonsGenerated": 3,
    "timestamp": "2024-01-15T10:30:05.306Z",
    "summary": {
      "hscode_detected": "8517.12.00",
      "confidence_score": 0.95,
      "analysis_source": "context7",
      "fallback_used": false,
      "cache_hit": false
    },
    "performance": {
      "context7_calls": 3,
      "context7_latency_ms": 2100,
      "database_queries": 2,
      "total_processing_time": 4850
    }
  }
}
```

### 7. **에러/타임아웃 이벤트**
```json
{
  "event": "detail_page_buttons_error",
  "data": {
    "type": "error",
    "errorCode": "CONTEXT7_TIMEOUT",
    "errorMessage": "Context7 API 호출 시간 초과",
    "timestamp": "2024-01-15T10:30:15.123Z",
    "fallbackActivated": true,
    "partialResults": {
      "buttonsGenerated": 1,
      "hscode_detected": null,
      "confidence_score": 0.3
    },
    "retryInfo": {
      "retryable": true,
      "retryAfter": 30,
      "maxRetries": 3
    }
  }
}
```

## 🗄️ 데이터베이스 저장 JSON 구조

### 1. **chat_messages.hscode_analysis**
```json
{
  "detected_hscode": "8517.12.00",
  "product_name": "스마트폰",
  "classification_confidence": 0.95,
  "intent_detection": {
    "primary_intent": "hscode_search",
    "secondary_intents": ["regulation_inquiry", "trade_statistics"],
    "intent_confidence": 0.87
  },
  "detail_buttons": [
    {
      "type": "HS_CODE",
      "url": "/detail/hscode/8517.12.00",
      "title": "HS Code 상세정보",
      "priority": 1,
      "generated_at": "2024-01-15T10:30:02.789Z"
    },
    {
      "type": "REGULATION",
      "url": "/regulation?hscode=8517.12.00&country=ALL",
      "title": "규제 정보 상세보기",
      "priority": 2,
      "generated_at": "2024-01-15T10:30:03.456Z"
    },
    {
      "type": "STATISTICS",
      "url": "/statistics?hscode=8517.12.00&period=latest",
      "title": "무역 통계 상세보기",
      "priority": 3,
      "generated_at": "2024-01-15T10:30:04.123Z"
    }
  ],
  "processing_metadata": {
    "analysis_timestamp": "2024-01-15T10:30:00.123Z",
    "processing_time_ms": 4850,
    "analysis_version": "v2.1.0"
  }
}
```

### 2. **chat_messages.context7_analysis**
```json
{
  "api_calls": [
    {
      "function": "resolve_library_id",
      "input": {"libraryName": "fastapi"},
      "output": {"library_id": "/tiangolo/fastapi"},
      "duration_ms": 890,
      "success": true,
      "timestamp": "2024-01-15T10:30:01.234Z"
    },
    {
      "function": "get_library_docs",
      "input": {
        "context7CompatibleLibraryID": "/tiangolo/fastapi",
        "topic": "background tasks streaming response",
        "tokens": 3000
      },
      "output": {
        "docs_retrieved": 15,
        "total_tokens": 2847,
        "relevant_snippets": 8
      },
      "duration_ms": 1650,
      "success": true,
      "timestamp": "2024-01-15T10:30:02.124Z"
    }
  ],
  "analysis_results": {
    "hscode_patterns_found": ["8517.12.00"],
    "context7_confidence": 0.85,
    "documentation_relevance": 0.78,
    "extracted_insights": [
      "FastAPI StreamingResponse 패턴 확인",
      "백그라운드 태스크 처리 방법 습득",
      "SSE 이벤트 구조 검증"
    ]
  },
  "performance": {
    "total_api_calls": 2,
    "total_duration_ms": 2540,
    "success_rate": 1.0,
    "tokens_consumed": 2847,
    "cache_hits": 0,
    "error_count": 0
  }
}
```

### 3. **chat_messages.sse_bookmark_data**
```json
{
  "bookmark_available": true,
  "bookmark_type": "HS_CODE",
  "target_value": "8517.12.00",
  "display_name": "스마트폰 (HS Code 8517.12.00)",
  "sse_generated": true,
  "generation_metadata": {
    "generated_at": "2024-01-15T10:30:05.306Z",
    "button_priority": 1,
    "confidence_threshold_met": true,
    "user_eligible": true
  },
  "bookmark_config": {
    "auto_monitoring": true,
    "notification_types": ["regulation_changes", "statistics_updates"],
    "default_settings": {
      "sms_enabled": false,
      "email_enabled": true
    }
  }
}
```

### 4. **chat_messages.parallel_task_metrics**
```json
{
  "task_execution": {
    "task_a": {
      "name": "ai_response_generation",
      "start_time": "2024-01-15T10:30:00.123Z",
      "end_time": "2024-01-15T10:30:08.456Z",
      "duration_ms": 8333,
      "status": "completed",
      "tokens_generated": 487
    },
    "task_b": {
      "name": "detail_page_preparation",
      "start_time": "2024-01-15T10:30:00.156Z",
      "end_time": "2024-01-15T10:30:05.006Z",
      "duration_ms": 4850,
      "status": "completed",
      "context7_calls": 2,
      "fallback_used": false
    },
    "task_c": {
      "name": "chat_history_saving",
      "start_time": "2024-01-15T10:30:00.178Z",
      "end_time": "2024-01-15T10:30:01.234Z",
      "duration_ms": 1056,
      "status": "completed",
      "db_operations": 3
    }
  },
  "performance_analysis": {
    "total_wall_clock_time": 8333,
    "parallel_efficiency": 0.58,
    "bottleneck_task": "task_a",
    "resource_utilization": {
      "cpu_peak": "45%",
      "memory_peak": "128MB",
      "network_calls": 5
    }
  },
  "optimization_suggestions": [
    "AI 응답 생성이 병목점으로 확인됨",
    "Context7 호출 최적화 가능",
    "캐싱 도입으로 성능 개선 예상"
  ]
}
```

## 🔧 클라이언트 요청/응답 구조

### 1. **채팅 요청 (기존 유지)**
```json
{
  "user_id": 12345,
  "session_uuid": "550e8400-e29b-41d4-a716-446655440000",
  "message": "아이폰 15 프로의 HS Code가 뭐야?"
}
```

### 2. **Context7 분석 결과 (내부 사용)**
```json
{
  "analysis_successful": true,
  "hscode_candidates": [
    {
      "code": "8517.12.00",
      "confidence": 0.95,
      "description": "휴대용 무선전화기",
      "source": "context7_analysis"
    },
    {
      "code": "8517.11.00",
      "confidence": 0.23,
      "description": "유선전화기",
      "source": "fallback_pattern_matching"
    }
  ],
  "context7_metadata": {
    "library_docs_used": ["/tiangolo/fastapi", "/pydantic/pydantic"],
    "total_tokens": 2847,
    "processing_time": 2540,
    "api_calls": 2
  },
  "quality_score": 0.87
}
```

## 📊 에러 응답 구조

### 1. **Context7 API 오류**
```json
{
  "event": "detail_page_buttons_error",
  "data": {
    "type": "context7_api_error",
    "errorCode": "CONTEXT7_API_FAILURE",
    "errorMessage": "Context7 서비스 일시적 장애",
    "timestamp": "2024-01-15T10:30:30.123Z",
    "errorDetails": {
      "api_endpoint": "resolve_library_id",
      "http_status": 503,
      "retry_after": 60
    },
    "fallback_status": {
      "activated": true,
      "fallback_type": "pattern_matching",
      "reduced_confidence": true
    },
    "impact_assessment": {
      "user_experience": "degraded",
      "feature_availability": "partial",
      "expected_recovery": "< 5 minutes"
    }
  }
}
```

### 2. **HSCode 감지 실패**
```json
{
  "event": "detail_page_buttons_error",
  "data": {
    "type": "hscode_detection_failed",
    "errorCode": "NO_HSCODE_DETECTED",
    "errorMessage": "메시지에서 HSCode 관련 정보를 찾을 수 없습니다",
    "timestamp": "2024-01-15T10:30:15.789Z",
    "analysis_attempted": {
      "context7_analysis": true,
      "pattern_matching": true,
      "keyword_extraction": true
    },
    "suggestions": [
      "구체적인 제품명을 포함해 주세요",
      "HSCode 번호를 직접 입력해 보세요",
      "제품의 용도나 재질을 명시해 주세요"
    ],
    "fallback_options": {
      "general_trade_info": true,
      "manual_search_guide": true,
      "contact_support": true
    }
  }
}
```

## 🔄 상태 관리 구조

### 1. **버튼 생성 상태 추적**
```json
{
  "button_generation_state": {
    "session_uuid": "550e8400-e29b-41d4-a716-446655440000",
    "current_stage": "context7_analysis",
    "progress_percentage": 65,
    "stages_completed": [
      "intent_detection",
      "hscode_extraction",
      "context7_library_resolution"
    ],
    "stages_remaining": [
      "context7_docs_analysis",
      "button_generation",
      "sse_event_publishing"
    ],
    "estimated_completion": "2024-01-15T10:30:07.000Z"
  }
}
```

## 📋 다음 단계

1. **구현 일정 및 마일스톤** (4단계 문서)
2. **테스트 전략 및 검증 방법** (5단계 문서)
3. **배포 및 모니터링 계획** (6단계 문서)
4. **성능 최적화 및 튜닝 가이드** (7단계 문서) 