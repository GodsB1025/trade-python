# HSCode 검색 기능 구현 가이드

## 개요

이 문서는 의사코드를 기반으로 구현한 HSCode 검색 기능에 대한 가이드입니다.

## 구현 완료 사항

### 1. 모델 정의 (`app/models/hscode_models.py`)
- `QueryType`: 쿼리 타입 열거형 (HSCODE_SEARCH, REGULATION_SEARCH 등)
- `ProductInfo`: 제품 정보 추출을 위한 구조화된 모델
- `HSCodeResult`: 국가별 HSCode 검색 결과
- `SearchResponse`: 최종 응답 모델

### 2. HSCode 서비스 (`app/services/hscode_service.py`)
- **쿼리 분석**: 사용자 입력에서 쿼리 타입 판별
- **제품 정보 추출**: LLM을 사용한 구조화된 정보 추출
- **정보 검증**: 필수 정보 충분성 확인
- **HSCode 검색**: 웹 검색을 통한 국가별 HSCode 조회
- **결과 캐싱**: VoyageAI 임베딩과 pgvector를 사용한 벡터 DB 저장

### 3. Chat 엔드포인트 통합 (`app/api/v1/endpoints/chat.py`)
- HSCode 쿼리 자동 감지
- 일반 채팅과 HSCode 검색 분기 처리
- SSE 스트리밍 응답 지원

## 환경 설정

### 필수 환경 변수
```bash
# AI Model API Keys
ANTHROPIC_API_KEY="your-anthropic-api-key"
VOYAGE_API_KEY="your-voyage-api-key"  # 벡터 임베딩용
TAVILY_API_KEY="your-tavily-api-key"  # 웹 검색용

# Database
DATABASE_URL="postgresql://username:password@localhost:5432/tradedb"
```

### 데이터베이스 설정
```sql
-- pgvector 확장 설치
CREATE EXTENSION IF NOT EXISTS vector;

-- hscode_vectors 테이블은 자동 생성됨 (SQLAlchemy 모델 사용)
```

## API 사용법

### HSCode 검색 요청
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "냉동 양념 족발의 HSCode를 알려줘",
    "user_id": 123
  }'
```

### 응답 형식
```json
{
  "type": "hscode_result",
  "data": {
    "success": true,
    "query_type": "HSCODE_SEARCH",
    "needs_more_info": false,
    "results": [
      {
        "country": "KR",
        "country_name": "한국",
        "hscode": "0206490000",
        "description": "냉동 돼지고기 기타",
        "confidence": 0.8
      },
      {
        "country": "CN",
        "country_name": "중국",
        "hscode": "0206490000",
        "description": "其他冻猪杂碎",
        "confidence": 0.7
      }
    ],
    "detail_buttons": [
      {
        "type": "REGULATION",
        "label": "규제 정보 상세보기",
        "url": "/regulation",
        "query_params": {"hscode": "0206490000", "country": "ALL"}
      }
    ],
    "message": "주요 수출국의 HSCode 정보입니다..."
  }
}
```

### 추가 정보 요청 응답
```json
{
  "type": "hscode_result",
  "data": {
    "success": false,
    "query_type": "HSCODE_SEARCH",
    "needs_more_info": true,
    "missing_info": ["물리적 상태", "가공 상태", "포장 형태"],
    "message": "정확한 HSCode 추천을 위해 추가 정보가 필요합니다..."
  }
}
```

## 주요 특징

### 1. 지능형 정보 추출
- LLM을 사용하여 자연어에서 구조화된 제품 정보 추출
- 제품 유형별 필수 정보 자동 판별

### 2. 다국가 HSCode 지원
- 한국(KR) 기준 우선, 주요 수출국 동시 검색
- 국가별 신뢰할 수 있는 소스 화이트리스트 관리

### 3. 벡터 검색 지원
- 검색 결과를 벡터 임베딩과 함께 저장
- 향후 유사 제품 HSCode 빠른 검색 가능

### 4. 상세 페이지 연동
- 규제 정보, 무역 통계, 화물 추적 버튼 제공
- 프론트엔드와의 원활한 연동 지원

## 에러 처리

### 정보 부족 시
- 사용자에게 구체적인 추가 정보 요청
- 예시와 함께 안내 메시지 제공

### 검색 실패 시
- 기본 HSCode 제공 (9999...)
- 낮은 신뢰도 표시

### 네트워크 오류 시
- 에러 메시지와 함께 재시도 안내

## 성능 최적화

### 1. 비동기 처리
- 모든 I/O 작업 비동기 처리
- 백그라운드 태스크로 캐싱 수행

### 2. 병렬 검색
- 여러 국가 HSCode 동시 검색
- 웹 검색 결과 병렬 처리

### 3. 캐싱 전략
- 벡터 DB를 활용한 유사 검색
- 향후 Redis 캐싱 추가 가능

## 향후 개선 사항

1. **GRI 규칙 구현**: 더 정확한 HSCode 분류를 위한 국제 규칙 적용
2. **벡터 검색 활용**: 기존 캐싱된 데이터에서 유사 제품 빠른 검색
3. **신뢰도 개선**: 머신러닝 기반 신뢰도 점수 계산
4. **다국어 지원**: 여러 언어로 HSCode 설명 제공
5. **실시간 업데이트**: 관세청 API 연동으로 실시간 정보 제공 