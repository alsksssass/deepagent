"""
CommitEvaluator Pydantic schemas

커밋 평가 에이전트의 입출력 스키마 정의
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Literal, Optional
from shared.schemas.common import BaseContext, BaseResponse
from shared.utils.repo_utils import generate_repo_id, is_valid_git_url


class CommitEvaluatorContext(BaseContext):
    """
    CommitEvaluator 입력 스키마

    단일 커밋 평가를 위한 컨텍스트
    Repository Isolation을 위해 git_url 추가
    """
    commit_hash: str = Field(..., description="평가할 커밋 해시")
    user: str = Field(..., description="커밋 작성자 이메일 또는 이름")
    git_url: str = Field(..., description="Git repository URL (Repository Isolation용)")

    # Neo4j 연결 정보
    neo4j_uri: str = Field(default="bolt://localhost:7687", description="Neo4j URI")
    neo4j_user: str = Field(default="neo4j", description="Neo4j 사용자명")
    neo4j_password: str = Field(default="password", description="Neo4j 비밀번호")

    @field_validator("commit_hash")
    def validate_commit_hash(cls, v):
        """커밋 해시 길이 검증 (최소 7자)"""
        if len(v) < 7:
            raise ValueError("commit_hash는 최소 7자 이상이어야 합니다")
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


class CommitEvaluation(BaseModel):
    """
    개별 커밋 평가 결과

    LLM이 반환하는 평가 데이터
    """
    quality_score: float = Field(
        ...,
        ge=0.0,
        le=10.0,
        description=(
            "커밋의 코드 품질 종합 점수 (0.0-10.0 범위). "
            "코드 변경의 품질, 일관성, 모범 사례 준수를 평가합니다. "
            "10.0 = 탁월한 품질 (명확한 목적, 클린 코드, 테스트 포함, 문서화 완벽), "
            "7.0-9.9 = 양호한 품질 (대부분 양호, 경미한 개선점만 존재), "
            "4.0-6.9 = 보통 품질 (기본 기능 구현, 일부 개선 필요), "
            "1.0-3.9 = 낮은 품질 (코드 스멜, 테스트 누락, 문서화 부족), "
            "0.0 = 매우 낮은 품질 (버그 포함, 컨벤션 위반 심각). "
            "평가 요소: 코드 가독성 (30%), 일관성 (25%), 테스트 존재 여부 (25%), 문서화 (20%). "
            "예시: 8.5 = 잘 작성된 기능 추가 with 테스트, 4.0 = 기본 구현 but 테스트 없음"
        )
    )
    technologies: List[str] = Field(
        default_factory=list,
        description=(
            "커밋에서 사용된 기술 스택 리스트 (문자열 배열). "
            "프로그래밍 언어, 프레임워크, 라이브러리, 도구를 구체적으로 나열합니다. "
            "예시: ['Python', 'FastAPI', 'Pydantic', 'asyncio', 'pytest'], "
            "['React', 'TypeScript', 'Tailwind CSS', 'Zustand'], "
            "['Go', 'Gin', 'GORM', 'PostgreSQL', 'Docker']. "
            "일반적인 용어('웹', '백엔드')보다는 정확한 기술명을 명시하세요. "
            "커밋 diff에서 import문, package.json, requirements.txt 등을 참고하여 추출합니다."
        )
    )
    complexity: Literal["low", "medium", "high", "unknown"] = Field(
        default="medium",
        description=(
            "커밋 변경의 복잡도 수준. 반드시 'low', 'medium', 'high', 'unknown' 중 하나의 문자열로 제공해야 합니다 (소문자). "
            "평가 기준: "
            "low = 단순 변경 (10줄 이하, 단일 파일, 로직 변경 없음, 오타 수정, 설정 변경 등), "
            "medium = 보통 변경 (10-100줄, 1-3개 파일, 새로운 함수/클래스 추가, 기존 로직 수정), "
            "high = 복잡한 변경 (100줄 이상, 4개 이상 파일, 아키텍처 변경, 여러 컴포넌트 수정, 리팩토링), "
            "unknown = 변경 내용을 파악할 수 없는 경우 (diff 정보 부족, 바이너리 파일만 변경 등). "
            "예시: 타이포 수정 = low, 새 API 엔드포인트 추가 = medium, 데이터베이스 스키마 마이그레이션 = high"
        )
    )
    evaluation: str = Field(
        default="",
        description=(
            "커밋에 대한 종합 평가 설명 (2-3개 문장). "
            "반드시 다음을 포함: (1) 변경 사항의 목적과 범위, (2) 코드 품질 강점 또는 약점, (3) 개선 제안 (있는 경우). "
            "예시: "
            "'사용자 인증 API 엔드포인트 3개를 추가한 커밋입니다. "
            "JWT 토큰 검증 로직이 명확하고 에러 핸들링이 잘 되어 있으나, 단위 테스트가 누락되었습니다. "
            "테스트 추가 시 품질이 8.5점 이상으로 향상될 것입니다.' "
            "또는 '데이터베이스 쿼리 최적화를 위한 인덱스 추가 커밋입니다. "
            "마이그레이션 스크립트가 rollback 지원하며 문서화도 충분합니다. "
            "프로덕션 배포 전 성능 테스트 권장합니다.'"
        )
    )

    @field_validator("quality_score")
    def round_quality_score(cls, v):
        """품질 점수 소수점 1자리로 반올림"""
        return round(v, 1)


class CommitEvaluatorResponse(BaseResponse):
    """
    CommitEvaluator 출력 스키마
    """
    commit_hash: str = Field(default="", description="평가된 커밋 해시")
    quality_score: float = Field(default=0.0, ge=0.0, le=10.0, description="품질 점수")
    technologies: List[str] = Field(default_factory=list, description="사용된 기술 스택")
    complexity: Literal["low", "medium", "high", "unknown"] = Field(
        default="unknown",
        description="복잡도"
    )
    evaluation: str = Field(default="", description="평가 설명")

    class Config:
        extra = "allow"
