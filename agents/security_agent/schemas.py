"""SecurityAgent Schemas"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Literal
from shared.schemas.common import BaseContext, BaseResponse


class SecurityAgentContext(BaseContext):
    """SecurityAgent 입력 스키마"""

    static_analysis: Dict[str, Any] = Field(
        default_factory=dict, description="StaticAnalyzer 결과"
    )
    user_aggregate: Dict[str, Any] = Field(
        default_factory=dict, description="UserAggregator 결과"
    )
    git_url: str = Field(default="", description="Git 레포지토리 URL")

    class Config:
        json_schema_extra = {
            "example": {
                "task_uuid": "test-uuid",
                "static_analysis": {
                    "type_check": {"total_errors": 5, "total_warnings": 10},
                    "complexity": {"summary": {"A": 10, "B": 5, "C": 2, "D": 1, "F": 0}},
                },
                "user_aggregate": {
                    "aggregate_stats": {
                        "tech_stack": {"Python": 10, "FastAPI": 5}
                    }
                },
                "git_url": "https://github.com/example/repo",
            }
        }


class VulnerabilityRisk(BaseModel):
    """취약점 위험 정보"""

    category: str = Field(
        ...,
        description=(
            "취약점 카테고리. OWASP Top 10 또는 표준 보안 분류를 참고하여 구체적으로 작성합니다. "
            "예시 카테고리: "
            "'SQL Injection', 'XSS (Cross-Site Scripting)', 'CSRF (Cross-Site Request Forgery)', "
            "'인증 우회 (Broken Authentication)', '민감 데이터 노출 (Sensitive Data Exposure)', "
            "'XML 외부 개체 (XXE)', '접근 제어 오류 (Broken Access Control)', "
            "'보안 설정 오류 (Security Misconfiguration)', '안전하지 않은 역직렬화 (Insecure Deserialization)', "
            "'알려진 취약점이 있는 컴포넌트 사용', '로깅 및 모니터링 부족', "
            "'입력 검증 부족', '하드코딩된 자격증명', '안전하지 않은 암호화', '레이스 컨디션'. "
            "일반적인 용어('보안 문제')보다는 구체적인 취약점 유형을 명시하세요."
        )
    )
    severity: Literal["High", "Medium", "Low"] = Field(
        ...,
        description=(
            "취약점 심각도. 반드시 'High', 'Medium', 'Low' 중 하나의 문자열로 제공해야 합니다 (대소문자 구분 없음, 자동 정규화됨). "
            "평가 기준: "
            "High = 즉시 조치 필요 (원격 코드 실행, 인증 우회, 민감 데이터 유출 가능성), "
            "Medium = 조건부 취약점 (특정 조건에서 악용 가능, 정보 노출, 권한 상승 가능성), "
            "Low = 보안 모범 사례 위반 (직접적 위험은 낮으나 개선 권장). "
            "CVSS 점수 참고 시: High(7.0-10.0), Medium(4.0-6.9), Low(0.1-3.9)"
        )
    )
    description: str = Field(
        ...,
        description=(
            "취약점에 대한 상세 설명 (2-3개 문장). "
            "반드시 다음을 포함: (1) 취약점의 기술적 원인, (2) 악용 시 발생 가능한 구체적 피해, (3) 영향 범위. "
            "예시: 'API 엔드포인트에서 사용자 입력을 직접 SQL 쿼리에 삽입하여 SQL Injection 공격에 취약합니다. "
            "공격자가 임의의 데이터베이스 쿼리를 실행하여 전체 사용자 데이터를 탈취하거나 삭제할 수 있습니다. "
            "auth.py:45, user_service.py:78 등 5개 엔드포인트에서 동일한 패턴이 발견되었습니다.'"
        )
    )
    mitigation: str = Field(
        ...,
        description=(
            "취약점 완화 방안 (구체적이고 실행 가능한 해결책). "
            "코드 수정 예시, 사용할 라이브러리/함수, 설정 변경 방법을 포함합니다. "
            "예시: "
            "'ORM의 파라미터 바인딩 사용: db.execute(\"SELECT * FROM users WHERE id = ?\", [user_id]) 형태로 변경. "
            "SQLAlchemy 사용 시 text() 대신 query() 메서드 활용. "
            "또는 Prepared Statement 패턴 적용하여 입력값과 쿼리 로직 분리.' "
            "또는 'bcrypt/argon2 해시 함수로 비밀번호 암호화: bcrypt.hashpw(password, bcrypt.gensalt(rounds=12)). "
            "평문 저장 중인 user.password 필드를 user.password_hash로 변경하고 마이그레이션 스크립트 작성.'"
        )
    )


class SecurityAnalysis(BaseModel):
    """보안 분석 결과"""

    type_safety_issues: List[str] = Field(
        default_factory=list,
        description=(
            "타입 안정성 관련 보안 이슈 리스트 (각 항목은 문자열). "
            "타입 시스템 미사용으로 인한 보안 위험을 구체적으로 나열합니다. "
            "각 항목은 '파일:라인 - 이슈 설명 - 보안 영향' 형식을 권장합니다. "
            "예시: "
            "['auth.py:23 - user_id 매개변수 타입 미지정으로 문자열/숫자 혼용 가능 - SQL Injection 위험', "
            "'api/routes.py:45 - 반환 타입 불명확으로 민감 데이터 의도치 않게 노출 가능', "
            "'config.py:12 - 환경 변수 타입 검증 없이 사용 - 설정 오류 및 보안 우회 가능']. "
            "타입 에러 개수만 나열하지 말고, 보안 관점에서 위험한 항목만 포함하세요."
        )
    )
    auth_patterns: List[str] = Field(
        default_factory=list,
        description=(
            "발견된 인증/인가 패턴 리스트 (긍정적 보안 패턴, 각 항목은 문자열). "
            "코드베이스에서 사용 중인 보안 메커니즘과 구현 위치를 나열합니다. "
            "이 필드는 '좋은 보안 관행'을 기록하는 용도이며, 취약점은 vulnerability_risks에 포함됩니다. "
            "예시: "
            "['JWT 토큰 기반 인증 (middleware/auth.py) - RS256 알고리즘, 1시간 만료', "
            "'Role-Based Access Control (RBAC) 구현 (decorators/permissions.py) - admin/user/guest 역할 분리', "
            "'비밀번호 bcrypt 해싱 (utils/security.py) - cost factor 12 사용', "
            "'CSRF 토큰 검증 (middleware/csrf.py) - 모든 POST/PUT/DELETE 요청에 적용', "
            "'Rate Limiting (middleware/rate_limit.py) - IP당 분당 100 요청 제한']. "
            "단순히 '인증 사용'이 아닌, 구체적인 메커니즘과 위치를 명시하세요."
        )
    )
    vulnerability_risks: List[VulnerabilityRisk] = Field(
        default_factory=list,
        description=(
            "취약점 위험 목록. 반드시 객체 배열로 제공해야 합니다. "
            "각 항목은 category, severity, description, mitigation 필드를 포함한 객체여야 합니다. "
            "문자열 배열이 아닙니다. OWASP Top 10 기반 분류를 우선하며, 심각도 순으로 정렬 권장 (High → Medium → Low). "
            "예시: [{\"category\": \"SQL Injection\", \"severity\": \"High\", \"description\": \"...\", \"mitigation\": \"...\"}, ...]"
        )
    )
    security_score: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description=(
            "종합 보안 점수 (0.0-10.0 범위). 취약점 심각도, 타입 안정성, 인증 패턴 품질을 종합 평가합니다. "
            "10.0 = 엔터프라이즈급 보안 (취약점 없음, 모든 보안 모범 사례 준수, 포괄적 방어 체계), "
            "7.0-9.9 = 양호한 보안 (경미한 취약점만 존재, 주요 보안 메커니즘 구현), "
            "4.0-6.9 = 보통 보안 (Medium 취약점 다수 또는 High 취약점 소수, 기본 인증만 구현), "
            "1.0-3.9 = 취약한 보안 (High 취약점 다수, 인증/암호화 미흡), "
            "0.0 = 심각한 보안 결함 (Critical 취약점 존재, 즉시 조치 필수). "
            "계산 가이드: 기본 10점 시작 - (High 취약점 수 × 2) - (Medium 취약점 수 × 0.5) - (Low 취약점 수 × 0.1) + (auth_patterns 수 × 0.3, 최대 +2점). "
            "타입 안정성 이슈가 10개 이상이면 추가 -1점."
        )
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description=(
            "보안 개선 권장사항 리스트 (3-7개 항목, 우선순위 순). "
            "각 항목은 실행 가능하고 구체적인 개선 제안이어야 하며, '[우선순위] 조치 내용 - 기대 효과' 형식을 권장합니다. "
            "예시: "
            "['[Urgent] SQL Injection 취약점 즉시 수정 - 파라미터 바인딩 적용으로 데이터베이스 보안 확보', "
            "'[High] 비밀번호 평문 저장 중단 - bcrypt 해싱 도입으로 자격증명 보호', "
            "'[High] HTTPS 강제 적용 - 모든 통신 암호화로 중간자 공격 방지', "
            "'[Medium] CSRF 토큰 검증 추가 - state-changing 요청 보호', "
            "'[Medium] Rate Limiting 도입 - Brute Force 공격 완화', "
            "'[Low] 보안 헤더 추가 - X-Frame-Options, CSP 설정으로 XSS 완화', "
            "'[Low] 정기 의존성 감사 - 알려진 취약점 컴포넌트 제거']. "
            "vulnerability_risks의 mitigation을 요약하되, 추가적인 예방 조치도 포함하세요."
        )
    )
    raw_analysis: str = Field(
        default="",
        description="LLM의 원본 보안 분석 텍스트 (디버깅 및 추적 용도). 구조화되지 않은 자유 형식 텍스트로, 분석 과정의 추론을 포함합니다."
    )

    @field_validator("vulnerability_risks", mode="before")
    @classmethod
    def convert_vulnerability_risks(cls, v):
        """문자열 리스트를 VulnerabilityRisk 객체 리스트로 자동 변환 및 정규화"""
        if not isinstance(v, list):
            return v
        
        result = []
        for item in v:
            if isinstance(item, str):
                # 문자열을 VulnerabilityRisk 객체로 변환
                result.append({
                    "category": "기타",
                    "severity": "Medium",
                    "description": item,
                    "mitigation": "상세 분석 필요"
                })
            elif isinstance(item, dict):
                # 누락된 필드 보완 및 대소문자 정규화
                normalized_item = item.copy()
                
                # category 필드 누락 시 기본값
                if "category" not in normalized_item:
                    normalized_item["category"] = "기타"
                
                # severity 대소문자 정규화: 'HIGH' → 'High', 'MEDIUM' → 'Medium', 'LOW' → 'Low'
                if "severity" in normalized_item:
                    severity = normalized_item["severity"]
                    if isinstance(severity, str):
                        severity_upper = severity.upper()
                        if severity_upper == "HIGH":
                            normalized_item["severity"] = "High"
                        elif severity_upper == "MEDIUM":
                            normalized_item["severity"] = "Medium"
                        elif severity_upper == "LOW":
                            normalized_item["severity"] = "Low"
                else:
                    normalized_item["severity"] = "Medium"
                
                # description 필드 누락 시 기본값
                if "description" not in normalized_item:
                    normalized_item["description"] = "취약점 상세 분석 필요"
                
                # mitigation 필드 누락 시 기본값
                if "mitigation" not in normalized_item:
                    normalized_item["mitigation"] = "상세 분석 후 완화 방안 수립 필요"
                
                result.append(normalized_item)
            else:
                result.append(item)
        return result

    @field_validator("security_score")
    @classmethod
    def round_security_score(cls, v):
        """보안 점수 소수점 1자리로 반올림"""
        return round(v, 1)


class SecurityAgentResponse(BaseResponse):
    """SecurityAgent 출력 스키마"""

    security_analysis: SecurityAnalysis = Field(default_factory=SecurityAnalysis)

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "security_analysis": {
                    "type_safety_issues": ["타입 에러 5개 발견"],
                    "auth_patterns": ["JWT 인증 사용"],
                    "vulnerability_risks": [
                        {
                            "category": "입력 검증",
                            "severity": "High",
                            "description": "SQL Injection 가능성",
                            "mitigation": "파라미터 바인딩 사용",
                        }
                    ],
                    "security_score": 7.5,
                    "recommendations": ["타입 안정성 개선", "입력 검증 강화"],
                },
            }
        }
