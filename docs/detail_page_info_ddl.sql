-- 상세페이지 분석 결과 테이블
CREATE TABLE public.detail_page_analyses (
	id int8 GENERATED ALWAYS AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	user_id int8 NULL,
	session_uuid uuid NULL,
	session_created_at timestamp NULL,
	message_hash varchar(64) NOT NULL, -- SHA256 해시로 중복 분석 방지
	original_message text NOT NULL,
	detected_intent varchar(50) NOT NULL,
	detected_hscode varchar(20) NULL,
	confidence_score float8 DEFAULT 0.0 NOT NULL,
	processing_time_ms int4 DEFAULT 0 NOT NULL,
	analysis_source varchar(50) NOT NULL, -- 'context7', 'fallback', 'vector_search' 등
	analysis_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
	web_search_performed bool DEFAULT false NOT NULL,
	web_search_results jsonb NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT detail_page_analyses_pkey PRIMARY KEY (id),
	CONSTRAINT detail_page_analyses_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL,
	CONSTRAINT detail_page_analyses_session_fkey FOREIGN KEY (session_uuid, session_created_at) REFERENCES public.chat_sessions(session_uuid, created_at) ON DELETE SET NULL
);

-- 상세페이지 버튼 정보 테이블
CREATE TABLE public.detail_page_buttons (
	id int8 GENERATED ALWAYS AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	analysis_id int8 NOT NULL,
	button_type varchar(50) NOT NULL, -- 'HS_CODE', 'REGULATION', 'STATISTICS', 'NEWS' 등
	label varchar(200) NOT NULL,
	url varchar(500) NOT NULL,
	query_params jsonb DEFAULT '{}'::jsonb NOT NULL,
	priority int4 DEFAULT 1 NOT NULL,
	is_active bool DEFAULT true NOT NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT detail_page_buttons_pkey PRIMARY KEY (id),
	CONSTRAINT detail_page_buttons_analysis_id_fkey FOREIGN KEY (analysis_id) REFERENCES public.detail_page_analyses(id) ON DELETE CASCADE
);

-- 웹 검색 결과 캐시 테이블
CREATE TABLE public.web_search_cache (
    id int8 GENERATED ALWAYS AS IDENTITY (
        INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE
    ) NOT NULL,
    search_query_hash varchar(64) NOT NULL, -- 검색 쿼리의 SHA256 해시
    search_query text NOT NULL,
    search_type varchar(50) NOT NULL, -- 'hscode', 'regulation', 'news' 등
    search_results jsonb NOT NULL,
    result_count int4 DEFAULT 0 NOT NULL,
    search_provider varchar(50) NOT NULL, -- 'google', 'bing', 'customs_api' 등
    expires_at timestamp NOT NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT web_search_cache_pkey PRIMARY KEY (id),
    CONSTRAINT web_search_cache_query_hash_key UNIQUE (search_query_hash)
);

-- 인덱스 생성
CREATE INDEX idx_detail_page_analyses_user_session ON public.detail_page_analyses USING btree (user_id, session_uuid);

CREATE INDEX idx_detail_page_analyses_message_hash ON public.detail_page_analyses USING btree (message_hash);

CREATE INDEX idx_detail_page_analyses_intent ON public.detail_page_analyses USING btree (detected_intent);

CREATE INDEX idx_detail_page_analyses_hscode ON public.detail_page_analyses USING btree (detected_hscode)
WHERE (detected_hscode IS NOT NULL);

CREATE INDEX idx_detail_page_analyses_confidence ON public.detail_page_analyses USING btree (confidence_score)
WHERE (confidence_score >= 0.7);

CREATE INDEX idx_detail_page_analyses_source ON public.detail_page_analyses USING btree (analysis_source);

CREATE INDEX idx_detail_page_analyses_web_search ON public.detail_page_analyses USING btree (web_search_performed)
WHERE (web_search_performed = true);

CREATE INDEX idx_detail_page_analyses_metadata ON public.detail_page_analyses USING gin (analysis_metadata);

CREATE INDEX idx_detail_page_buttons_analysis_id ON public.detail_page_buttons USING btree (analysis_id);

CREATE INDEX idx_detail_page_buttons_type ON public.detail_page_buttons USING btree (button_type);

CREATE INDEX idx_detail_page_buttons_priority ON public.detail_page_buttons USING btree (priority);

CREATE INDEX idx_detail_page_buttons_active ON public.detail_page_buttons USING btree (is_active)
WHERE (is_active = true);

CREATE INDEX idx_web_search_cache_expires ON public.web_search_cache USING btree (expires_at);

CREATE INDEX idx_web_search_cache_type ON public.web_search_cache USING btree (search_type);

CREATE INDEX idx_web_search_cache_provider ON public.web_search_cache USING btree (search_provider);

CREATE INDEX idx_web_search_cache_created ON public.web_search_cache USING btree (created_at DESC);

-- 트리거 생성
CREATE TRIGGER update_detail_page_analyses_updated_at 
BEFORE UPDATE ON public.detail_page_analyses 
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();