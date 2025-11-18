"""QualityAgent Schemas"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Literal, Union
from shared.schemas.common import BaseContext, BaseResponse


class QualityAgentContext(BaseContext):
    """QualityAgent 입력 스키마"""

    static_analysis: Dict[str, Any] = Field(
        default_factory=dict, description="StaticAnalyzer 결과"
    )
    user_aggregate: Dict[str, Any] = Field(
        default_factory=dict, description="UserAggregator 결과"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "task_uuid": "test-uuid",
                "static_analysis": {
                    "loc_stats": {
                        "total_lines": 1200,
                        "code_lines": 1000,
                        "comment_lines": 150,
                    },
                    "type_check": {
                        "total_errors": 5,
                        "total_warnings": 10,
                        "files_analyzed": 20,
                    },
                    "complexity": {"average_complexity": 5.2},
                },
                "user_aggregate": {
                    "aggregate_stats": {
                        "quality_stats": {"average_score": 7.5}
                    }
                },
            }
        }


class CodeSmell(BaseModel):
    """코드 스멜 정보"""

    category: str = Field(
        ...,
        description=(
            "코드 스멜 카테고리. 구체적이고 인식 가능한 스멜 유형을 사용합니다. "
            "예시 카테고리: "
            "'복잡도' (높은 순환 복잡도, 깊은 중첩, 긴 함수), "
            "'중복 코드' (Copy-Paste Programming, 반복 패턴), "
            "'긴 함수/클래스' (God Object, Long Method), "
            "'불필요한 복잡성' (Speculative Generality, Dead Code), "
            "'부적절한 명명' (Naming Conventions, Magic Numbers), "
            "'결합도' (Feature Envy, Inappropriate Intimacy), "
            "'응집도' (Divergent Change, Shotgun Surgery), "
            "'주석 부족/과다' (Documentation Smells), "
            "'타입 안정성' (Type Confusion, Missing Type Hints), "
            "'에러 처리' (Empty Catch Blocks, Silent Failures). "
            "일반적인 용어('문제점')보다는 정확한 스멜 유형을 명시하세요."
        )
    )
    severity: Literal["High", "Medium", "Low"] = Field(
        ...,
        description=(
            "스멜 심각도. 반드시 'High', 'Medium', 'Low' 중 하나의 문자열로 제공해야 합니다 (대소문자 구분 없음). "
            "평가 기준: "
            "High = 유지보수성 심각 저해 (코드 이해 어려움, 버그 발생 위험 높음, 확장 불가), "
            "Medium = 개선 필요 (일부 혼란 유발, 중간 수준 기술부채, 시간 소요), "
            "Low = 경미한 개선 여지 (사소한 불편함, 표준 위반). "
            "리팩토링 우선순위 결정에 사용됩니다."
        )
    )
    description: str = Field(
        ...,
        description=(
            "코드 스멜에 대한 상세 설명 (2-3개 문장). "
            "반드시 다음을 포함: (1) 스멜의 구체적 특징, (2) 유지보수성/가독성에 미치는 영향, (3) 예시 위치. "
            "예시: "
            "'process_data 함수가 150줄로 너무 길고 여러 책임을 가짐 (데이터 검증, 변환, 저장). "
            "코드 이해가 어렵고 테스트 작성 복잡하며 버그 발생 시 디버깅 시간 증가. "
            "services/processor.py:45-195에서 발견.' "
            "또는 '5개 파일에서 동일한 validation 로직 중복 (auth.py, user.py, admin.py, api.py, utils.py). "
            "수정 시 여러 위치 동시 변경 필요하여 누락 위험 및 불일치 발생 가능.'"
        )
    )
    instances: int = Field(
        ...,
        ge=0,
        description=(
            "코드베이스에서 발견된 해당 스멜의 인스턴스(발생) 개수 (0 이상 정수). "
            "예시: category='긴 함수', instances=12 → 긴 함수가 12개 존재. "
            "많을수록 기술부채가 크고 리팩토링 우선순위가 높습니다."
        )
    )


class QualityAnalysis(BaseModel):
    """품질 분석 결과"""

    maintainability_index: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description=(
            "유지보수성 지수 (0.0-100.0 범위). 코드의 유지보수 용이성을 종합 평가하는 지표입니다. "
            "100.0 = 최상의 유지보수성 (명확한 구조, 충분한 문서화, 낮은 복잡도, 우수한 타입 안정성), "
            "75.0-99.9 = 양호한 유지보수성 (대부분 잘 구조화, 경미한 개선점), "
            "50.0-74.9 = 보통 유지보수성 (일부 복잡한 코드, 문서화 부족), "
            "25.0-49.9 = 낮은 유지보수성 (복잡도 높음, 기술부채 심각), "
            "0.0-24.9 = 심각한 유지보수성 문제 (레거시 코드, 이해 극히 어려움). "
            "계산 가이드: 기본 100점 시작 - (평균 복잡도 × 2) - (문서화 부족 비율 × 30) - (타입 에러율 × 20) - (코드 스멜 가중치). "
            "Microsoft의 Maintainability Index 계산 방식 참고 가능."
        )
    )
    documentation_coverage: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description=(
            "문서화 커버리지 (0.0-100.0 백분율). 코드베이스의 문서화 정도를 나타냅니다. "
            "계산 방법: (주석이 있는 함수/클래스 수 + docstring이 있는 모듈 수) ÷ (전체 함수/클래스/모듈 수) × 100. "
            "90.0-100.0 = 탁월한 문서화 (모든 공개 API 문서화, 복잡한 로직 설명), "
            "70.0-89.9 = 양호한 문서화 (주요 컴포넌트 문서화, 일부 누락), "
            "40.0-69.9 = 부족한 문서화 (핵심 함수만 문서화, 상당 부분 누락), "
            "10.0-39.9 = 매우 부족한 문서화 (극소수만 문서화, 코드 읽기로 파악 필요), "
            "0.0-9.9 = 문서화 거의 없음 (주석/docstring 거의 없음). "
            "예시: 커버리지 12.5% = 100개 함수 중 12-13개만 문서화됨."
        )
    )
    type_safety_level: Literal["Excellent", "Good", "Fair", "Poor"] = Field(
        default="Fair",
        description=(
            "타입 안정성 수준. 반드시 'Excellent', 'Good', 'Fair', 'Poor' 중 하나의 문자열로 제공해야 합니다 (대소문자 정확히 일치). "
            "평가 기준 (타입 체커 실행 결과 기반): "
            "Excellent = 타입 에러 0개, 경고 0-2개, 모든 함수/변수에 타입 힌트 (타입 커버리지 95% 이상), "
            "Good = 타입 에러 0개, 경고 3-10개, 주요 함수에 타입 힌트 (타입 커버리지 70-94%), "
            "Fair = 타입 에러 1-5개 또는 경고 11-30개, 일부 함수에 타입 힌트 (타입 커버리지 40-69%), "
            "Poor = 타입 에러 6개 이상 또는 경고 31개 이상, 타입 힌트 거의 없음 (타입 커버리지 40% 미만). "
            "타입 에러는 런타임 버그 위험을 나타내므로 즉시 수정 권장."
        )
    )
    code_smells: List[CodeSmell] = Field(
        default_factory=list,
        description=(
            "코드 스멜 목록. 반드시 객체 배열로 제공해야 합니다. "
            "각 항목은 category, severity, description, instances 필드를 포함한 객체여야 합니다. "
            "문자열 배열이 아닙니다. 심각도 순으로 정렬 권장 (High → Medium → Low). "
            "예시: [{\"category\": \"복잡도\", \"severity\": \"High\", \"description\": \"...\", \"instances\": 5}, ...]"
        )
    )

    @field_validator("code_smells", mode="before")
    @classmethod
    def convert_code_smells(cls, v):
        """문자열 리스트를 CodeSmell 객체 리스트로 자동 변환"""
        if not isinstance(v, list):
            return v
        
        result = []
        for item in v:
            if isinstance(item, str):
                # 문자열을 CodeSmell 객체로 변환
                result.append({
                    "category": "기타",
                    "severity": "Medium",
                    "description": item,
                    "instances": 0
                })
            elif isinstance(item, dict):
                # 이미 딕셔너리인 경우 그대로 사용
                result.append(item)
            else:
                # 이미 CodeSmell 객체인 경우
                result.append(item)
        return result
    quality_score: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description=(
            "종합 품질 점수 (0.0-10.0 범위). 유지보수성, 문서화, 타입 안정성, 코드 스멜을 종합 평가합니다. "
            "10.0 = 최상의 코드 품질 (높은 유지보수성 지수, 충분한 문서화, Excellent 타입 안정성, 스멜 없음), "
            "7.0-9.9 = 양호한 품질 (대부분 양호, 경미한 개선점만 존재), "
            "4.0-6.9 = 보통 품질 (Fair 타입 안정성, 중간 수준 문서화, Medium 스멜 다수), "
            "1.0-3.9 = 낮은 품질 (Poor 타입 안정성, 문서화 부족, High 스멜 다수, 즉시 개선 필요), "
            "0.0 = 심각한 품질 문제 (레거시 코드, 기술부채 심각, 전면 리팩토링 필요). "
            "계산 가이드: (maintainability_index / 10) × 0.4 + (documentation_coverage / 10) × 0.2 + (타입 안정성 점수 × 0.2) + (10 - 스멜 가중치) × 0.2. "
            "타입 안정성 점수: Excellent=10, Good=7, Fair=5, Poor=2."
        )
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description=(
            "품질 개선 권장사항 리스트 (3-7개 항목, 우선순위 순). "
            "각 항목은 실행 가능하고 구체적인 제안이어야 하며, '[우선순위] 개선 영역 - 방법 - 기대 효과' 형식을 권장합니다. "
            "예시: "
            "['[Urgent] 타입 에러 6개 즉시 수정 - 타입 힌트 추가 및 mypy 오류 해결 - 런타임 버그 예방', "
            "'[High] process_data 함수 150줄 리팩토링 - 단일 책임 원칙 적용하여 5개 함수로 분리 - 가독성 향상 및 테스트 용이', "
            "'[High] 5개 파일 중복 validation 로직 통합 - shared/validators.py 모듈 생성 후 재사용 - 유지보수 용이', "
            "'[Medium] 문서화 커버리지 12.5% → 60% 향상 - 공개 API 및 복잡한 함수에 docstring 추가 - 온보딩 시간 단축', "
            "'[Medium] 복잡도 D등급 함수 10개 단순화 - Early Return 패턴, Guard Clause 적용 - 복잡도 C등급 이하로 감소', "
            "'[Low] Magic Number 제거 - 상수로 추출하여 의미 있는 이름 부여 - 코드 이해도 향상', "
            "'[Low] Pre-commit Hook 도입 - black, ruff, mypy 자동 실행으로 품질 자동 검증']. "
            "code_smells와 분석 결과를 기반으로 작성하되, 추가적인 개선 조치도 포함하세요."
        )
    )
    raw_analysis: str = Field(
        default="",
        description="LLM의 원본 품질 분석 텍스트 (디버깅 및 추적 용도). 구조화되지 않은 자유 형식 텍스트로, 분석 과정의 추론을 포함합니다."
    )

    @field_validator("maintainability_index", "documentation_coverage")
    @classmethod
    def round_percentage(cls, v):
        """백분율 소수점 1자리로 반올림"""
        return round(v, 1)

    @field_validator("quality_score")
    @classmethod
    def round_quality_score(cls, v):
        """품질 점수 소수점 1자리로 반올림"""
        return round(v, 1)


class QualityAgentResponse(BaseResponse):
    """QualityAgent 출력 스키마"""

    quality_analysis: QualityAnalysis = Field(default_factory=QualityAnalysis)

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "quality_analysis": {
                    "maintainability_index": 75.0,
                    "documentation_coverage": 12.5,
                    "type_safety_level": "Fair",
                    "code_smells": [
                        {
                            "category": "복잡도",
                            "severity": "High",
                            "description": "높은 cyclomatic complexity",
                            "instances": 5,
                        }
                    ],
                    "quality_score": 7.0,
                    "recommendations": ["주석 추가", "타입 힌트 개선"],
                },
            }
        }
