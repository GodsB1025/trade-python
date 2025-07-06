-- 비관세 정보 컬럼 추가 마이그레이션
-- 작성일: 2025년 1월 7일
-- 목적: detail_page_analyses 테이블에 비관세 장벽 정보를 저장하기 위한 컬럼 추가

BEGIN;

-- detail_page_analyses 테이블에 비관세 정보 컬럼 추가
ALTER TABLE public.detail_page_analyses 
ADD COLUMN non_tariff_info jsonb DEFAULT '{}'::jsonb;

-- 비관세 정보 검색을 위한 GIN 인덱스 추가
CREATE INDEX idx_detail_page_analyses_non_tariff_info ON public.detail_page_analyses USING gin (non_tariff_info);

-- 컬럼 설명 추가
COMMENT ON COLUMN public.detail_page_analyses.non_tariff_info IS '비관세 장벽 정보 (쿼터, 라이센스, 기술규제, 위생검역, 표준화, 인증 등)';

COMMENT ON COLUMN public.detail_page_analyses.regulation_info IS '일반 규제 정보 (법적 규제, 인증 요구사항 등)';

-- 변경사항 확인
\d detail_page_analyses;

COMMIT;