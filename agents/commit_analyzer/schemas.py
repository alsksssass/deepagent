"""
CommitAnalyzer Pydantic schemas

Git 커밋 분석 및 Neo4j 적재 에이전트의 입출력 스키마 정의
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, List
from pathlib import Path
from shared.schemas.common import BaseContext, BaseResponse
from shared.utils.repo_utils import generate_repo_id, is_valid_git_url


class AuthorAlias(BaseModel):
    """저자 ID 별칭 스키마"""
    name: Optional[str] = Field(None, description="별칭 이름 (None이면 canonical_name 사용)")
    email: str = Field(..., description="별칭 이메일")


class AuthorMappingRule(BaseModel):
    """저자 매핑 규칙 스키마"""
    canonical_email: str = Field(..., description="대표 이메일 주소")
    aliases: List[AuthorAlias] = Field(default_factory=list, description="통합할 별칭 목록")


class AuthorMappingRules(BaseModel):
    """전체 저자 매핑 규칙 컬렉션"""
    mappings: Dict[str, AuthorMappingRule] = Field(
        default_factory=dict,
        description="매핑 규칙 딕셔너리 (key: canonical_name, value: AuthorMappingRule)"
    )

    def to_dict(self) -> Dict:
        """AuthorMapper가 사용하는 형식으로 변환"""
        result = {}
        for canonical_name, rule in self.mappings.items():
            result[canonical_name] = {
                "canonical_email": rule.canonical_email,
                "aliases": [
                    {"name": alias.name, "email": alias.email} if alias.name else {"email": alias.email}
                    for alias in rule.aliases
                ]
            }
        return result


class CommitAnalyzerContext(BaseContext):
    """
    CommitAnalyzer 입력 스키마

    Git 커밋 분석 및 Neo4j 적재를 위한 컨텍스트
    Repository Isolation을 위해 git_url 추가
    """
    repo_path: str = Field(..., description="분석할 Git 레포지토리 경로")
    git_url: str = Field(..., description="Git repository URL (Repository Isolation용)")
    target_user: Optional[str] = Field(None, description="분석 대상 유저 이메일 또는 이름 (None이면 전체)")
    user_emails: Optional[list[str]] = Field(None, description="사용자의 이메일 및 식별자 목록 (소문자, RepoCloner에서 전달)")

    # Neo4j 연결 정보 (GraphDBBackend가 사용)
    neo4j_uri: str = Field(default="bolt://localhost:7687", description="Neo4j URI")
    neo4j_user: str = Field(default="neo4j", description="Neo4j 사용자명")
    neo4j_password: str = Field(default="password", description="Neo4j 비밀번호")

    # Author Mapping 설정
    author_mapping_rules: Optional[AuthorMappingRules] = Field(
        None,
        description="저자 ID 매핑 규칙 (None이면 매핑하지 않음)"
    )

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

    @field_validator("git_url")
    def validate_git_url(cls, v):
        """Git URL 형식 검증"""
        if not is_valid_git_url(v):
            raise ValueError(f"유효하지 않은 Git URL입니다: {v}")
        return v

    @property
    def repo_id(self) -> str:
        """Repository ID 생성 (Repository Isolation용)"""
        return generate_repo_id(self.git_url)


class CommitAnalyzerResponse(BaseResponse):
    """
    CommitAnalyzer 출력 스키마
    """
    total_commits: int = Field(default=0, description="분석된 총 커밋 수")
    total_users: int = Field(default=0, description="발견된 총 유저 수")
    total_files: int = Field(default=0, description="수정된 총 파일 수")

    class Config:
        extra = "allow"
