

### **v6.2 Redis 데이터 구조 (신뢰성 및 동시성 강화)**

### 1\. SMS 인증 시스템 (동시성 제어 강화)

```
# [기존과 동일] SMS 인증 세션 정보 (Hash)
# HINCRBY 명령어로 attemptCount를 원자적으로 증가시켜 Race Condition 방지
sms:verification:{verificationId}
 ├── userId, phoneNumber, verificationCode, attemptCount, ...
 └── TTL: 300초

# [🆕 신규] 활성 인증 세션 추적 (String)
# 특정 전화번호에 대한 동시 인증 요청을 방지하기 위함
# 키 생성 전, 이 키가 존재하는지 먼저 확인
sms:active_verification:{phoneNumber}
 ├── value: {verificationId}
 └── TTL: 300초 (인증 세션의 TTL과 동기화)

# [기존과 동일] 재발송 방지 쿨다운 (String)
sms:cooldown:{phoneNumber}
 └── TTL: 120초

# [기존과 동일] 일일 발송 한도 관리 (String)
sms:daily_limit:{phoneNumber}:{YYYYMMDD}
 └── TTL: 86400초
```

**주요 변경점:** `sms:active_verification:{phoneNumber}` 키를 추가하여, 동일한 전화번호로 동시에 여러 인증 절차가 진행되는 것을 원천적으로 차단합니다.

-----

### 2\. JWT 토큰 관리 (기존 우수 설계 유지)

```
# [기존과 동일] JWT 토큰 갱신 진행 중 상태 관리 (Hash)
# Refresh Token 갱신 시 발생하는 Race Condition 방지
jwt:refresh_in_progress:{userId}
 └── TTL: 30초

# [기존과 동일] 토큰 블랙리스트 (String)
# JTI(JWT ID)를 사용하여 명확하게 토큰을 무효화
jwt:blacklist:{tokenJti}
 └── TTL: {original_token_ttl}

# [기존과 동일] 토큰 발급 기록 (Hash)
# 어뷰징 탐지 및 모니터링
jwt:issue_log:{userId}:{YYYYMMDD}
 └── TTL: 86400초
```

**주요 변경점:** 변경 사항 없습니다. 기존 설계가 이미 훌륭하여 그대로 유지합니다.

-----

### 3\. 사이드바 캐시 관리 (키 명확성 개선)

```
# [키 형식 수정] 외부 API 호출 제한 관리 (String)
# 키의 {minute} 부분을 {YYYYMMDDHHMI} 형식으로 명확화
api:rate_limit:{api_name}:{YYYYMMDDHHMI}
 ├── value: {호출횟수}
 └── TTL: 60초
```

**주요 변경점:** 키의 마지막 시간 부분을 `YYYYMMDDHHMI` (예: `202507032102`) 형식으로 명확히 하여 오해의 소지를 없앴습니다.

-----

### 4\. 일일 알림 큐 시스템 (신뢰성 높은 큐 패턴 적용)

```
# 1. 알림 대기 큐 (List)
# Worker가 RPOPLPUSH(or BLMOVE) 명령어로 이 큐에서 처리 큐로 메시지를 가져감
daily_notification:queue:SMS
daily_notification:queue:EMAIL

# 2. [🆕 변경] 처리 중인 알림 큐 (List)
# Worker 장애 발생 시 메시지 유실을 방지하는 안전장치
# 기존 processing(Set)을 List 타입의 처리 큐로 변경
daily_notification:processing_queue:SMS
daily_notification:processing_queue:EMAIL

# 3. [기존과 동일] 알림 상세 정보 (Hash)
# 메시지 ID를 통해 실제 데이터 조회
daily_notification:detail:{id}
 └── TTL: 86400초
```
