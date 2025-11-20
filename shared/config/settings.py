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
    """Graph Database Backend 타입 (Neo4j 전용)"""
    NEO4J = "neo4j"


class VectorDBBackend(str, Enum):
    """Vector Database Backend 타입 (ChromaDB 전용)"""
    CHROMADB = "chromadb"


class DBBackend(str, Enum):
    """RDBMS Backend 타입"""
    POSTGRES = "postgres"


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

    # === Graph Database (Neo4j) ===
    # 로컬 개발: bolt://localhost:7687
    # AWS EC2: bolt://ec2-xxx-xxx-xxx-xxx.compute.amazonaws.com:7687
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    # === Vector Database (ChromaDB) ===
    # 로컬 개발: http://localhost:8000
    # AWS EC2: http://ec2-xxx-xxx-xxx-xxx.compute.amazonaws.com:8000
    CHROMADB_HOST: str = "localhost"
    CHROMADB_PORT: int = 8000
    CHROMADB_AUTH_TOKEN: str = ""  # 프로덕션에서는 필수
    
    # ChromaDB Persist 디렉토리
    # 코드 RAG용: 일반적으로 작업별로 생성 (code_{task_uuid})
    # 스킬 차트용: 전역으로 공유되는 스킬 차트 데이터 (격리 필요)
    SKILL_CHARTS_CHROMADB_DIR: Path = Path("./data/chroma_db_skill_charts")

    # === RDBMS (PostgreSQL) ===
    DB_BACKEND: DBBackend = DBBackend.POSTGRES
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "deep_agents"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_ECHO: bool = False  # SQL 로그 출력 여부

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
        """현재 Graph DB 설정 정보 반환 (Neo4j)"""
        return {
            "backend": "neo4j",
            "uri": self.NEO4J_URI,
            "user": self.NEO4J_USER,
        }

    def get_vector_db_info(self) -> dict:
        """현재 Vector DB 설정 정보 반환 (ChromaDB)"""
        return {
            "backend": "chromadb",
            "host": self.CHROMADB_HOST,
            "port": self.CHROMADB_PORT,
        }

    def get_db_info(self) -> dict:
        """현재 RDBMS 설정 정보 반환"""
        return {
            "backend": "postgres",
            "host": self.POSTGRES_HOST,
            "port": self.POSTGRES_PORT,
            "db": self.POSTGRES_DB,
            "user": self.POSTGRES_USER,
        }


# 싱글톤 인스턴스
settings = Settings()
