"""Reporter Schemas"""

from pydantic import BaseModel, Field
from typing import Dict, Any
from pathlib import Path
from shared.schemas.common import BaseContext, BaseResponse


class ReporterContext(BaseContext):
    """Reporter 입력 스키마"""

    base_path: str = Field(
        ...,
        description=(
            "리포트 파일을 저장할 기본 디렉토리 경로 (절대 경로). "
            "Reporter는 이 경로 아래에 'reports/' 하위 디렉토리를 생성하고 마크다운 리포트를 저장합니다. "
            "예시: '/Users/user/project/deep_agents' → 리포트 저장 위치: '/Users/user/project/deep_agents/reports/report_YYYYMMDD_HHMMSS.md'"
        )
    )
    git_url: str = Field(
        default="",
        description=(
            "분석 대상 Git 레포지토리 URL (선택 사항). "
            "리포트 헤더에 표시되며 컨텍스트 정보로 사용됩니다. "
            "예시: 'https://github.com/user/project', 'git@github.com:user/project.git'"
        )
    )
    static_analysis: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "StaticAnalyzer의 정적 분석 결과 딕셔너리. "
            "복잡도 통계, LOC 통계, 타입 체크 결과 등을 포함합니다. "
            "Reporter는 이 데이터를 Summary 섹션 생성에 사용합니다."
        )
    )
    user_aggregate: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "UserAggregator의 사용자별 집계 결과 딕셔너리. "
            "사용자별 통계, 기술 스택, 품질 지표 등을 포함합니다. "
            "Reporter는 이 데이터를 User Statistics 섹션 생성에 사용합니다."
        )
    )
    domain_analysis: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "도메인 전문 에이전트들(ArchitectAgent, SecurityAgent, PerformanceAgent, QualityAgent)의 분석 결과 딕셔너리. "
            "이 필드는 입력이 아닌 내부적으로 계산됩니다 (Orchestrator가 도메인 에이전트 실행 후 결과 전달). "
            "구조 예시: {'architecture': {...}, 'security': {...}, 'performance': {...}, 'quality': {...}}. "
            "Reporter는 이 데이터를 각 도메인별 상세 분석 섹션 생성에 사용합니다."
        )
    )


class ReporterResponse(BaseResponse):
    """Reporter 출력 스키마"""

    report_path: str = Field(
        default="",
        description=(
            "생성된 마크다운 리포트 파일의 절대 경로. "
            "파일명 형식: 'report_YYYYMMDD_HHMMSS.md' (타임스탬프 포함). "
            "예시: '/Users/user/project/deep_agents/reports/report_20240115_143052.md'. "
            "이 경로를 사용하여 생성된 리포트를 읽거나 참조할 수 있습니다."
        )
    )
