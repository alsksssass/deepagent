"""
SQLAlchemy Models for Analysis Results

AWS RDS PostgreSQL에 저장되는 분석 결과 모델
"""

from sqlalchemy import Column, String, JSON, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from enum import Enum
import uuid
from datetime import datetime, timezone

Base = declarative_base()


class AnalysisStatus(str, Enum):
    """분석 상태"""
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def utc_now():
    """UTC 현재 시간 (timezone-aware)"""
    return datetime.now(timezone.utc)


class RepositoryAnalysis(Base):
    """
    각 레포지토리별 분석 결과를 저장하는 테이블

    UserAggregatorResponse 결과를 JSON으로 저장

    Note: user_id는 UUID 타입이지만 FK 제약조건 없음 (users 테이블 미존재 시 대응)
    """
    __tablename__ = "repository_analysis"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)  # FK 제약조건 제거
    repository_url = Column(String, index=True, nullable=False)
    result = Column(JSON, nullable=True)  # UserAggregatorResponse 형태의 JSON

    status = Column(SQLEnum(AnalysisStatus), default=AnalysisStatus.PROCESSING, nullable=False)
    error_message = Column(String, nullable=True)

    task_uuid = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<RepositoryAnalysis(id={self.id}, url={self.repository_url}, status={self.status})>"


class Analysis(Base):
    """
    모든 분석이 끝난 후 종합 분석 결과를 저장하는 테이블

    UserAnalysisResult 결과를 JSON으로 저장

    Note: user_id는 UUID 타입이지만 FK 제약조건 없음 (users 테이블 미존재 시 대응)
    """
    __tablename__ = "analysis"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)  # FK 제약조건 제거
    repository_url = Column(String, index=True, nullable=False)  # 대표 레포지토리 URL
    result = Column(JSON, nullable=True)  # UserAnalysisResult 형태의 JSON

    status = Column(SQLEnum(AnalysisStatus), default=AnalysisStatus.PROCESSING, nullable=False)
    error_message = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<Analysis(id={self.id}, user_id={self.user_id}, status={self.status})>"
