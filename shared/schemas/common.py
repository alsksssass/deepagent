"""
Common Pydantic schemas for all agents

모든 에이전트의 입출력 스키마 기반 클래스
"""

from pydantic import BaseModel, Field, field_validator
from typing import Any, Optional, Literal
from datetime import datetime


class BaseContext(BaseModel):
    """
    모든 에이전트 입력의 기본 클래스

    모든 서브에이전트는 이 클래스를 상속하여 입력 스키마를 정의합니다.
    """
    task_uuid: str = Field(..., description="작업 고유 ID (UUID)")
    repo_path: Optional[str] = Field(None, description="Git 레포지토리 경로")
    target_user: Optional[str] = Field(None, description="분석 대상 유저 이메일 또는 이름")
    result_store_path: Optional[str] = Field(
        None,
        description="ResultStore 결과 디렉토리 경로 (다른 에이전트 결과 로드 시 사용)"
    )

    class Config:
        extra = "allow"  # 하위 에이전트별 추가 필드 허용
        str_strip_whitespace = True
        validate_assignment = True


class BaseResponse(BaseModel):
    """
    모든 에이전트 출력의 기본 클래스

    모든 서브에이전트는 이 클래스를 상속하여 출력 스키마를 정의합니다.
    """
    status: Literal["success", "failed"] = Field(
        ...,
        description="작업 실행 상태"
    )
    error: Optional[str] = Field(
        None,
        description="에러 메시지 (실패 시)"
    )

    class Config:
        extra = "allow"
        validate_assignment = True

    @field_validator("error")
    def validate_error_on_failed(cls, v, values):
        """failed 상태일 때 error 필드 필수 검증"""
        if values.data.get("status") == "failed" and not v:
            raise ValueError("status가 'failed'일 때 error 필드는 필수입니다")
        return v


class ErrorResponse(BaseResponse):
    """
    에러 전용 응답 스키마

    에이전트 실행 실패 시 사용
    """
    status: Literal["failed"] = "failed"
    error: str = Field(..., description="에러 메시지 (필수)")
    traceback: Optional[str] = Field(None, description="Python traceback (디버깅용)")

    class Config:
        extra = "allow"


class AgentMetadata(BaseModel):
    """
    에이전트 실행 메타데이터

    성능 모니터링 및 디버깅용
    """
    agent_name: str = Field(..., description="에이전트 이름")
    start_time: datetime = Field(default_factory=datetime.now, description="시작 시간")
    end_time: Optional[datetime] = Field(None, description="종료 시간")
    duration_seconds: Optional[float] = Field(None, description="실행 시간 (초)")

    def mark_complete(self):
        """실행 완료 시각 기록"""
        self.end_time = datetime.now()
        if self.start_time:
            self.duration_seconds = (self.end_time - self.start_time).total_seconds()
