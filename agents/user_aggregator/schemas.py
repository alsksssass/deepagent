"""UserAggregator Agent Schemas"""

from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, List, Tuple, Literal, Optional
from shared.schemas.common import BaseContext, BaseResponse


class UserAggregatorContext(BaseContext):
    """UserAggregator 입력 스키마"""

    user: Optional[str] = Field(None, description="집계 대상 유저 이메일 또는 이름 (None이면 전체 유저)")
    commit_evaluations: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="CommitEvaluator 평가 결과 리스트 (하위 호환성, result_store_path 우선)"
    )

    @field_validator("user")
    def validate_user(cls, v):
        """유저 식별자 검증 (이메일 또는 이름 허용, None 또는 전체 유저 허용)"""
        if v is None or v == "ALL_USERS":
            return v
        # 이메일 또는 이름 모두 허용 (빈 문자열만 체크)
        if isinstance(v, str) and v.strip():
            return v.strip()
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "task_uuid": "test-uuid",
                "user": "user@example.com",
                "commit_evaluations": [
                    {
                        "status": "success",
                        "quality_score": 7.5,
                        "technologies": ["Python", "FastAPI"],
                        "complexity": "medium",
                    }
                ],
            }
        }


class QualityStats(BaseModel):
    """품질 점수 통계"""

    average_score: float = Field(default=0.0, ge=0.0, le=10.0)
    median_score: float = Field(default=0.0, ge=0.0, le=10.0)
    min_score: float = Field(default=0.0, ge=0.0, le=10.0)
    max_score: float = Field(default=0.0, ge=0.0, le=10.0)
    std_dev: float = Field(default=0.0, ge=0.0)
    distribution: Dict[str, int] = Field(default_factory=dict)


class TechStats(BaseModel):
    """기술 스택 통계"""

    top_technologies: List[Tuple[str, int]] = Field(default_factory=list)
    total_unique_technologies: int = Field(default=0, ge=0)
    technology_frequency: Dict[str, int] = Field(default_factory=dict)


class ComplexityStats(BaseModel):
    """복잡도 분포 통계"""

    low_count: int = Field(default=0, ge=0)
    medium_count: int = Field(default=0, ge=0)
    high_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    percentages: Dict[str, float] = Field(default_factory=dict)


class AggregateStats(BaseModel):
    """종합 집계 통계"""

    total_commits: int = Field(default=0, ge=0)
    successful_evaluations: int = Field(default=0, ge=0)
    failed_evaluations: int = Field(default=0, ge=0)
    quality_stats: QualityStats = Field(default_factory=QualityStats)
    tech_stats: TechStats = Field(default_factory=TechStats)
    complexity_stats: ComplexityStats = Field(default_factory=ComplexityStats)


class UserAggregatorResponse(BaseResponse):
    """UserAggregator 출력 스키마"""

    user: str = Field(default="")
    aggregate_stats: AggregateStats = Field(default_factory=AggregateStats)

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "user": "user@example.com",
                "aggregate_stats": {
                    "total_commits": 10,
                    "successful_evaluations": 9,
                    "failed_evaluations": 1,
                    "quality_stats": {
                        "average_score": 7.5,
                        "median_score": 7.8,
                        "min_score": 5.0,
                        "max_score": 9.5,
                        "std_dev": 1.2,
                        "distribution": {
                            "0-2": 0,
                            "2-4": 0,
                            "4-6": 2,
                            "6-8": 5,
                            "8-10": 3,
                        },
                    },
                    "tech_stats": {
                        "top_technologies": [("Python", 8), ("FastAPI", 5)],
                        "total_unique_technologies": 10,
                    },
                    "complexity_stats": {
                        "low_count": 3,
                        "medium_count": 5,
                        "high_count": 2,
                        "percentages": {"low": 30.0, "medium": 50.0, "high": 20.0},
                    },
                },
            }
        }
