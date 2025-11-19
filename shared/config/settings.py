"""
Deep Agents Configuration Settings

환경변수 우선 + 기본값 fallback 방식으로 설정 관리
"""

from enum import Enum
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageBackend(str, Enum):
    """Storage Backend 타입"""
    LOCAL = "local"
    S3 = "s3"


class GraphDBBackend(str, Enum):
    """Graph Database Backend 타입"""
    NEO4J = "neo4j"
    NEPTUNE = "neptune"


class VectorDBBackend(str, Enum):
    """Vector Database Backend 타입"""
    CHROMADB = "chromadb"
    PGVECTOR = "pgvector"


class Settings(BaseSettings):
    """Deep Agents 통합 설정

    환경변수 로딩 우선순위:
    1. 환경변수 (.env 파일 또는 시스템 환경변수)
    2. 코드 기본값 (fallback)

    사용법:
        # 로컬 개발
        python main.py  # .env 파일 자동 로딩

        # AWS 환경
        export STORAGE_BACKEND=s3
        export S3_BUCKET_NAME=deep-agents-results-prod
        python main.py
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # 알 수 없는 환경변수 무시
    )

    # === Storage Backend ===
    STORAGE_BACKEND: StorageBackend = StorageBackend.LOCAL

    # S3 설정 (STORAGE_BACKEND=s3일 때 필수)
    S3_BUCKET_NAME: str = "deep-agents-results"
    S3_REGION: str = "us-east-1"
    S3_LIFECYCLE_DAYS: int = 30

    # Local 설정
    LOCAL_DATA_DIR: Path = Path("./data")

    # === Graph Database ===
    GRAPH_DB_BACKEND: GraphDBBackend = GraphDBBackend.NEO4J

    # Neo4j 설정
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    # Neptune 설정 (GRAPH_DB_BACKEND=neptune일 때 필수)
    NEPTUNE_ENDPOINT: str = ""
    NEPTUNE_PORT: int = 8182
    NEPTUNE_USE_IAM: bool = True

    # === Vector Database ===
    VECTOR_DB_BACKEND: VectorDBBackend = VectorDBBackend.CHROMADB

    # ChromaDB 설정
    CHROMADB_PERSIST_DIR: Path = Path("./data/chroma_db")

    # pgvector 설정 (VECTOR_DB_BACKEND=pgvector일 때 필수)
    PGVECTOR_HOST: str = ""
    PGVECTOR_PORT: int = 5432
    PGVECTOR_DATABASE: str = "deep_agents"
    PGVECTOR_USER: str = "postgres"
    PGVECTOR_PASSWORD: str = ""

    # === AWS 공통 ===
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    def validate_backend_requirements(self):
        """백엔드별 필수 설정 검증

        Raises:
            ValueError: 필수 설정이 누락된 경우
        """
        # S3 사용 시 bucket_name 필수
        if self.STORAGE_BACKEND == StorageBackend.S3:
            if not self.S3_BUCKET_NAME:
                raise ValueError(
                    "S3_BUCKET_NAME is required when STORAGE_BACKEND=s3"
                )

        # Neptune 사용 시 endpoint 필수
        if self.GRAPH_DB_BACKEND == GraphDBBackend.NEPTUNE:
            if not self.NEPTUNE_ENDPOINT:
                raise ValueError(
                    "NEPTUNE_ENDPOINT is required when GRAPH_DB_BACKEND=neptune"
                )

        # pgvector 사용 시 host 필수
        if self.VECTOR_DB_BACKEND == VectorDBBackend.PGVECTOR:
            if not self.PGVECTOR_HOST:
                raise ValueError(
                    "PGVECTOR_HOST is required when VECTOR_DB_BACKEND=pgvector"
                )

    def get_storage_info(self) -> dict:
        """현재 Storage 설정 정보 반환"""
        if self.STORAGE_BACKEND == StorageBackend.S3:
            return {
                "backend": "s3",
                "bucket": self.S3_BUCKET_NAME,
                "region": self.S3_REGION,
            }
        else:
            return {
                "backend": "local",
                "data_dir": str(self.LOCAL_DATA_DIR),
            }

    def get_graph_db_info(self) -> dict:
        """현재 Graph DB 설정 정보 반환"""
        if self.GRAPH_DB_BACKEND == GraphDBBackend.NEPTUNE:
            return {
                "backend": "neptune",
                "endpoint": self.NEPTUNE_ENDPOINT,
                "port": self.NEPTUNE_PORT,
            }
        else:
            return {
                "backend": "neo4j",
                "uri": self.NEO4J_URI,
                "user": self.NEO4J_USER,
            }

    def get_vector_db_info(self) -> dict:
        """현재 Vector DB 설정 정보 반환"""
        if self.VECTOR_DB_BACKEND == VectorDBBackend.PGVECTOR:
            return {
                "backend": "pgvector",
                "host": self.PGVECTOR_HOST,
                "port": self.PGVECTOR_PORT,
                "database": self.PGVECTOR_DATABASE,
            }
        else:
            return {
                "backend": "chromadb",
                "persist_dir": str(self.CHROMADB_PERSIST_DIR),
            }


# 싱글톤 인스턴스
settings = Settings()
