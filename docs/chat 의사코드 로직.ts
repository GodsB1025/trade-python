// 무역 정보 레이더 시스템 - HScode 검색 의사코드
//
// 접근 방식:
// 1. 국제 표준 HS 6자리를 먼저 결정 (GRI 규칙 적용)
// 2. 각 국가별로 6자리를 해당 국가의 전체 코드로 매핑 (웹 검색 활용)
//
// 장점:
// - HS 6자리는 전 세계 공통이므로 한 번만 결정하면 됨
// - 각 국가별 매핑은 Claude의 웹 검색으로 효율적으로 처리 가능
// - 실무에서 사용하는 방식과 동일

// 타입 정의

// --- [추가된 부분 시작] ---
// 의사코드 실행을 위한 외부 모듈 및 클라이언트 정의 (가상)

// VoyageAI 임베딩 모델 클라이언트 (가상)
// 실제 환경에서는 VoyageAI 라이브러리를 import하여 사용합니다.

type QueryType =
  | "HSCODE_SEARCH"
  | "REGULATION_SEARCH"
  | "STATISTICS_SEARCH"
  | "SHIPMENT_TRACKING";

type ProductInfo = {
  name?: string;
  physicalState?: "냉동" | "냉장" | "상온" | "건조" | "액체" | "고체";
  processingState?: "원료" | "반가공" | "완제품";
  packagingType?: string;
  materials?: string[];
  usage?: string;
  weight?: number;
  dimensions?: { length: number; width: number; height: number };
  additionalInfo?: string;
};

type CountryCode = "CN" | "US" | "VN" | "HK" | "TW" | "JP" | "EU" | "OTHER";

type HSCodeResult = {
  country: CountryCode;
  countryName: string;
  hsCode: string;
  description: string;
  confidence: number;
};

type SearchResponse = {
  success: boolean;
  queryType: QueryType;
  needsMoreInfo: boolean;
  missingInfo?: string[];
  results?: HSCodeResult[];
  detailButtons?: DetailButton[];
  message: string;
};

type DetailButton = {
  type: "REGULATION" | "STATISTICS" | "SHIPMENT_TRACKING";
  label: string;
  url: string;
  queryParams: Record<string, string>;
};

// 주요 수출국 목록
const MAJOR_EXPORT_COUNTRIES: Record<CountryCode, string> = {
  CN: "중국",
  US: "미국",
  VN: "베트남",
  HK: "홍콩",
  TW: "대만",
};

// HScode 판단을 위한 필수 정보 체크리스트
const REQUIRED_INFO_CHECKLIST = {
  basic: ["name", "physicalState", "processingState"],
  material: ["materials"],
  usage: ["usage"],
  packaging: ["packagingType"],
};

// 메인 검색 함수
async function searchHSCode(userQuery: string): Promise<SearchResponse> {
  try {
    // 1단계: 쿼리 타입 분석
    const queryType = analyzeQueryType(userQuery);

    // 2단계: 자연어에서 제품 정보 추출
    const extractedInfo = await extractProductInfo(userQuery);

    // 3단계: 정보 충분성 검증
    const validationResult = validateProductInfo(extractedInfo);

    if (!validationResult.isComplete) {
      return {
        success: false,
        queryType,
        needsMoreInfo: true,
        missingInfo: validationResult.missingFields,
        message: generateInfoRequestMessage(
          validationResult.missingFields,
          extractedInfo.name
        ),
      };
    }

    // 4단계: 멀티스텝 추론으로 HScode 결정
    const hsCodes = await determineHSCode(extractedInfo);

    // 5단계: 상세 페이지 버튼 생성
    const detailButtons = generateDetailButtons(hsCodes, queryType);

    // 6단계: 응답 생성
    const finalResponse = generateResponse(queryType, hsCodes, detailButtons);

    // --- [추가된 부분 시작] ---
    // 7단계: 결과 캐싱 (비동기 "Fire-and-Forget")
    // 사용자에게 응답을 지연시키지 않기 위해 await를 **사용하지 않고** 백그라운드에서 작업을 시작합니다.
    // 실제 프로덕션 환경에서는 이 부분을 메시지 큐(e.g., RabbitMQ, SQS)나
    // 별도의 워커 스레드로 분리하여 안정성을 높이는 것이 좋습니다.
    cacheHSCodeResultWithEmbedding(userQuery, extractedInfo, hsCodes);
    // --- [추가된 부분 끝] ---

    return finalResponse;
  } catch (error) {
    return {
      success: false,
      queryType: "HSCODE_SEARCH",
      needsMoreInfo: false,
      message: "처리 중 오류가 발생했습니다. 다시 시도해주세요.",
    };
  }
}

// --- [추가된 부분 시작] ---
/**
 * HSCode 검색 결과를 벡터 임베딩과 함께 데이터베이스에 캐싱합니다.
 * hscode_vectors 테이블에 결과를 저장(UPSERT)합니다.
 * @param userQuery - 사용자의 원본 자연어 질문
 * @param productInfo - LLM이 추출한 구조화된 제품 정보
 * @param hscodeResults - 검색된 HSCode 결과 목록
 */
async function cacheHSCodeResultWithEmbedding(
  userQuery: string,
  productInfo: ProductInfo,
  hscodeResults: HSCodeResult[]
): Promise<void> {
  // 신뢰도가 가장 높고 기준이 되는 한국(KR) 코드를 캐싱 대상으로 선택합니다.
  const primaryResult =
    hscodeResults.find((r) => r.country === "KR") || hscodeResults[0];

  if (!primaryResult) {
    console.log("[Cache Logic] 캐싱할 유효한 HSCode 결과가 없습니다.");
    return;
  }

  try {
    // 1. 임베딩 생성을 위한 풍부한 컨텍스트의 텍스트 데이터 생성
    const textToEmbed = `제품명: ${productInfo.name}, 물리적 상태: ${
      productInfo.physicalState
    }, 가공 상태: ${
      productInfo.processingState
    }, 원재료: ${productInfo.materials?.join(", ")}, 상세 설명: ${
      primaryResult.description
    }, 사용자 질문: ${userQuery}`;

    // 2. VoyageAI 모델을 사용하여 벡터 임베딩 생성
    const embeddingVector = await voyageAIEmbeddingModel.embedQuery(
      textToEmbed
    );

    // 3. hscode_vectors 테이블에 저장하기 위한 SQL 쿼리 (UPSERT)
    // ON CONFLICT 구문을 사용하여 hscode가 이미 존재하면 데이터를 업데이트합니다.
    const sqlQuery = `
      INSERT INTO public.hscode_vectors (
          hscode, product_name, description, embedding, metadata, 
          confidence_score, classification_basis, web_search_context, verified
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
      ON CONFLICT (hscode) DO UPDATE SET
          product_name = EXCLUDED.product_name,
          description = EXCLUDED.description,
          embedding = EXCLUDED.embedding,
          metadata = EXCLUDED.metadata,
          confidence_score = EXCLUDED.confidence_score,
          updated_at = CURRENT_TIMESTAMP;
    `;

    const params = [
      primaryResult.hsCode,
      productInfo.name,
      primaryResult.description,
      `[${embeddingVector.join(",")}]`, // pgvector 형식에 맞게 문자열로 변환
      JSON.stringify(productInfo), // ProductInfo 객체 전체를 JSONB 메타데이터로 저장
      primaryResult.confidence,
      "LLM analysis based on user query", // 분류 근거
      userQuery, // 웹 검색 컨텍스트
      false, // 아직 검증되지 않은 상태
    ];

    // 4. 데이터베이스 클라이언트를 통해 쿼리 실행
    await dbClient.query(sqlQuery, params);
  } catch (error) {
    console.error("[Cache Logic] HSCode 캐싱 중 오류 발생:", error);
  }
}
// --- [추가된 부분 끝] ---

// 쿼리 타입 분석
function analyzeQueryType(query: string): QueryType {
  const lowerQuery = query.toLowerCase();

  if (lowerQuery.includes("규제") || lowerQuery.includes("regulation")) {
    return "REGULATION_SEARCH";
  } else if (lowerQuery.includes("통계") || lowerQuery.includes("statistics")) {
    return "STATISTICS_SEARCH";
  } else if (lowerQuery.includes("추적") || lowerQuery.includes("tracking")) {
    return "SHIPMENT_TRACKING";
  }

  return "HSCODE_SEARCH";
}

// 제품 정보 추출 (LLM 활용)
async function extractProductInfo(query: string): Promise<ProductInfo> {
  // LLM을 사용하여 자연어에서 구조화된 정보 추출
  const prompt = `
    다음 쿼리에서 제품 정보를 추출하세요:
    쿼리: ${query}
    
    추출할 정보:
    - 제품명
    - 물리적 상태 (냉동/냉장/상온/건조/액체/고체)
    - 가공 상태 (원료/반가공/완제품)
    - 포장 형태
    - 원재료 구성
    - 용도
    - 중량 및 규격
    
    JSON 형식으로 반환하세요.
  `;

  // LLM 호출 (실제 구현에서는 API 호출)
  return await callLLM(prompt);
}

// 정보 충분성 검증
function validateProductInfo(info: ProductInfo): {
  isComplete: boolean;
  missingFields: string[];
} {
  const missingFields: string[] = [];

  // 기본 정보 확인
  if (!info.name) missingFields.push("제품명");
  if (!info.physicalState) missingFields.push("물리적 상태");
  if (!info.processingState) missingFields.push("가공 상태");

  // 특정 제품에 따른 추가 정보 확인
  if (isFood(info.name)) {
    if (!info.materials || info.materials.length === 0) {
      missingFields.push("원재료 구성");
    }
    if (!info.packagingType) {
      missingFields.push("포장 형태");
    }
  }

  if (isElectronics(info.name)) {
    if (!info.usage) {
      missingFields.push("용도");
    }
  }

  return {
    isComplete: missingFields.length === 0,
    missingFields,
  };
}

// HScode 결정 (각 국가별로 GRI 규칙 적용)
async function determineHSCode(
  productInfo: ProductInfo
): Promise<HSCodeResult[]> {
  const results: HSCodeResult[] = [];

  // 각 국가별 관세청 소스 정의
  const countrySpecificSources = {
    KR: ["customs.go.kr", "kita.net"], // 한국
    CN: ["customs.gov.cn", "ccpit.org"], // 중국
    US: ["usitc.gov", "cbp.gov"], // 미국
    VN: ["customs.gov.vn"], // 베트남
    HK: ["customs.gov.hk"], // 홍콩
    TW: ["customs.mof.gov.tw"], // 대만
  };

  // 한국 HSK 코드 먼저 결정 (기준)
  const koreaHSCode = await determineCountryHSCode(
    productInfo,
    "KR",
    countrySpecificSources.KR
  );

  if (koreaHSCode) {
    results.push({
      country: "KR" as CountryCode,
      countryName: "한국",
      hsCode: koreaHSCode.code,
      description: koreaHSCode.description,
      confidence: koreaHSCode.confidence,
    });
  }

  // 주요 수출국별로 각각 GRI 규칙 적용하여 HScode 결정
  for (const [countryCode, countryName] of Object.entries(
    MAJOR_EXPORT_COUNTRIES
  )) {
    const sources =
      countrySpecificSources[
        countryCode as keyof typeof countrySpecificSources
      ];

    const countryHSCode = await determineCountryHSCode(
      productInfo,
      countryCode as CountryCode,
      sources
    );

    if (countryHSCode) {
      results.push({
        country: countryCode as CountryCode,
        countryName,
        hsCode: countryHSCode.code,
        description: countryHSCode.description,
        confidence: countryHSCode.confidence,
      });
    }
  }

  return results;
}

// HScode 결정 (국제 표준 6자리 먼저 결정 후 국가별 매핑)
async function determineHSCode(
  productInfo: ProductInfo
): Promise<HSCodeResult[]> {
  const results: HSCodeResult[] = [];

  // 1단계: 국제 표준 HS 6자리 코드 결정 (GRI 규칙 적용)
  const internationalHS6 = await determineInternationalHS6(productInfo);

  if (!internationalHS6) {
    throw new Error("국제 HS 코드를 결정할 수 없습니다.");
  }

  // 2단계: 각 국가별로 6자리 HS를 해당 국가의 전체 코드로 매핑
  for (const [countryCode, countryName] of Object.entries(
    MAJOR_EXPORT_COUNTRIES
  )) {
    const countrySpecificCode = await mapHS6ToCountryCode(
      internationalHS6,
      countryCode as CountryCode,
      productInfo
    );

    if (countrySpecificCode) {
      results.push({
        country: countryCode as CountryCode,
        countryName,
        hsCode: countrySpecificCode.code,
        description: countrySpecificCode.description,
        confidence: countrySpecificCode.confidence,
      });
    }
  }

  // 한국 HSK 코드도 추가 (기준으로 사용)
  const koreaHSK = await mapHS6ToCountryCode(
    internationalHS6,
    "KR",
    productInfo
  );
  if (koreaHSK) {
    results.unshift({
      country: "KR" as CountryCode,
      countryName: "한국",
      hsCode: koreaHSK.code,
      description: koreaHSK.description,
      confidence: koreaHSK.confidence,
    });
  }

  return results;
}

// 국제 표준 HS 6자리 결정
async function determineInternationalHS6(
  productInfo: ProductInfo
): Promise<string> {
  // WCO 표준 및 신뢰할 수 있는 국제 소스 사용
  const internationalSources = [
    "wcoomd.org", // 세계관세기구
    "trade.gov", // 미국 무역부
    "customs.go.kr", // 한국 관세청
    "tariffdata.wto.org", // WTO 관세 데이터
  ];

  // GRI 규칙을 국제 표준 레벨에서 적용
  const hs6Code = await applyGRIRules(productInfo, internationalSources);

  // 6자리로 정규화 (일부 소스는 더 긴 코드를 반환할 수 있음)
  return hs6Code.substring(0, 6);
}

// HS 6자리를 국가별 전체 코드로 매핑
async function mapHS6ToCountryCode(
  hs6: string,
  countryCode: CountryCode | "KR",
  productInfo: ProductInfo
): Promise<{ code: string; description: string; confidence: number } | null> {
  try {
    // 각 국가의 자릿수
    const countryDigits = {
      KR: 10, // 한국 HSK
      CN: 10, // 중국 (+ CIQ 3자리 추가 가능)
      US: 10, // 미국 HTS
      VN: 8, // 베트남
      HK: 8, // 홍콩
      TW: 11, // 대만
      JP: 9, // 일본
    };

    // 웹 검색으로 해당 국가의 전체 코드 찾기
    const searchQuery = `${hs6} ${
      productInfo.name
    } ${countryCode} tariff code ${
      countryCode === "US"
        ? "HTS"
        : countryCode === "KR"
        ? "HSK"
        : "customs code"
    }`;

    const countryCode = await searchCountrySpecificCode(
      searchQuery,
      hs6,
      countryCode,
      productInfo
    );

    return countryCode;
  } catch (error) {
    console.error(`Error mapping HS6 to ${countryCode} code:`, error);
    return null;
  }
}

// GRI 규칙 적용 (국제 표준 레벨)
async function applyGRIRules(
  productInfo: ProductInfo,
  sources: string[]
): Promise<string> {
  // GRI 1: 제목과 법적 주석에 따른 분류
  let classification = await applyGRI1(productInfo, sources);

  if (!classification) {
    // GRI 2: 미완성품 및 혼합물 처리
    classification = await applyGRI2(productInfo, sources);
  }

  if (!classification) {
    // GRI 3: 복수 분류 가능한 경우
    classification = await applyGRI3(productInfo, sources);
  }

  if (!classification) {
    // GRI 4: 유사 제품으로 분류
    classification = await applyGRI4(productInfo, sources);
  }

  // GRI 5: 포장 관련 규칙
  if (classification) {
    classification = await applyGRI5(classification, productInfo);
  }

  // GRI 6: 소호 레벨 분류 (6자리까지)
  if (classification) {
    classification = await applyGRI6(classification, productInfo);
  }

  return classification;
}

// 추가 정보 요청 메시지 생성
function generateInfoRequestMessage(
  missingFields: string[],
  productName?: string
): string {
  let message = `정확한 HScode 추천을 위해 추가 정보가 필요합니다.\n\n`;

  if (productName) {
    message += `"${productName}"에 대한 다음 정보를 제공해주세요:\n`;
  } else {
    message += `다음 정보를 제공해주세요:\n`;
  }

  missingFields.forEach((field, index) => {
    message += `${index + 1}. ${field}\n`;
  });

  message += `\n예시: "냉동 양념 족발, 진공포장, 1kg, 돼지고기 100%"`;

  return message;
}

// 상세 페이지 버튼 생성
function generateDetailButtons(
  hsCodes: HSCodeResult[],
  queryType: QueryType
): DetailButton[] {
  const buttons: DetailButton[] = [];

  // 기본 HScode로 첫 번째 결과 사용 (한국 기준)
  const primaryHSCode = hsCodes[0]?.hsCode || "";

  buttons.push({
    type: "REGULATION",
    label: "규제 정보 상세보기",
    url: "/regulation",
    queryParams: {
      hscode: primaryHSCode,
      country: "ALL",
    },
  });

  buttons.push({
    type: "STATISTICS",
    label: "무역 통계 상세보기",
    url: "/statistics",
    queryParams: {
      hscode: primaryHSCode,
      period: "latest",
    },
  });

  buttons.push({
    type: "SHIPMENT_TRACKING",
    label: "화물 추적 정보",
    url: "/tracking",
    queryParams: {
      hscode: primaryHSCode,
    },
  });

  return buttons;
}

// 최종 응답 생성
function generateResponse(
  queryType: QueryType,
  hsCodes: HSCodeResult[],
  buttons: DetailButton[]
): SearchResponse {
  let message = "";

  if (queryType === "HSCODE_SEARCH") {
    message = `주요 수출국의 HScode 정보입니다:\n\n`;
    hsCodes.forEach((result) => {
      message += `${result.countryName}: ${result.hsCode} - ${result.description}\n`;
    });
    message += `\n다른 국가에 대한 HScode 정보를 보시려면 정확한 수입 국가를 입력해주세요.`;
  } else if (queryType === "REGULATION_SEARCH") {
    message = `해당 제품의 HScode를 확인했습니다.\n규제 정보를 확인하려면 아래 상세 페이지 버튼을 클릭해주세요.`;
  }

  message += `\n\n이 HScode에 대한 규제, 통계 상세 정보를 보려면 아래의 상세 페이지로 가는 버튼들을 클릭해주세요.`;

  return {
    success: true,
    queryType,
    needsMoreInfo: false,
    results: hsCodes,
    detailButtons: buttons,
    message,
  };
}

// 헬퍼 함수들
function isFood(productName?: string): boolean {
  if (!productName) return false;
  const foodKeywords = ["족발", "김치", "고기", "과일", "야채", "음식", "식품"];
  return foodKeywords.some((keyword) => productName.includes(keyword));
}

function isElectronics(productName?: string): boolean {
  if (!productName) return false;
  const electronicsKeywords = ["전자", "반도체", "컴퓨터", "모니터", "배터리"];
  return electronicsKeywords.some((keyword) => productName.includes(keyword));
}

// 웹 검색으로 국가별 코드 찾기
async function searchCountrySpecificCode(
  searchQuery: string,
  hs6Base: string,
  countryCode: CountryCode | "KR",
  productInfo: ProductInfo
): Promise<{ code: string; description: string; confidence: number } | null> {
  try {
    // 국가별 신뢰할 수 있는 소스
    const trustedSources = {
      KR: ["customs.go.kr", "kita.net", "tradenavi.or.kr"],
      CN: ["customs.gov.cn", "ccpit.org", "english.customs.gov.cn"],
      US: ["usitc.gov", "cbp.gov", "hts.usitc.gov"],
      VN: ["customs.gov.vn", "vcci.com.vn"],
      HK: ["customs.gov.hk", "tid.gov.hk"],
      TW: ["customs.mof.gov.tw", "trade.gov.tw"],
      JP: ["customs.go.jp", "jetro.go.jp"],
    };

    // Claude의 웹 검색 기능을 활용하여 정확한 코드 찾기
    // 화이트리스트 기반으로 신뢰할 수 있는 소스에서만 검색
    const searchPrompt = `
      Find the exact tariff code for "${productInfo.name}" in ${countryCode}
      Starting with HS6: ${hs6Base}
      Search only from: ${trustedSources[countryCode]?.join(", ")}
      
      Product details:
      - Physical state: ${productInfo.physicalState}
      - Processing state: ${productInfo.processingState}
      - Materials: ${productInfo.materials?.join(", ")}
      - Packaging: ${productInfo.packagingType}
    `;

    const result = await performWebSearch(
      searchPrompt,
      trustedSources[countryCode]
    );

    if (result) {
      return {
        code: result.code,
        description: result.description,
        confidence: calculateSearchConfidence(result, hs6Base),
      };
    }

    // 검색 실패 시 6자리 HS + 기본 확장
    return {
      code: hs6Base + getDefaultExtension(countryCode),
      description: `기본 분류 - ${productInfo.name}`,
      confidence: 0.5,
    };
  } catch (error) {
    console.error(`Search failed for ${countryCode}:`, error);
    return null;
  }
}

// 국가별 기본 확장 자릿수
function getDefaultExtension(countryCode: CountryCode | "KR"): string {
  const extensions = {
    KR: "0000", // 한국 10자리
    CN: "0000", // 중국 10자리
    US: "0000", // 미국 10자리
    VN: "00", // 베트남 8자리
    HK: "00", // 홍콩 8자리
    TW: "00000", // 대만 11자리
    JP: "000", // 일본 9자리
  };

  return extensions[countryCode] || "00";
}

// 검색 결과 신뢰도 계산
function calculateSearchConfidence(result: any, expectedHS6: string): number {
  let confidence = 0.5;

  // HS6가 일치하면 신뢰도 증가
  if (result.code.startsWith(expectedHS6)) {
    confidence += 0.3;
  }

  // 공식 소스에서 나온 결과면 신뢰도 증가
  if (result.isOfficial) {
    confidence += 0.2;
  }

  return Math.min(confidence, 1.0);
}

// LLM 호출 함수 (실제 구현 필요)
async function callLLM(prompt: string): Promise<any> {
  // Claude API 호출하여 응답 받기
  // 실제 구현에서는 API 키, 엔드포인트 등 설정 필요
  return {};
}

// 실제 웹 검색 수행
async function performWebSearch(
  searchPrompt: string,
  trustedSources: string[]
): Promise<any> {
  // Claude의 웹 검색 API 활용
  // 화이트리스트 소스에서만 검색하도록 제한

  const searchResults = await claude.webSearch({
    query: searchPrompt,
    sources: trustedSources,
    maxResults: 10,
  });

  // 검색 결과에서 가장 신뢰할 수 있는 코드 추출
  for (const result of searchResults) {
    const code = extractTariffCode(result.content);
    const description = extractDescription(result.content);

    if (code && isValidCode(code)) {
      return {
        code,
        description,
        isOfficial: trustedSources.includes(result.source),
        source: result.source,
      };
    }
  }

  return null;
}

// 텍스트에서 관세 코드 추출
function extractTariffCode(content: string): string | null {
  // 국가별 코드 패턴
  const patterns = [
    /\b\d{10}\b/, // 10자리 (한국, 중국, 미국)
    /\b\d{8}\b/, // 8자리 (베트남, 홍콩)
    /\b\d{11}\b/, // 11자리 (대만)
    /\b\d{9}\b/, // 9자리 (일본)
  ];

  for (const pattern of patterns) {
    const match = content.match(pattern);
    if (match) {
      return match[0];
    }
  }

  return null;
}

// 코드 유효성 검증
function isValidCode(code: string): boolean {
  // 기본 검증: 숫자로만 구성, 적절한 길이
  return /^\d{8,11}$/.test(code);
}

// 설명 추출
function extractDescription(content: string): string {
  // 코드 주변의 설명 텍스트 추출
  // 실제 구현에서는 더 정교한 파싱 필요
  return content.substring(0, 100);
}

// GRI 규칙 구현 함수들
async function applyGRI1(
  productInfo: ProductInfo,
  sources: string[]
): Promise<string | null> {
  // GRI 1: 섹션, 챕터, 헤딩의 용어와 관련 노트에 따른 분류
  // 제품명이 특정 헤딩에 정확히 매칭되는지 확인

  const searchQuery = `"${productInfo.name}" HScode classification heading`;
  const results = await searchTrustedSources(searchQuery, sources);

  // 정확한 매칭이 있으면 해당 코드 반환
  if (results.exactMatch) {
    return results.hsCode;
  }

  return null;
}

async function applyGRI2(
  productInfo: ProductInfo,
  sources: string[]
): Promise<string | null> {
  // GRI 2: 미완성품, 미조립품, 혼합물 처리

  // 2(a): 미완성품이지만 완성품의 본질적 특성을 가진 경우
  if (productInfo.processingState === "반가공") {
    const completeProductCode = await findCompleteProductCode(
      productInfo,
      sources
    );
    if (completeProductCode) {
      return completeProductCode;
    }
  }

  // 2(b): 혼합물이나 복합물의 경우
  if (productInfo.materials && productInfo.materials.length > 1) {
    return await classifyMixture(productInfo, sources);
  }

  return null;
}

async function applyGRI3(
  productInfo: ProductInfo,
  sources: string[]
): Promise<string | null> {
  // GRI 3: 두 개 이상의 헤딩에 분류 가능한 경우

  // 3(a): 가장 구체적인 설명을 제공하는 헤딩 선택
  const possibleHeadings = await findPossibleHeadings(productInfo, sources);
  if (possibleHeadings.length > 1) {
    return selectMostSpecificHeading(possibleHeadings);
  }

  // 3(b): 본질적 특성에 따른 분류
  if (possibleHeadings.length > 1) {
    return classifyByEssentialCharacter(productInfo, possibleHeadings);
  }

  // 3(c): 마지막 순서의 헤딩 선택
  if (possibleHeadings.length > 1) {
    return possibleHeadings[possibleHeadings.length - 1];
  }

  return null;
}

async function applyGRI4(
  productInfo: ProductInfo,
  sources: string[]
): Promise<string | null> {
  // GRI 4: 앞선 규칙으로 분류할 수 없는 경우, 가장 유사한 물품으로 분류

  const similarProducts = await findSimilarProducts(productInfo, sources);
  if (similarProducts.length > 0) {
    return similarProducts[0].hsCode;
  }

  return null;
}

async function applyGRI5(
  classification: string,
  productInfo: ProductInfo
): Promise<string> {
  // GRI 5: 포장재 및 포장용기 관련 규칙

  // 5(a): 특정 물품을 담기 위해 특별히 제작된 용기는 해당 물품과 함께 분류
  // 5(b): 일반적인 포장재는 내용물과 함께 분류

  if (
    productInfo.packagingType &&
    isSpecialPackaging(productInfo.packagingType)
  ) {
    // 특수 포장의 경우 별도 고려 필요
    return await adjustForSpecialPackaging(
      classification,
      productInfo.packagingType
    );
  }

  return classification;
}

async function applyGRI6(
  classification: string,
  productInfo: ProductInfo
): Promise<string> {
  // GRI 6: 소호(subheading) 레벨에서의 분류
  // 4자리 헤딩이 결정된 후, 6자리 소호를 결정

  if (classification.length === 4) {
    const subheading = await determineSubheading(classification, productInfo);
    return classification + subheading;
  }

  return classification;
}

// 신뢰할 수 있는 소스 검색
async function searchTrustedSources(
  query: string,
  sources: string[]
): Promise<any> {
  // 실제 구현에서는 웹 검색 API 사용
  // 각 소스별로 검색하고 결과 통합
  return {
    exactMatch: false,
    hsCode: null,
    confidence: 0,
  };
}

// 헬퍼 함수들 (실제 구현 필요)
async function findCompleteProductCode(
  info: ProductInfo,
  sources: string[]
): Promise<string | null> {
  return null;
}

async function classifyMixture(
  info: ProductInfo,
  sources: string[]
): Promise<string | null> {
  return null;
}

async function findPossibleHeadings(
  info: ProductInfo,
  sources: string[]
): Promise<string[]> {
  return [];
}

function selectMostSpecificHeading(headings: string[]): string {
  return headings[0];
}

function classifyByEssentialCharacter(
  info: ProductInfo,
  headings: string[]
): string {
  return headings[0];
}

async function findSimilarProducts(
  info: ProductInfo,
  sources: string[]
): Promise<any[]> {
  return [];
}

function isSpecialPackaging(packagingType: string): boolean {
  const specialTypes = ["진공포장", "냉동포장", "특수용기"];
  return specialTypes.includes(packagingType);
}

async function adjustForSpecialPackaging(
  code: string,
  packagingType: string
): Promise<string> {
  return code;
}

async function determineSubheading(
  heading: string,
  info: ProductInfo
): Promise<string> {
  return "00";
}
