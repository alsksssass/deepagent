"""
Database Models for Deep Agents
"""
import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import DeclarativeBase

def utc_now():
    return datetime.now(timezone.utc)

class AnalysisStatus(str, enum.Enum):
    WAITING = "WAITING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Base(DeclarativeBase):
    pass

# 각 레포지토리별 분석 결과를 저장하는 테이블
class RepositoryAnalysis(Base):
    __tablename__ = "repository_analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    # user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    # NOTE: users 테이블이 아직 정의되지 않았으므로 ForeignKey 임시 주석 처리
    user_id = Column(UUID(as_uuid=True), nullable=False)
    
    repository_url = Column(String, index=True)
    result = Column(JSON, nullable=True) # RepositoryAnalysisResult 형태의 JSON

    status = Column(Enum(AnalysisStatus), default=AnalysisStatus.PROCESSING)
    error_message = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

# 모든 분석이 끝난 후 종합 분석 결과를 저장하는 테이블
class Analysis(Base):
    __tablename__ = "analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    # user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    # NOTE: users 테이블이 아직 정의되지 않았으므로 ForeignKey 임시 주석 처리
    user_id = Column(UUID(as_uuid=True), nullable=False)
    
    repository_url = Column(String, index=True)
    # target_user = Column(String, nullable=False) # 분석 대상 GitHub 사용자명 -> username
    result = Column(JSON, nullable=True) # UserAnalysisResult 형태의 JSON

    status = Column(Enum(AnalysisStatus), default=AnalysisStatus.PROCESSING)
    error_message = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
