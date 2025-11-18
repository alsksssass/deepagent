"""ArchitectAgent Schemas"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Union
from shared.schemas.common import BaseContext, BaseResponse


class ArchitectAgentContext(BaseContext):
    """ArchitectAgent 입력 스키마"""

    static_analysis: Dict[str, Any] = Field(default_factory=dict)
    user_aggregate: Dict[str, Any] = Field(default_factory=dict)
    repo_path: str = Field(default="", description="레포지토리 경로")


class StructurePattern(BaseModel):
    """아키텍처 구조 패턴"""

    pattern: str = Field(
        ...,
        description=(
            "아키텍처 패턴 이름. 구체적이고 인식 가능한 패턴명을 사용합니다. "
            "예시: 'Layered Architecture', 'MVC (Model-View-Controller)', 'Microservices', "
            "'Repository Pattern', 'Dependency Injection', 'Factory Pattern', 'Observer Pattern', "
            "'Component-Based Architecture', 'Event-Driven Architecture', 'Hexagonal Architecture'. "
            "일반적인 용어보다는 정확한 패턴 이름을 사용하세요."
        )
    )
    description: str = Field(
        ...,
        description=(
            "패턴의 적용 방식과 목적 설명 (1-2개 문장). "
            "해당 패턴이 코드베이스에서 어떻게 구현되어 있는지, 어떤 문제를 해결하는지 구체적으로 기술합니다. "
            "예시: 'Controller-Service-Repository 3계층으로 분리하여 비즈니스 로직과 데이터 접근을 격리. 각 계층은 명확한 책임을 가지며 하위 계층에만 의존.'"
        )
    )
    evidence: str = Field(
        ...,
        description=(
            "패턴 사용의 구체적 근거 (파일 경로, 디렉토리 구조, 코드 예시 포함). "
            "실제 코드베이스에서 이 패턴을 확인할 수 있는 증거를 제시합니다. "
            "예시: 'src/controllers/, src/services/, src/repositories/ 디렉토리 구조로 계층 분리 확인. "
            "UserController → UserService → UserRepository 의존성 체인 존재.' "
            "또는 'src/config/di_container.ts에서 Dependency Injection Container 구현 확인.'"
        )
    )


class ArchitectureAnalysis(BaseModel):
    """아키텍처 분석 결과"""

    structure_patterns: List[StructurePattern] = Field(
        default_factory=list,
        description="아키텍처 구조 패턴 목록. 반드시 객체 배열로 제공해야 합니다. 각 항목은 pattern, description, evidence 필드를 포함한 객체여야 합니다. 문자열 배열이 아닙니다."
    )
    design_principles: Dict[str, str] = Field(
        default_factory=dict,
        description="설계 원칙 준수 수준. 문자열 값으로 제공해야 합니다 (예: 'High', 'Medium', 'Low'). 숫자가 아닙니다. 키는 SRP, OCP, DRY, Modularity 등입니다."
    )

    @field_validator("structure_patterns", mode="before")
    @classmethod
    def convert_structure_patterns(cls, v):
        """문자열 리스트를 StructurePattern 객체 리스트로 자동 변환"""
        if not isinstance(v, list):
            return v
        
        result = []
        for item in v:
            if isinstance(item, str):
                # 문자열을 StructurePattern 객체로 변환
                result.append({
                    "pattern": item,
                    "description": f"{item} 패턴이 사용되고 있습니다.",
                    "evidence": "코드 구조 분석 결과"
                })
            elif isinstance(item, dict):
                result.append(item)
            else:
                result.append(item)
        return result

    @field_validator("design_principles", mode="before")
    @classmethod
    def convert_design_principles(cls, v):
        """float 값을 문자열로 변환"""
        if not isinstance(v, dict):
            return v
        
        result = {}
        for key, value in v.items():
            if isinstance(value, (int, float)):
                # float를 문자열로 변환 (0.8 -> "0.8" 또는 "High" 등)
                if 0.8 <= value <= 1.0:
                    result[key] = "High"
                elif 0.6 <= value < 0.8:
                    result[key] = "Medium"
                elif 0.4 <= value < 0.6:
                    result[key] = "Low"
                else:
                    result[key] = str(value)
            else:
                result[key] = value
        return result
    modularity_score: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description=(
            "모듈화 점수 (0.0-10.0 범위). 코드베이스의 모듈 분리 정도를 평가합니다. "
            "10.0 = 완벽한 모듈화 (각 모듈이 단일 책임을 가지며 명확한 경계와 인터페이스), "
            "7.0-9.9 = 우수한 모듈화 (대부분의 모듈이 잘 분리되어 있으나 소수의 개선점 존재), "
            "4.0-6.9 = 보통 수준의 모듈화 (기본적인 모듈 구조는 있으나 결합도가 높거나 책임이 불분명), "
            "1.0-3.9 = 낮은 모듈화 (모듈 경계가 불분명하고 높은 결합도), "
            "0.0 = 모듈화 없음 (스파게티 코드, 전역 의존성 심각). "
            "평가 시 고려사항: 모듈 간 결합도(낮을수록 좋음), 응집도(높을수록 좋음), 순환 의존성 여부, 인터페이스 명확성"
        )
    )
    scalability_assessment: str = Field(
        default="",
        description=(
            "확장성 평가 설명 (2-3개 문장으로 구성). 아키텍처의 확장 가능성을 종합적으로 설명합니다. "
            "반드시 다음 내용을 포함해야 합니다: "
            "(1) 수평 확장성(horizontal scaling): 서버/인스턴스 추가 시 성능 선형 증가 가능 여부, "
            "(2) 수직 확장성(vertical scaling): 리소스 증가 시 성능 향상 가능 여부, "
            "(3) 병목 지점(bottleneck): 확장을 제한하는 구체적인 요소 (예: 단일 DB, 전역 상태, 동기 처리), "
            "(4) 제약사항: 현재 아키텍처 구조로 인한 확장 한계. "
            "예시: '수평 확장은 stateless 서비스 설계로 가능하나, 중앙 집중식 DB가 병목. 수직 확장은 비동기 처리 부족으로 제한적. 캐싱 레이어 추가 시 개선 가능.'"
        )
    )
    architecture_score: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description=(
            "전체 아키텍처 종합 점수 (0.0-10.0 범위). modularity_score, design_principles 준수 수준, scalability_assessment를 종합하여 평가합니다. "
            "10.0 = 엔터프라이즈급 우수 아키텍처 (높은 모듈화, 모든 설계 원칙 High 준수, 뛰어난 확장성), "
            "7.0-9.9 = 양호한 아키텍처 (대부분의 영역에서 우수하나 일부 개선 필요), "
            "4.0-6.9 = 보통 아키텍처 (기본 구조는 갖추었으나 여러 개선 필요), "
            "1.0-3.9 = 개선 필요 (구조적 문제가 많고 리팩토링 시급), "
            "0.0 = 심각한 구조적 결함 (전면 재설계 권장). "
            "계산 가이드: (modularity_score * 0.4) + (design_principles 평균 점수 * 0.3) + (확장성 평가 점수 * 0.3). "
            "design_principles의 High=10, Medium=6, Low=3으로 환산하여 평균 계산"
        )
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description=(
            "아키텍처 개선 권장사항 리스트 (3-5개 항목). 각 항목은 구체적이고 실행 가능한 개선 제안이어야 합니다. "
            "우선순위 순으로 작성하며, 각 항목은 다음 형식을 따릅니다: '[우선순위] 문제점 → 개선방안 (기대효과)'. "
            "예시: "
            "['[High] 순환 의존성 제거 → 의존성 역전 원칙(DIP) 적용하여 core 모듈과 feature 모듈 분리 (결합도 감소, 테스트 용이성 향상)', "
            "'[Medium] 전역 상태 관리 개선 → Context API 또는 상태 관리 라이브러리 도입 (확장성 향상)', "
            "'[Low] API 레이어 추가 → 비즈니스 로직과 데이터 접근 계층 분리 (유지보수성 향상)']. "
            "기술적 부채, 성능 병목, 보안 취약점, 확장성 제약을 우선 다룹니다."
        )
    )
    raw_analysis: str = Field(
        default="",
        description="LLM의 원본 분석 텍스트 (디버깅 및 추적 용도). 구조화되지 않은 자유 형식 텍스트로, 분석 과정에서의 추론과 관찰 내용을 포함합니다."
    )

    @field_validator("modularity_score", "architecture_score")
    def round_scores(cls, v):
        return round(v, 1)


class ArchitectAgentResponse(BaseResponse):
    """ArchitectAgent 출력 스키마"""

    architecture_analysis: ArchitectureAnalysis = Field(
        default_factory=ArchitectureAnalysis
    )
