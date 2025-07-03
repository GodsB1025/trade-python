from __future__ import annotations
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, HttpUrl


class SearchResult(BaseModel):
    """
    웹 검색 결과 단일 항목을 나타내는 모델
    """
    title: str = Field(..., description="검색 결과의 제목")
    url: HttpUrl = Field(..., description="검색 결과의 원본 URL")
    content: str = Field(..., description="검색된 문서의 내용 또는 요약")
    published_date: Optional[str] = Field(None, description="문서의 발행일 (문자열)")


class MonitoringUpdate(BaseModel):
    """
    모니터링 결과를 나타내는 구조화된 응답 모델
    """
    status: Literal["UPDATE_FOUND", "NO_UPDATE",
                    "ERROR"] = Field(..., description="모니터링 작업의 상태")
    hscode: str = Field(..., description="모니터링 대상 HSCode")
    summary: Optional[str] = Field(None, description="발견된 변경 사항에 대한 AI 요약")
    sources: List[SearchResult] = Field(
        default_factory=list, description="요약의 근거가 된 출처 목록")
    error_message: Optional[str] = Field(None, description="오류 발생 시 상세 메시지")
