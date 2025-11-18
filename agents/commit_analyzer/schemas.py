"""
CommitAnalyzer Pydantic schemas

Git 커밋 분석 및 Neo4j 적재 에이전트의 입출력 스키마 정의
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from pathlib import Path
from shared.schemas.common import BaseContext, BaseResponse


class CommitAnalyzerContext(BaseContext):
    """
    CommitAnalyzer 입력 스키마

    Git 커밋 분석 및 Neo4j 적재를 위한 컨텍스트
    """
    repo_path: str = Field(..., description="분석할 Git 레포지토리 경로")
    target_user: Optional[str] = Field(None, description="분석 대상 유저 이메일 또는 이름 (None이면 전체)")

    # Neo4j 연결 정보
    neo4j_uri: str = Field(default="bolt://localhost:7687", description="Neo4j URI")
    neo4j_user: str = Field(default="neo4j", description="Neo4j 사용자명")
    neo4j_password: str = Field(default="password", description="Neo4j 비밀번호")

    @field_validator("repo_path")
    def validate_repo_path(cls, v):
        """레포지토리 경로 존재 여부 검증"""
        path = Path(v)
        if not path.exists():
            raise ValueError(f"repo_path가 존재하지 않습니다: {v}")

        # .git 디렉토리 확인
        git_path = path / ".git"
        if not git_path.exists():
            raise ValueError(f"Git 레포지토리가 아닙니다: {v}")

        return v


class CommitAnalyzerResponse(BaseResponse):
    """
    CommitAnalyzer 출력 스키마
    """
    total_commits: int = Field(default=0, description="분석된 총 커밋 수")
    total_users: int = Field(default=0, description="발견된 총 유저 수")
    total_files: int = Field(default=0, description="수정된 총 파일 수")

    class Config:
        extra = "allow"
