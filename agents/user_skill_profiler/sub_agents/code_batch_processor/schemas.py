"""
CodeBatchProcessor 스키마 정의

Level 1 전용 스키마 (부모 UserSkillProfiler와 분리)

이 스키마는 CodeBatchProcessor 에이전트의 입력/출력을 정의하며,
LLM이 명확하게 이해할 수 있도록 상세한 Field description을 포함합니다.
"""

from typing import List, Optional
from pydantic import BaseModel, Field
from shared.schemas.common import BaseContext, BaseResponse


class CodeSample(BaseModel):
    """
    단일 코드 샘플 (메타데이터 포함)

    ChromaDB code collection에서 가져온 코드 스니펫과 위치 정보를 포함합니다.
    """

    code: str = Field(
        ...,
        description=(
            "분석할 Python 코드 스니펫 전체 내용. "
            "함수, 클래스, 또는 코드 블록일 수 있으며, "
            "이 코드를 분석하여 사용된 스킬을 판단합니다. "
            "예: 'async def fetch_data():\\n    async with aiohttp.ClientSession() as session:'"
        )
    )

    file: str = Field(
        ...,
        description=(
            "코드가 위치한 파일의 상대 경로. "
            "예: 'src/services/api_client.py', 'utils/data_processor.py'. "
            "미등록 스킬 제안 시 이 경로가 함께 기록됩니다."
        )
    )

    line_start: int = Field(
        ...,
        ge=0,
        description=(
            "코드 스니펫의 시작 라인 번호 (0부터 시작). "
            "파일 내에서 이 코드가 시작되는 위치를 나타냅니다. "
            "예: 42 (파일의 42번째 줄부터 시작)"
        )
    )

    line_end: int = Field(
        ...,
        ge=0,
        description=(
            "코드 스니펫의 종료 라인 번호 (0부터 시작). "
            "파일 내에서 이 코드가 끝나는 위치를 나타냅니다. "
            "line_start보다 크거나 같아야 합니다. "
            "예: 58 (파일의 58번째 줄까지)"
        )
    )


class CodeBatchContext(BaseContext):
    """
    CodeBatchProcessor 입력 스키마

    부모 에이전트(UserSkillProfiler)로부터 전달받는 배치 처리 요청 정보입니다.
    하나의 배치는 통상 10개 내외의 코드 샘플을 포함하며,
    이들은 병렬로 LLM 분석됩니다.
    """

    batch_id: int = Field(
        ...,
        ge=0,
        description=(
            "배치 식별자 (0부터 시작). "
            "로깅 및 디버깅 목적으로 사용되며, 여러 배치가 병렬 실행될 때 "
            "각 배치를 구분하는 데 사용됩니다. "
            "예: 0 (첫 번째 배치), 1 (두 번째 배치)"
        )
    )

    codes: List[CodeSample] = Field(
        ...,
        min_length=1,
        max_length=20,
        description=(
            "이 배치에서 처리할 코드 샘플 리스트. "
            "각 코드 샘플은 별도의 LLM 호출로 분석되며, 병렬로 처리됩니다. "
            "통상적으로 10개 내외의 코드를 포함하지만, 최대 20개까지 가능합니다. "
            "배치 크기가 클수록 처리 시간이 길어질 수 있습니다."
        )
    )

    persist_dir: str = Field(
        ...,
        description=(
            "ChromaDB 데이터베이스가 저장된 디렉토리 경로 (절대 경로 또는 상대 경로). "
            "이 경로에서 skill_charts collection을 로드하여 "
            "임베딩 기반 스킬 후보를 검색합니다. "
            "예: './data/chroma_db' 또는 '/Users/user/project/data/chroma_db'"
        )
    )

    hybrid_config: "HybridConfig" = Field(
        ...,
        description=(
            "하이브리드 매칭 설정 객체. "
            "임베딩 검색 후보 수(skill_candidate_count), "
            "LLM 판단 임계값(relevance_threshold), "
            "배치 크기(llm_batch_size), "
            "최대 동시 실행 수(llm_max_concurrent) 등을 포함합니다. "
            "이 설정은 부모 에이전트로부터 전달받아 일관성을 유지합니다."
        )
    )

    task_uuid: str = Field(
        ...,
        description=(
            "작업 고유 식별자 (UUID 형식). "
            "ChromaDB collection 이름 생성 시 사용되며 (code_{task_uuid}), "
            "로깅 및 결과 추적에도 활용됩니다. "
            "예: '0313b26d-881f-4fe6-97f6-1b7b0546d4aa'"
        )
    )


class CodeBatchResponse(BaseResponse):
    """
    CodeBatchProcessor 출력 스키마

    배치 처리 결과를 부모 에이전트에게 반환하는 응답 객체입니다.
    성공한 스킬 매칭, 실패한 코드, 성공률 등을 포함하여
    부모 에이전트가 재시도 여부를 판단할 수 있게 합니다.
    """

    batch_id: int = Field(
        ...,
        ge=0,
        description=(
            "처리한 배치의 식별자. "
            "요청 시 받은 batch_id를 그대로 반환하여 "
            "부모 에이전트가 어떤 배치의 결과인지 확인할 수 있게 합니다."
        )
    )

    matched_skills: List["SkillMatch"] = Field(
        default_factory=list,
        description=(
            "LLM이 매칭에 성공한 스킬 목록. "
            "각 SkillMatch 객체는 skill_name, level, category, subcategory, "
            "relevance_score, reasoning 필드를 포함합니다. "
            "relevance_score가 임계값 이상인 스킬만 포함됩니다. "
            "빈 리스트일 수 있으며, 이는 매칭된 스킬이 없음을 의미합니다."
        )
    )

    missing_skills: List["MissingSkillInfo"] = Field(
        default_factory=list,
        description=(
            "코드에서 발견되었으나 스킬 DB에 없는 스킬 제안 목록. "
            "각 MissingSkillInfo는 suggested_skill_name, suggested_level, "
            "suggested_category, description, evidence_examples 등을 포함합니다. "
            "이 정보는 스킬 DB 확장에 활용될 수 있습니다."
        )
    )

    success_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "배치 처리 성공률 (0.0 ~ 1.0). "
            "전체 코드 수 대비 성공적으로 처리된 코드의 비율입니다. "
            "예: 0.9 = 90% 성공 (10개 중 9개 성공). "
            "0.8 이상이면 'success', 0.8 미만이면 'partial_success' 또는 'failed' 상태입니다."
        )
    )

    failed_codes: List[CodeSample] = Field(
        default_factory=list,
        description=(
            "처리에 실패한 코드 샘플 목록. "
            "LLM 호출 실패, Pydantic validation 실패, 또는 기타 예외 발생 시 "
            "해당 코드가 이 리스트에 포함됩니다. "
            "부모 에이전트는 이 코드들을 재시도할 수 있습니다. "
            "빈 리스트면 모든 코드 처리에 성공했음을 의미합니다."
        )
    )

    processing_time: float = Field(
        ...,
        ge=0.0,
        description=(
            "이 배치를 처리하는 데 소요된 총 시간 (초 단위). "
            "임베딩 검색 + LLM 호출 + 검증 + 재시도를 모두 포함한 시간입니다. "
            "예: 3.5 (3.5초 소요). "
            "성능 모니터링 및 병목 지점 파악에 활용됩니다."
        )
    )

    retry_count: int = Field(
        default=0,
        ge=0,
        le=3,
        description=(
            "이 배치에서 수행한 재시도 횟수 (0 ~ 3). "
            "0이면 첫 시도에 성공, 1-3이면 재시도 후 성공 또는 실패를 의미합니다. "
            "최대 3회까지 재시도하며, 그 이후에도 실패하면 failed 상태로 반환됩니다."
        )
    )


# Forward references 해결을 위한 import (순환 참조 방지)
from agents.user_skill_profiler.schemas import (
    HybridConfig,
    SkillMatch,
    MissingSkillInfo,
)

# Pydantic model_rebuild for forward references
CodeBatchContext.model_rebuild()
CodeBatchResponse.model_rebuild()
