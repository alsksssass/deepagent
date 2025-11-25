"""RepoSynthesizer Schemas"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, Any, List, Optional
from shared.schemas.common import BaseContext, BaseResponse


class LanguageInfo(BaseModel):
    """언어별 상세 정보"""

    stack: List[str] = Field(default_factory=list, description="기술 스택 리스트 (프레임워크, 라이브러리)")
    level: int = Field(default=0, ge=0, le=100, description="숙련도 레벨 (0-100)")
    exp: int = Field(default=0, description="경험치 (커밋 수 × 코드량 기반)")
    usage_frequency: int = Field(default=0, ge=0, le=100, description="사용 빈도 퍼센트 (0-100)")


class UserAnalysisResult(BaseModel):
    """유저 종합 분석 결과"""

    python: LanguageInfo = Field(default_factory=LanguageInfo)
    clean_code: float = Field(default=0.0, ge=0.0, le=10.0, description="코드 품질 점수 (0-10)")
    role: Dict[str, float] = Field(
        default_factory=dict,
        description="역할에 맞는 기술스택 보유 퍼센트 (예: {'Backend': 75, 'Frontend': 30})",
    )
    markdown: str = Field(
        default="", description="유저 분석 결과를 markdown 형식으로 예쁘게 추출한 문자열"
    )
    level: Dict[str, Any] = Field(
        default_factory=dict,
        description="레벨 정보 (level, experience, current_level_exp, next_level_exp, progress_percentage)",
    )
    tech_stack: List[str] = Field(
        default_factory=list,
        description="전체 기술 스택 리스트 (모든 언어, 프레임워크, 라이브러리, 도구 등)",
    )
    model_config = ConfigDict(
        extra="allow"
    )  # 동적 필드 허용 (언어별 정보: "python", "javascript" 등)


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

    main_task_uuid: str = Field(..., description="종합 작업 UUID (메인 task_uuid)")
    main_base_path: str = Field(..., description="종합 결과 저장 경로")
    repo_results: List[Dict[str, Any]] = Field(
        ..., description="각 레포지토리 분석 결과 리스트 (AgentState 딕셔너리)"
    )
    user_analysis_result: Optional[UserAnalysisResult] = Field(
        default=None, description="1차 종합한 유저 정보"
    )
    target_user: str | None = Field(None, description="분석 대상 유저 (None이면 전체 유저)")


class ImprovementRecommendation(BaseModel):
    """개선 권장사항"""

    priority: str = Field(..., description="우선순위: High, Medium, Low")
    category: str = Field(
        default="일반", description="카테고리 (예: 코드 품질, 아키텍처, 테스트, 성능, 보안 등)"
    )
    title: str = Field(..., description="개선 사항 제목")
    description: str = Field(..., description="개선 사항 상세 설명")
    action_items: List[str] = Field(
        default_factory=list, description="구체적인 실행 가능한 액션 아이템 리스트"
    )


class DimensionScores(BaseModel):
    """12개 차원별 점수"""

    technical_proficiency: int = Field(default=0, ge=0, le=100, description="기술 역량")
    code_quality: int = Field(default=0, ge=0, le=100, description="코드 품질")
    architecture_design: int = Field(default=0, ge=0, le=100, description="아키텍처 설계")
    development_style: int = Field(default=0, ge=0, le=100, description="개발 스타일")
    testing_validation: int = Field(default=0, ge=0, le=100, description="테스트 & 검증")
    performance: int = Field(default=0, ge=0, le=100, description="성능 최적화")
    security_awareness: int = Field(default=0, ge=0, le=100, description="보안 인식")
    collaboration: int = Field(default=0, ge=0, le=100, description="협업 능력")
    productivity: int = Field(default=0, ge=0, le=100, description="생산성")
    learning_growth: int = Field(default=0, ge=0, le=100, description="학습 능력")
    role_fit: int = Field(default=0, ge=0, le=100, description="역할 적합성")
    career_level: int = Field(default=0, ge=0, le=100, description="경력 수준")


class OverallAssessment(BaseModel):
    """종합 평가 상세 정보"""

    developer_level: str = Field(
        ..., description="개발자 등급 (Junior/Mid-level/Senior/Expert)"
    )
    total_score: int = Field(..., ge=0, le=100, description="총점 (0-100)")
    star_rating: int = Field(..., ge=0, le=5, description="별점 (0-5)")
    dimension_scores: DimensionScores = Field(..., description="12개 차원별 점수")
    key_strength: str = Field(..., description="핵심 강점 요약 (1줄)")
    key_improvement: str = Field(..., description="핵심 개선점 요약 (1줄)")
    recommended_direction: str = Field(..., description="추천 방향 요약 (1줄)")


class HiringDecision(BaseModel):
    """채용 의견 및 투입 가능성"""

    immediate_readiness: str = Field(
        ...,
        description="즉시 투입 가능성: 즉시 투입 가능 | 단기 온보딩 필요 | 중기 육성 필요 | 장기 육성 필요 | 투입 불가",
    )
    onboarding_period: str = Field(..., description="예상 온보딩 기간 (예: 1-2주, 1-3개월, 3-6개월 등)")
    hiring_recommendation: str = Field(
        ...,
        description="채용 추천 의견: 최우선 채용 | 적극 채용 | 채용 권장 | 조건부 가능 | 신중 검토 | 채용 불가",
    )
    hiring_decision_reason: str = Field(
        ..., description="채용 의견 근거 (3-5문장, 기술 역량, 팀 핏, 비용 대비 가치, 리스크 등 종합 평가)"
    )
    technical_risks: List[str] = Field(
        default_factory=list, description="채용 시 예상되는 기술적 리스크 (3-5개)"
    )
    expected_contributions: List[str] = Field(
        default_factory=list, description="채용 후 기대되는 기여 (3-5개)"
    )
    salary_recommendation: str = Field(
        ...,
        description="급여 레벨 추천 (예: Junior 초기 수준, Mid-level 표준, Senior 중반 등)",
    )
    estimated_salary_range: str = Field(
        ...,
        description="예상 적정 연봉 (한국 IT 개발자 기준, 예: 3,500만원 - 4,500만원)",
    )


class LLMAnalysisResult(BaseModel):
    """LLM 종합 분석 결과"""

    overall_assessment: str = Field(
        ...,
        description=(
            "종합 평가 - 개발자 등급, 총점, 12개 차원별 점수, 핵심 요약 포함. "
            "형식: '개발자 등급: [등급]\\n\\n총점: [점수]/100 ⭐⭐⭐\\n\\n"
            "## 12개 차원별 점수\\n- 기술 역량: [점수]/100\\n...\\n\\n"
            "## 핵심 요약\\n- 강점: [요약]\\n- 개선점: [요약]\\n- 추천 방향: [요약]'"
        ),
    )
    strengths: List[str] = Field(
        default_factory=list,
        description=(
            "강점 분석 - 최소 5개 이상, 각 강점은 근거와 예시 포함. "
            "형식: '✅ [강점 제목]: [구체적 설명 2-3문장]'"
        ),
    )
    improvement_recommendations: List[ImprovementRecommendation] = Field(
        default_factory=list,
        description="개선 방향 - 우선순위별 5-10개 구체적인 개선 제안 (priority, category, title, description, action_items 포함)",
    )
    role_suitability: Dict[str, str] = Field(
        ...,
        description=(
            "역할 적합성 평가 - 5개 역할(Backend, Frontend, DevOps, Data Science, Fullstack) 모두 평가. "
            "각 역할 형식: '[역할명] ([보유율]%): [강점 1-2문장]. [부족한 부분 1문장].' "
            "예: 'Backend (75%): 서버 아키텍처 설계와 데이터베이스 최적화에 강점을 보이나, 대규모 트래픽 처리 경험이 부족함.'"
        ),
    )
    hiring_decision: HiringDecision = Field(..., description="채용 의견 및 투입 가능성 평가")
    model_config = ConfigDict(
        extra="allow"
    )  # 동적 필드 허용 (언어별 정보: "python", "javascript" 등), 각 언어별 stack, level, exp, usage_frequency 정보 포함


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
        default_factory=list, description="각 레포지토리별 요약"
    )
    user_analysis_result: Optional[UserAnalysisResult] = Field(
        default=None, description="target_user가 지정된 경우 유저 종합 분석 결과"
    )
    llm_analysis: Optional[LLMAnalysisResult] = Field(
        default=None, description="LLM 종합 분석 결과 (개선 방향 제시)"
    )
