"""
RepoCloner Pydantic schemas

레포지토리 클론 에이전트의 입출력 스키마 정의
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from pathlib import Path
from shared.schemas.common import BaseContext, BaseResponse


class RepoClonerContext(BaseContext):
    """
    RepoCloner 입력 스키마

    Git 레포지토리 클론을 위한 컨텍스트
    """
    git_url: str = Field(..., description="Git 레포지토리 URL (SSH 또는 HTTPS)")
    base_path: str = Field(..., description="클론할 기본 경로")
    user_id: Optional[str] = Field(None, description="사용자 UUID (액세스 토큰 조회용, 옵셔널)")
    db_writer: Optional[Any] = Field(None, description="AnalysisDBWriter 인스턴스 (토큰 조회용, 옵셔널)")

    @field_validator("git_url")
    def validate_git_url(cls, v):
        """Git URL 형식 검증"""
        if not (v.startswith("git@") or v.startswith("http")):
            raise ValueError("git_url은 'git@' 또는 'http'로 시작해야 합니다")
        return v

    @field_validator("base_path")
    def validate_base_path(cls, v):
        """기본 경로 검증 (로컬 환경만)"""
        import os
        storage_backend = os.getenv("STORAGE_BACKEND", "local")
        
        # S3 환경에서는 경로가 존재하지 않을 수 있으므로 검증 스킵
        if storage_backend == "local":
            path = Path(v)
            if not path.exists():
                raise ValueError(f"base_path가 존재하지 않습니다: {v}")
        
        return v


class RepoClonerResponse(BaseResponse):
    """
    RepoCloner 출력 스키마
    """
    repo_path: Optional[str] = Field(None, description="클론된 레포지토리 경로")
    repo_name: Optional[str] = Field(None, description="레포지토리 이름")

    class Config:
        extra = "allow"
