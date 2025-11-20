"""
Report Database Utility
"""
import logging
import uuid
from typing import Any, Dict, Union, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.database import AsyncSessionLocal, engine
from shared.db.models import RepositoryAnalysis, AnalysisStatus, Base

logger = logging.getLogger(__name__)


class ReportDBClient:
    """리포트 데이터를 DB에 저장하는 클라이언트"""

    @staticmethod
    async def init_db():
        """DB 및 테이블 생성 (초기화용)"""
        from shared.db.database import create_database_if_not_exists
        
        # 1. 데이터베이스 생성 확인
        await create_database_if_not_exists()
        
        # 2. 테이블 생성
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @staticmethod
    async def save_report_async(
        context: Dict[str, Any],
        response: Dict[str, Any],
        user_id: uuid.UUID,  # user_id 필수
        summary: str = ""
    ) -> RepositoryAnalysis:
        """
        리포트 데이터를 RepositoryAnalysis 테이블에 저장 (비동기)

        Args:
            context: ReporterContext 딕셔너리 (입력 데이터)
            response: ReporterResponse 딕셔너리 (출력 데이터)
            user_id: 사용자 UUID
            summary: 리포트 요약 텍스트 (선택 사항)

        Returns:
            RepositoryAnalysis: 저장된 모델 인스턴스
        """
        async with AsyncSessionLocal() as session:
            async with session.begin():
                git_url = context.get("git_url", "")
                
                # 결과 데이터 구성
                # RepositoryAnalysisResult 형태에 맞게 구성 필요
                # 현재는 context와 response를 합쳐서 저장
                analysis_result = {
                    "summary": summary,
                    "report_path": response.get("report_path", ""),
                    "static_analysis": context.get("static_analysis", {}),
                    "user_aggregate": context.get("user_aggregate", {}),
                    "domain_analysis": context.get("domain_analysis", {}),
                }

                analysis = RepositoryAnalysis(
                    user_id=user_id,
                    repository_url=git_url,
                    result=analysis_result,
                    status=AnalysisStatus.COMPLETED
                )
                
                session.add(analysis)
                await session.flush()
                logger.info(f"RepositoryAnalysis saved to DB: {analysis.id}")
                return analysis

    @staticmethod
    async def get_analysis(analysis_id: str) -> Union[RepositoryAnalysis, None]:
        """ID로 분석 결과 조회"""
        async with AsyncSessionLocal() as session:
            return await session.get(RepositoryAnalysis, uuid.UUID(analysis_id))
