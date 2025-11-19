"""SkillChartsRAGBuilder Schemas"""

from pydantic import BaseModel, Field
from typing import List
from shared.schemas.common import BaseContext, BaseResponse


class SkillChartsRAGBuilderContext(BaseContext):
    """SkillChartsRAGBuilder 입력 스키마"""

    skill_charts_path: str = Field(..., description="skill_charts.csv 파일 경로")
    persist_dir: str = Field(
        default="./data/chroma_db", description="ChromaDB 저장 디렉토리"
    )


class SkillChartsRAGBuilderResponse(BaseResponse):
    """SkillChartsRAGBuilder 출력 스키마"""

    total_skills: int = Field(default=0, ge=0, description="저장된 스킬 수")
    categories: List[str] = Field(default_factory=list, description="카테고리 목록")
    collection_name: str = Field(default="", description="ChromaDB 컬렉션 이름")
    message: str = Field(default="", description="추가 메시지 (기존 컬렉션 재사용 시 등)")
