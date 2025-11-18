"""UserSkillProfiler Schemas"""

import os
from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional
from shared.schemas.common import BaseContext, BaseResponse


class HybridConfig(BaseModel):
    """하이브리드 매칭 설정"""

    llm_max_concurrent: int = Field(default=50, ge=1, le=100, description="LLM 최대 병렬 실행 수")
    llm_batch_size: int = Field(default=10, ge=1, le=50, description="LLM 배치 크기")
    skill_candidate_count: int = Field(default=20, ge=5, le=50, description="임베딩 후보 선출 개수")
    relevance_threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="LLM 판단 임계값")

    @classmethod
    def from_env(cls) -> "HybridConfig":
        """환경변수에서 로드"""
        return cls(
            llm_max_concurrent=int(os.getenv("LLM_MAX_CONCURRENT", "50")),
            llm_batch_size=int(os.getenv("LLM_BATCH_SIZE", "10")),
            skill_candidate_count=int(os.getenv("SKILL_CANDIDATE_COUNT", "20")),
            relevance_threshold=float(os.getenv("SKILL_RELEVANCE_THRESHOLD", "0.5")),
        )


class SkillMatch(BaseModel):
    """LLM 스킬 매칭 결과"""

    skill_name: str = Field(..., description="스킬 이름")
    level: str = Field(..., description="스킬 레벨 (Basic/Intermediate/Advanced)")
    category: str = Field(..., description="카테고리")
    subcategory: str = Field(..., description="서브카테고리")
    relevance_score: float = Field(..., ge=0.0, le=1.0, description="LLM 판단 점수")
    reasoning: str = Field(..., description="LLM 판단 근거")
    base_score: int = Field(default=0, description="기본 점수")
    weighted_score: int = Field(default=0, description="가중 점수")
    occurrence_count: int = Field(default=1, description="발생 횟수")


class MissingSkillInfo(BaseModel):
    """미등록 스킬 로그"""

    code_snippet: str = Field(..., description="코드 스니펫")
    file_path: str = Field(..., description="소스 파일 경로")
    line_number: int = Field(default=0, description="라인 번호")
    suggested_skill_name: str = Field(..., description="제안 스킬 이름")
    suggested_level: str = Field(..., description="제안 레벨")
    suggested_category: str = Field(..., description="제안 카테고리")
    suggested_subcategory: str = Field(..., description="제안 서브카테고리")
    description: str = Field(..., description="스킬 설명")
    evidence_examples: str = Field(..., description="증거 예시")
    developer_type: str = Field(default="All", description="개발자 타입")


class SkillMatchItem(BaseModel):
    """LLM 스킬 매칭 결과 (Structured Output용)"""

    skill_name: str = Field(
        ...,
        description="스킬 이름 (예: '비동기 프로그래밍', 'FastAPI 기본')"
    )
    level: str = Field(
        ...,
        description="스킬 레벨 - 반드시 'Basic', 'Intermediate', 'Advanced' 중 하나여야 합니다"
    )
    category: str = Field(
        ...,
        description="카테고리 (예: '비동기 프로그래밍 (asyncio)', '웹 프레임워크')"
    )
    subcategory: str = Field(
        ...,
        description="서브카테고리 (예: '고급 비동기 패턴', 'FastAPI')"
    )
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="LLM 판단 점수 (0.0~1.0). 반드시 소수점 형태의 숫자여야 합니다 (예: 0.85, 0.90)"
    )
    reasoning: str = Field(
        ...,
        description="LLM 판단 근거 - 코드에서 어떤 패턴/라이브러리가 이 스킬을 입증하는지 구체적으로 설명"
    )


class MissingSkillItem(BaseModel):
    """미등록 스킬 제안 (Structured Output용)"""

    suggested_skill_name: str = Field(
        ...,
        description="제안 스킬 이름 (예: 'YOLOv8 객체 탐지', 'FastAPI 의존성 주입')"
    )
    suggested_level: str = Field(
        ...,
        description="제안 레벨 - 반드시 'Basic', 'Intermediate', 'Advanced' 중 하나"
    )
    suggested_category: str = Field(
        ...,
        description="제안 카테고리 (예: '머신러닝 및 딥러닝', '웹 프레임워크')"
    )
    suggested_subcategory: str = Field(
        ...,
        description="제안 서브카테고리 (예: '컴퓨터 비전', 'FastAPI')"
    )
    description: str = Field(
        ...,
        description="스킬 설명 - 이 스킬이 무엇인지, 어떤 기술을 포함하는지 명확하게 설명"
    )
    evidence_examples: str = Field(
        ...,
        description="증거 예시 - 코드에서 발견된 구체적인 패턴/라이브러리 사용 예시"
    )
    developer_type: str = Field(
        default="All",
        description="개발자 타입 (예: 'AI/ML', 'Backend', 'Frontend', 'All')"
    )


class SkillAnalysisOutput(BaseModel):
    """LLM 스킬 분석 출력 (Structured Output 최상위)"""

    matched_skills: List[SkillMatchItem] = Field(
        default_factory=list,
        description=(
            "매칭된 스킬 목록 - 반드시 SkillMatchItem 객체 배열이어야 합니다. "
            "⚠️ 중요: JSON 문자열이 아닌 실제 객체 배열을 반환해야 합니다. "
            "❌ 잘못된 형식: '[...]' (문자열) 또는 \"[...]\" (문자열) "
            "✅ 올바른 형식: [...] (배열) "
            "각 항목은 skill_name, level, category, subcategory, relevance_score, reasoning 필드를 포함한 객체여야 합니다. "
            "빈 배열 []을 반환해도 됩니다."
        )
    )
    missing_skills: List[MissingSkillItem] = Field(
        default_factory=list,
        description=(
            "미등록 스킬 제안 목록 - 반드시 MissingSkillItem 객체 배열이어야 합니다. "
            "⚠️ 중요: JSON 문자열이 아닌 실제 객체 배열을 반환해야 합니다. "
            "❌ 잘못된 형식: '[...]' (문자열) 또는 \"[...]\" (문자열) "
            "✅ 올바른 형식: [...] (배열) "
            "각 항목은 suggested_skill_name, suggested_level, suggested_category, "
            "suggested_subcategory, description, evidence_examples 필드를 포함한 객체여야 합니다. "
            "\n\n"
            "⚠️ 매우 엄격한 제안 기준 (다음 조건을 모두 만족해야 함):\n"
            "1. 코드에서 명확하게 특정 라이브러리/프레임워크/기술을 사용하고 있음\n"
            "2. 해당 기술이 스킬 DB에 전혀 없음 (후보 스킬에도 없음)\n"
            "3. 기술적으로 의미 있는 스킬임 (단순 함수 호출이 아님)\n"
            "4. 특정 도메인/기술 영역의 전문 지식을 요구함\n\n"
            "❌ 제안하지 말아야 할 것:\n"
            "- 기본 Python 문법 (if, for, def, class, import, if __name__ == '__main__' 등)\n"
            "- 표준 라이브러리 기본 사용 (os.path.exists, sys.argv, pathlib.Path, json.load 등)\n"
            "- 너무 일반적인 이름 (\"이미지 처리\", \"데이터 처리\", \"파일 처리\" 등)\n"
            "- 이미 기존 스킬로 커버 가능한 것\n"
            "- 코드에 실제로 없는 기능\n"
            "- 단순 함수/클래스 정의만 있는 경우\n\n"
            "✅ 제안해야 할 것:\n"
            "- 특정 프레임워크/라이브러리 (예: YOLOv8, FastAPI, Django 등)\n"
            "- 특정 기술 패턴 (예: Event Sourcing, CQRS 등)\n"
            "- 도메인 특화 기술\n\n"
            "대부분의 경우 빈 배열 []을 반환하는 것이 정상입니다."
        )
    )


class UserSkillProfilerContext(BaseContext):
    """UserSkillProfiler 입력 스키마"""

    user: str = Field(..., description="유저 이메일 또는 이름")
    persist_dir: str = Field(
        default="./data/chroma_db", description="ChromaDB 저장 디렉토리"
    )
    enable_hybrid: bool = Field(default=True, description="하이브리드 매칭 활성화")
    hybrid_config: Optional[HybridConfig] = Field(default=None, description="하이브리드 설정")


class SkillProfileData(BaseModel):
    """스킬 프로파일 데이터"""

    total_skills: int = Field(default=0, ge=0, description="총 보유 스킬 수")
    skills_by_category: Dict[str, Any] = Field(
        default_factory=dict, description="카테고리별 스킬 통계"
    )
    skills_by_level: Dict[str, int] = Field(
        default_factory=dict, description="레벨별 스킬 수"
    )
    category_coverage: Dict[str, Any] = Field(
        default_factory=dict, description="카테고리별 커버리지"
    )
    total_coverage: int = Field(default=0, ge=0, le=100, description="전체 커버리지 %")
    top_skills: List[Dict[str, Any]] = Field(
        default_factory=list, description="상위 스킬 목록"
    )
    # 레벨링 시스템 필드
    total_experience: int = Field(
        default=0, ge=0, description="총 경험치 (중복 제거된 base_score 합산)"
    )
    level: Dict[str, Any] = Field(
        default_factory=dict,
        description="레벨 정보 (level, level_name, experience, current_level_exp, next_level_exp, progress_percentage)",
    )
    # 개발자 타입별 통계 필드
    developer_type_coverage: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="개발자 타입별 기술 보유율 (퍼센티지 내림차순 정렬)",
    )
    developer_type_levels: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="개발자 타입별 레벨 정보",
    )


class UserSkillProfilerResponse(BaseResponse):
    """UserSkillProfiler 출력 스키마"""

    user: str = Field(default="", description="유저 이메일 또는 이름")
    skill_profile: SkillProfileData = Field(
        default_factory=SkillProfileData, description="스킬 프로파일"
    )
    missing_skills_log_path: Optional[str] = Field(
        default=None, description="미등록 스킬 로그 파일 경로"
    )
    hybrid_stats: Optional[Dict[str, Any]] = Field(
        default=None, description="하이브리드 매칭 통계"
    )
