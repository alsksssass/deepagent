"""CodeRAGBuilder Schemas"""

from pydantic import BaseModel, Field
from shared.schemas.common import BaseContext, BaseResponse


class CodeRAGBuilderContext(BaseContext):
    """CodeRAGBuilder 입력 스키마"""

    repo_path: str = Field(..., description="레포지토리 경로")
    persist_dir: str = Field(
        default="./data/chroma_db", description="ChromaDB 저장 디렉토리"
    )


class CodeRAGBuilderResponse(BaseResponse):
    """CodeRAGBuilder 출력 스키마"""

    total_files: int = Field(default=0, ge=0, description="처리된 파일 수")
    total_chunks: int = Field(default=0, ge=0, description="생성된 청크 수")
    collection_name: str = Field(default="", description="ChromaDB 컬렉션 이름")
