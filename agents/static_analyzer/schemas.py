"""
StaticAnalyzer Pydantic schemas

정적 분석 에이전트의 입출력 스키마 정의
"""

from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Any, Optional
from pathlib import Path
from shared.schemas.common import BaseContext, BaseResponse


class StaticAnalyzerContext(BaseContext):
    """
    StaticAnalyzer 입력 스키마

    코드 정적 분석을 위한 컨텍스트
    """
    repo_path: str = Field(..., description="분석할 레포지토리 경로")

    @field_validator("repo_path")
    def validate_repo_path(cls, v):
        """레포지토리 경로 존재 여부 검증"""
        path = Path(v)
        if not path.exists():
            raise ValueError(f"repo_path가 존재하지 않습니다: {v}")
        return v


class ComplexityResult(BaseModel):
    """Radon 복잡도 분석 결과"""
    average_complexity: float = Field(default=0.0, description="평균 복잡도")
    total_functions: int = Field(default=0, description="총 함수 수")
    high_complexity_files: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="고복잡도 파일 목록"
    )
    summary: Dict[str, int] = Field(
        default_factory=dict,
        description="복잡도 등급별 분포 (A/B/C/D/F)"
    )
    error: Optional[str] = Field(None, description="에러 메시지")


class TypeCheckResult(BaseModel):
    """Pyright 타입 체크 결과"""
    total_errors: int = Field(default=0, description="타입 에러 수")
    total_warnings: int = Field(default=0, description="타입 경고 수")
    total_info: int = Field(default=0, description="정보성 메시지 수")
    files_analyzed: int = Field(default=0, description="분석된 파일 수")
    time_ms: float = Field(default=0.0, description="분석 시간 (ms)")
    error: Optional[str] = Field(None, description="에러 메시지")


class LocStatsResult(BaseModel):
    """Cloc 라인 수 분석 결과"""
    total_lines: int = Field(default=0, description="총 라인 수")
    code_lines: int = Field(default=0, description="코드 라인 수")
    comment_lines: int = Field(default=0, description="주석 라인 수")
    blank_lines: int = Field(default=0, description="빈 라인 수")
    by_language: Dict[str, Dict[str, int]] = Field(
        default_factory=dict,
        description="언어별 통계"
    )
    error: Optional[str] = Field(None, description="에러 메시지")


class StaticAnalyzerResponse(BaseResponse):
    """
    StaticAnalyzer 출력 스키마
    """
    complexity: ComplexityResult = Field(
        default_factory=ComplexityResult,
        description="복잡도 분석 결과"
    )
    type_check: TypeCheckResult = Field(
        default_factory=TypeCheckResult,
        description="타입 체크 결과"
    )
    loc_stats: LocStatsResult = Field(
        default_factory=LocStatsResult,
        description="라인 수 통계"
    )

    class Config:
        extra = "allow"
