"""RepoSynthesizer Schemas"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, Any, List, Optional
from shared.schemas.common import BaseContext, BaseResponse


class LanguageInfo(BaseModel):
    """언어별 상세 정보"""
    stack: List[str] = Field(default_factory=list, description="기술 스택 리스트")
    level: int = Field(default=0, description="숙련도 레벨")
    exp: int = Field(default=0, description="경험치")


class UserAnalysisResult(BaseModel):
    """유저 종합 분석 결과"""
    python: LanguageInfo = Field(default_factory=LanguageInfo)
    clean_code: float = Field(default=0.0, ge=0.0, le=10.0, description="코드 품질 점수 (0-10)")
    role: Dict[str, int] = Field(
        default_factory=dict,
        description="역할에 맞는 기술스택 보유 퍼센트 (예: {'Backend': 75, 'Frontend': 30})"
    )
    markdown: str = Field(default="", description="유저 분석 결과를 markdown 형식으로 예쁘게 추출한 문자열")
    level: Dict[str, Any] = Field(
        default_factory=dict,
        description="레벨 정보 (level, experience, current_level_exp, next_level_exp, progress_percentage)"
    )
    tech_stack: List[str] = Field(
        default_factory=list,
        description="전체 기술 스택 리스트 (모든 언어, 프레임워크, 라이브러리, 도구 등)"
    )
    model_config = ConfigDict(extra="allow")  # 동적 필드 허용 (언어별 정보: "python", "javascript" 등)



class RepoResult(BaseModel):
    """단일 레포지토리 분석 결과"""

    git_url: str = Field(..., description="Git 레포지토리 URL")
    task_uuid: str = Field(..., description="작업 UUID")
    base_path: str = Field(..., description="결과 저장 경로")
    final_report_path: str | None = Field(None, description="최종 리포트 경로")
    total_commits: int = Field(0, description="분석된 커밋 수")
    total_files: int = Field(0, description="분석된 파일 수")
    status: str = Field("success", description="분석 상태: success | failed")
    error_message: str | None = Field(None, description="에러 메시지 (실패 시)")


class RepoSynthesizerContext(BaseContext):
    """RepoSynthesizer 입력 스키마"""

    main_task_uuid: str = Field(
        ...,
        description="종합 작업 UUID (메인 task_uuid)"
    )
    main_base_path: str = Field(
        ...,
        description="종합 결과 저장 경로"
    )
    repo_results: List[Dict[str, Any]] = Field(
        ...,
        description="각 레포지토리 분석 결과 리스트 (AgentState 딕셔너리)"
    )
    target_user: str | None = Field(
        None,
        description="분석 대상 유저 (None이면 전체 유저)"
    )


class ImprovementRecommendation(BaseModel):
    """개선 권장사항"""
    priority: str = Field(..., description="우선순위: High, Medium, Low")
    category: str = Field(
        default="일반",
        description="카테고리 (예: 코드 품질, 아키텍처, 테스트, 성능, 보안 등)"
    )
    title: str = Field(..., description="개선 사항 제목")
    description: str = Field(..., description="개선 사항 상세 설명")
    action_items: List[str] = Field(
        default_factory=list,
        description="구체적인 실행 가능한 액션 아이템 리스트"
    )


class LLMAnalysisResult(BaseModel):
    """LLM 종합 분석 결과"""
    overall_assessment: str = Field(
        ...,
        description="종합 평가 - 전체적인 코드 품질과 개발 역량 평가"
    )
    strengths: List[str] = Field(
        default_factory=list,
        description="강점 분석 - 잘하고 있는 부분과 강점 리스트"
    )
    improvement_recommendations: List[ImprovementRecommendation] = Field(
        default_factory=list,
        description="개선 방향 - 우선순위별 구체적인 개선 제안"
    )
    role_suitability: Optional[Dict[str, str]] = Field(
        default=None,
        description="역할 적합성 평가 - 개발자 타입별 적합성 평가 (target_user가 지정된 경우)"
    )
    level: Dict[str, Any] = Field(
        default_factory=dict,
        description="레벨 정보 (level, experience, current_level_exp, next_level_exp, progress_percentage)"
    )
    tech_stack: List[str] = Field(
        default_factory=list,
        description="전체 기술 스택 리스트 (모든 언어, 프레임워크, 라이브러리, 도구 등)"
    )
    model_config = ConfigDict(extra="allow")  # 동적 필드 허용 (언어별 정보: "python", "javascript" 등), 각 언어별 stack, level, exp 정보 포함


class RepoSynthesizerResponse(BaseResponse):
    """RepoSynthesizer 출력 스키마"""

    total_repos: int = Field(0, description="분석된 총 레포지토리 수")
    successful_repos: int = Field(0, description="성공한 레포지토리 수")
    failed_repos: int = Field(0, description="실패한 레포지토리 수")
    total_commits: int = Field(0, description="전체 커밋 수")
    total_files: int = Field(0, description="전체 파일 수")
    synthesis_report_path: str = Field("", description="종합 리포트 경로")
    synthesis_report_markdown: str = Field("", description="종합 리포트 마크다운 전체 내용")
    repo_summaries: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="각 레포지토리별 요약"
    )
    user_analysis_result: Optional[UserAnalysisResult] = Field(
        default=None,
        description="target_user가 지정된 경우 유저 종합 분석 결과"
    )
    llm_analysis: Optional[LLMAnalysisResult] = Field(
        default=None,
        description="LLM 종합 분석 결과 (개선 방향 제시)"
    )

