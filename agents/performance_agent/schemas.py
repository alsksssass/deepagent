"""PerformanceAgent Schemas"""

import logging
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Literal
from shared.schemas.common import BaseContext, BaseResponse

logger = logging.getLogger(__name__)


class PerformanceAgentContext(BaseContext):
    """PerformanceAgent 입력 스키마"""

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
                    "complexity": {
                        "average_complexity": 5.2,
                        "total_functions": 50,
                        "summary": {"A": 20, "B": 15, "C": 10, "D": 3, "F": 2},
                    },
                    "loc_stats": {"code_lines": 1000},
                },
                "user_aggregate": {
                    "aggregate_stats": {
                        "complexity_stats": {
                            "low_count": 10,
                            "medium_count": 15,
                            "high_count": 5,
                        }
                    }
                },
            }
        }


class HighComplexityFunction(BaseModel):
    """높은 복잡도 함수 정보"""

    grade: Literal["D", "F"] = Field(
        ...,
        description=(
            "순환 복잡도(Cyclomatic Complexity) 등급. ⚠️ 반드시 'D' 또는 'F'만 허용됩니다. "
            "'C', 'B', 'A' 등급은 절대 사용하지 마세요. "
            "D = 복잡도 21-50 (높은 복잡도, 유지보수 어려움, 버그 발생 위험 증가), "
            "F = 복잡도 51+ (매우 높은 복잡도, 테스트 및 이해 극히 어려움, 즉시 리팩토링 필요). "
            "참고: A(1-5), B(6-10), C(11-20) 등급은 이 필드에 포함하지 않으며, D/F만 성능 병목 위험으로 간주합니다. "
            "만약 복잡도가 C(11-20) 수준이라면, 이 필드에 포함하지 말고 high_complexity_functions 배열에서 제외하세요. "
            "⚠️ 중요: 이 객체에는 grade, count, impact 필드만 포함하세요. risk_level, description 등 다른 필드는 포함하지 마세요."
        )
    )
    
    @field_validator("grade", mode="before")
    @classmethod
    def normalize_grade(cls, v):
        """grade 값 정규화: 'C' → 'D'로 매핑, 대소문자 무시"""
        if isinstance(v, str):
            v_upper = v.upper()
            # 'C' 등급은 'D'로 매핑 (C는 11-20 복잡도이므로 D에 가까움)
            if v_upper == "C":
                return "D"
            # 'D' 또는 'F'만 허용
            if v_upper in ["D", "F"]:
                return v_upper
            # 알 수 없는 값은 'D'로 기본값 설정
            logger.warning(f"⚠️ 알 수 없는 grade 값 '{v}', 'D'로 매핑")
            return "D"
        return v
    count: int = Field(
        ...,
        ge=0,
        description=(
            "해당 등급에 속하는 함수의 개수 (0 이상 정수). "
            "예시: grade='D', count=5 → 복잡도 21-50인 함수가 5개 존재. "
            "많을수록 코드베이스의 성능 및 유지보수 리스크가 높습니다."
        )
    )
    impact: str = Field(
        ...,
        description=(
            "해당 등급 함수들이 성능에 미치는 영향 설명 (1-2개 문장). "
            "CPU 사용률, 메모리 소비, 응답 시간 등 구체적인 성능 지표에 미치는 영향을 기술합니다. "
            "예시: "
            "'D등급 3개 함수는 중첩 루프로 인해 평균 50% CPU 사용률 초과 예상. 입력 크기 증가 시 성능 저하 가속화.' "
            "또는 'F등급 2개 함수는 O(n³) 알고리즘으로 대용량 데이터 처리 시 심각한 응답 지연 및 타임아웃 위험. 즉시 리팩토링 필요.'"
        )
    )


class BottleneckRisk(BaseModel):
    """병목 위험 정보"""

    area: str = Field(
        ...,
        description=(
            "성능 병목이 발생하는 구체적인 영역 또는 컴포넌트. "
            "파일명, 함수명, 모듈명을 포함하여 명확하게 지정합니다. "
            "예시: "
            "'데이터 처리 로직 (data_processor.py:process_batch)', "
            "'API 응답 생성 (api/handlers.py:get_users)', "
            "'데이터베이스 쿼리 (models/user.py:find_all_with_joins)', "
            "'파일 I/O (utils/file_loader.py:load_large_file)', "
            "'캐시 미스율 높음 (cache/redis_client.py)', "
            "'동기 처리 블로킹 (services/email_service.py:send_email)'. "
            "일반적인 용어('로직', '처리')보다는 정확한 코드 위치를 명시하세요."
        )
    )
    risk_level: Literal["High", "Medium", "Low"] = Field(
        ...,
        description=(
            "병목 위험 수준. 반드시 'High', 'Medium', 'Low' 중 하나의 문자열로 제공해야 합니다 (대소문자 구분 없음, 자동 정규화됨). "
            "⚠️ 중요: 'Critical'은 사용하지 마세요. 'Critical' 수준은 'High'로 표현하세요. "
            "평가 기준: "
            "High = 심각한 성능 저하 (응답 시간 2초 이상, CPU 80% 이상, 메모리 누수, 동시 사용자 10명 이하 제한), "
            "Medium = 눈에 띄는 지연 (응답 시간 500ms-2초, CPU 50-80%, 확장성 제약), "
            "Low = 경미한 최적화 여지 (응답 시간 200-500ms, CPU 30-50%, 개선 시 효율성 향상). "
            "실제 사용자 경험 및 시스템 자원 소비를 기준으로 평가합니다. "
            "허용된 값: 'High', 'Medium', 'Low'만 사용 가능합니다."
        )
    )
    description: str = Field(
        ...,
        description=(
            "병목 발생 원인 및 영향에 대한 상세 설명 (2-3개 문장). "
            "반드시 다음을 포함: (1) 병목의 기술적 원인 (알고리즘, I/O, 리소스 경쟁 등), "
            "(2) 성능 지표에 미치는 구체적 영향, (3) 발생 조건 또는 트리거. "
            "예시: "
            "'process_batch 함수에서 O(n²) 중첩 루프로 1,000개 항목 처리 시 30초 소요. "
            "입력 크기가 커질수록 처리 시간이 제곱으로 증가하여 대용량 배치 작업에서 타임아웃 발생. "
            "평균 API 응답 시간을 500ms에서 5초로 증가시킴.' "
            "또는 'find_all_with_joins 쿼리가 N+1 문제로 100회 개별 DB 조회 수행. "
            "단일 요청에 1초 소요되며, 동시 사용자 증가 시 DB 커넥션 풀 고갈 위험.'"
        )
    )


class OptimizationOpportunity(BaseModel):
    """최적화 기회"""

    category: Literal["알고리즘", "데이터구조", "캐싱", "병렬화", "기타"] = Field(
        ...,
        description=(
            "최적화 카테고리. 반드시 다음 중 하나를 선택해야 합니다 (정확히 일치해야 함): "
            "'알고리즘' = 알고리즘 효율성 개선 (O(n²) → O(n log n), 중복 연산 제거 등), "
            "'데이터구조' = 데이터 구조 변경 (배열 → 해시맵, 리스트 → 트리 등), "
            "'캐싱' = 캐싱 전략 도입 또는 개선 (메모리 캐시, Redis, CDN 등), "
            "'병렬화' = 병렬 처리 및 비동기화 (멀티스레드, async/await, 워커 풀 등), "
            "'기타' = 위 카테고리에 속하지 않는 최적화 (I/O 개선, 네트워크 최적화, 리소스 관리 등). "
            "허용된 값만 사용하세요. 다른 값은 자동으로 '기타'로 변환됩니다."
        )
    )
    description: str = Field(
        ...,
        description=(
            "최적화 방안에 대한 구체적 설명 (2-3개 문장). "
            "현재 문제점, 제안하는 해결 방법, 구현 방식을 포함합니다. "
            "예시: "
            "'현재 선형 탐색으로 사용자 검색 시 O(n) 시간 소요. "
            "해시맵 기반 인덱스를 도입하여 O(1) 조회로 개선 가능. "
            "user_id를 키로 하는 딕셔너리 구조로 변경하고 초기화 시 인덱스 생성.' "
            "또는 '동기 API 호출로 외부 서비스 응답 대기 중 블로킹 발생. "
            "asyncio 기반 비동기 처리로 변경하여 여러 API를 동시 호출. "
            "응답 대기 시간을 순차 합산에서 최대값으로 단축.'"
        )
    )
    expected_improvement: str = Field(
        ...,
        description=(
            "예상되는 성능 개선 효과 (구체적 수치 또는 백분율 포함). "
            "응답 시간, 처리량, 리소스 사용률 등 측정 가능한 지표로 표현합니다. "
            "예시: "
            "'응답 시간 70% 단축 (1초 → 300ms)', "
            "'처리량 3배 향상 (초당 100개 → 300개 요청)', "
            "'메모리 사용량 50% 감소 (2GB → 1GB)', "
            "'CPU 사용률 30% 절감 (80% → 50%)', "
            "'동시 사용자 수용 능력 5배 증가 (20명 → 100명)'. "
            "단순히 '성능 향상' 대신 구체적 수치를 제시하세요."
        )
    )


class PerformanceAnalysis(BaseModel):
    """성능 분석 결과"""

    high_complexity_functions: List[HighComplexityFunction] = Field(
        default_factory=list, 
        description=(
            "높은 복잡도 함수 목록. "
            "⚠️ 중요: 각 항목은 grade, count, impact 필드만 포함해야 합니다. "
            "risk_level, description 등 다른 필드는 포함하지 마세요."
        )
    )
    bottleneck_risks: List[BottleneckRisk] = Field(
        default_factory=list, 
        description=(
            "병목 위험 목록. 반드시 객체 배열로 제공해야 합니다. "
            "각 항목은 area, risk_level, description 필드를 포함한 객체여야 합니다. "
            "⚠️ 중요: risk_level은 반드시 'High', 'Medium', 'Low' 중 하나여야 합니다. "
            "'Critical'은 사용하지 마세요. 'Critical' 수준은 'High'로 표현하세요. "
            "문자열 배열이 아닙니다."
        )
    )
    optimization_opportunities: List[OptimizationOpportunity] = Field(
        default_factory=list, 
        description="최적화 기회 목록. 반드시 객체 배열로 제공해야 합니다. 각 항목은 category, description, expected_improvement 필드를 포함한 객체여야 합니다. 문자열 배열이 아닙니다."
    )

    @field_validator("bottleneck_risks", mode="before")
    @classmethod
    def convert_bottleneck_risks(cls, v):
        """문자열 리스트를 BottleneckRisk 객체 리스트로 자동 변환 및 정규화"""
        if not isinstance(v, list):
            return v
        
        result = []
        for item in v:
            if isinstance(item, str):
                # 문자열을 BottleneckRisk 객체로 변환
                result.append({
                    "area": "일반",
                    "risk_level": "Medium",
                    "description": item
                })
            elif isinstance(item, dict):
                # 대소문자 정규화: 'HIGH' → 'High', 'MEDIUM' → 'Medium', 'LOW' → 'Low'
                # 'CRITICAL' → 'High'로 매핑
                normalized_item = item.copy()
                if "risk_level" in normalized_item:
                    risk_level = normalized_item["risk_level"]
                    if isinstance(risk_level, str):
                        risk_level_upper = risk_level.upper()
                        if risk_level_upper == "HIGH" or risk_level_upper == "CRITICAL":
                            normalized_item["risk_level"] = "High"
                        elif risk_level_upper == "MEDIUM":
                            normalized_item["risk_level"] = "Medium"
                        elif risk_level_upper == "LOW":
                            normalized_item["risk_level"] = "Low"
                        # 알 수 없는 값은 기본값으로 설정
                        elif risk_level_upper not in ["HIGH", "MEDIUM", "LOW", "CRITICAL"]:
                            normalized_item["risk_level"] = "Medium"
                result.append(normalized_item)
            else:
                result.append(item)
        return result

    @field_validator("optimization_opportunities", mode="before")
    @classmethod
    def convert_optimization_opportunities(cls, v):
        """문자열 리스트를 OptimizationOpportunity 객체 리스트로 자동 변환 및 카테고리 매핑"""
        if not isinstance(v, list):
            return v
        
        # 허용된 카테고리 목록
        allowed_categories = ["알고리즘", "데이터구조", "캐싱", "병렬화", "기타"]
        
        result = []
        for item in v:
            if isinstance(item, str):
                # 문자열을 OptimizationOpportunity 객체로 변환
                result.append({
                    "category": "기타",
                    "description": item,
                    "expected_improvement": "개선 효과 분석 필요"
                })
            elif isinstance(item, dict):
                # 카테고리 매핑: 비표준 카테고리 → '기타'로 변환
                normalized_item = item.copy()
                if "category" in normalized_item:
                    category = normalized_item["category"]
                    if isinstance(category, str) and category not in allowed_categories:
                        # 비표준 카테고리인 경우 '기타'로 매핑
                        normalized_item["category"] = "기타"
                result.append(normalized_item)
            else:
                result.append(item)
        return result
    performance_score: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description=(
            "종합 성능 점수 (0.0-10.0 범위). 복잡도, 병목 위험, 최적화 기회를 종합 평가합니다. "
            "10.0 = 최적화된 고성능 (모든 함수 A-C 등급, 병목 없음, 효율적 알고리즘/데이터구조), "
            "7.0-9.9 = 양호한 성능 (D등급 소수, Low 병목만 존재, 경미한 최적화 여지), "
            "4.0-6.9 = 보통 성능 (D등급 다수 또는 F등급 소수, Medium 병목 존재, 개선 필요), "
            "1.0-3.9 = 낮은 성능 (F등급 다수, High 병목 다수, 즉시 최적화 필요), "
            "0.0 = 심각한 성능 문제 (응답 불가 수준, 시스템 과부하 위험). "
            "계산 가이드: 기본 10점 시작 - (D등급 함수 수 × 0.3) - (F등급 함수 수 × 1.0) - (High 병목 수 × 1.5) - (Medium 병목 수 × 0.5). "
            "최적화 기회가 3개 이상이면 추가 -0.5점."
        )
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description=(
            "성능 개선 권장사항 리스트 (3-7개 항목, 우선순위 순). "
            "각 항목은 실행 가능하고 구체적인 제안이어야 하며, '[우선순위] 개선 대상 - 방법 - 기대 효과' 형식을 권장합니다. "
            "예시: "
            "['[Urgent] process_batch 함수 O(n²) 알고리즘 개선 - 해시맵 인덱스 도입으로 O(n) 단축 - 응답 시간 80% 감소', "
            "'[High] find_all_with_joins N+1 쿼리 문제 해결 - eager loading 적용으로 단일 쿼리 변환 - DB 부하 90% 감소', "
            "'[High] 동기 API 호출 비동기화 - asyncio 기반 병렬 처리 도입 - 처리 시간 3배 단축', "
            "'[Medium] Redis 캐싱 레이어 추가 - 자주 조회되는 사용자 데이터 캐싱 - DB 쿼리 50% 감소', "
            "'[Medium] 파일 I/O 스트리밍 처리 - 메모리 전체 로드 대신 청크 단위 읽기 - 메모리 사용량 70% 감소', "
            "'[Low] 복잡도 D등급 함수 리팩토링 - 조건문 단순화 및 함수 분리 - 유지보수성 향상', "
            "'[Low] 프로파일링 도구 도입 - 실제 병목 지점 측정 및 지속적 모니터링']. "
            "bottleneck_risks와 optimization_opportunities를 기반으로 작성하되, 추가적인 예방 조치도 포함하세요."
        )
    )
    raw_analysis: str = Field(
        default="",
        description="LLM의 원본 성능 분석 텍스트 (디버깅 및 추적 용도). 구조화되지 않은 자유 형식 텍스트로, 분석 과정의 추론을 포함합니다."
    )

    @field_validator("performance_score")
    @classmethod
    def round_performance_score(cls, v):
        """성능 점수 소수점 1자리로 반올림"""
        return round(v, 1)


class PerformanceAgentResponse(BaseResponse):
    """PerformanceAgent 출력 스키마"""

    performance_analysis: PerformanceAnalysis = Field(
        default_factory=PerformanceAnalysis
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "performance_analysis": {
                    "high_complexity_functions": [
                        {
                            "grade": "D",
                            "count": 3,
                            "impact": "높은 CPU 사용률 예상",
                        },
                        {
                            "grade": "F",
                            "count": 2,
                            "impact": "심각한 성능 저하 가능성",
                        },
                    ],
                    "bottleneck_risks": [
                        {
                            "area": "데이터 처리 로직",
                            "risk_level": "High",
                            "description": "O(n²) 알고리즘 사용",
                        }
                    ],
                    "optimization_opportunities": [
                        {
                            "category": "알고리즘",
                            "description": "정렬 알고리즘 개선",
                            "expected_improvement": "50% 성능 향상",
                        }
                    ],
                    "performance_score": 6.5,
                    "recommendations": ["복잡도 개선", "알고리즘 최적화"],
                },
            }
        }
