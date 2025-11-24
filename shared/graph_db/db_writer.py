"""
Singleton DB Writer for Analysis Results

AWS RDS PostgreSQL에 분석 결과를 저장하는 싱글톤 헬퍼 클래스
"""

from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import logging
import os
from urllib.parse import quote_plus

from .models import Base, RepositoryAnalysis, Analysis, AnalysisStatus

logger = logging.getLogger(__name__)


class AnalysisDBWriter:
    """
    싱글톤 DB Writer

    분석 결과를 AWS RDS PostgreSQL에 저장하는 헬퍼 클래스

    Usage:
        # 초기화 (앱 시작 시 1회)
        await AnalysisDBWriter.initialize()

        # 사용 (어디서든)
        db_writer = AnalysisDBWriter.get_instance()
        await db_writer.save_repository_analysis(...)

        # 종료 (앱 종료 시)
        await AnalysisDBWriter.close()
    """

    _instance: Optional['AnalysisDBWriter'] = None
    _engine: Optional[AsyncEngine] = None
    _session_factory: Optional[sessionmaker] = None
    _initialized: bool = False

    def __init__(self):
        """직접 생성 금지, get_instance() 사용"""
        if AnalysisDBWriter._instance is not None:
            raise RuntimeError("Use AnalysisDBWriter.get_instance() instead")

    @classmethod
    async def initialize(
        cls,
        database_url: Optional[str] = None,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        create_tables: bool = False
    ) -> 'AnalysisDBWriter':
        """
        싱글톤 인스턴스 초기화

        Args:
            database_url: DB 연결 URL (None이면 환경 변수 사용)
            echo: SQL 로그 출력 여부
            pool_size: 커넥션 풀 크기
            max_overflow: 커넥션 풀 오버플로우
            create_tables: 테이블 자동 생성 여부 (개발 환경 전용)

        Returns:
            초기화된 싱글톤 인스턴스
        """
        if cls._initialized:
            logger.info("ℹ️  AnalysisDBWriter already initialized")
            return cls._instance

        try:
            # DB URL 생성: 파라미터 우선, 없으면 환경 변수 조합
            if database_url is None:
                db_host = os.getenv("POSTGRES_HOST", "localhost")
                db_port = os.getenv("POSTGRES_PORT", "5432")
                db_name = os.getenv("POSTGRES_DB", "sesami")
                db_user = os.getenv("POSTGRES_USER", "postgres")
                db_password = os.getenv("POSTGRES_PASSWORD", "password")

                # 비밀번호 URL 인코딩 (특수문자 처리)
                encoded_password = quote_plus(db_password)

                # SSL 모드 추가 (AWS RDS 연결 시 필요)
                database_url = f"postgresql+asyncpg://{db_user}:{encoded_password}@{db_host}:{db_port}/{db_name}?ssl=require"

            # Echo 설정: 환경 변수 우선
            echo = os.getenv("POSTGRES_ECHO", "false").lower() == "true" or echo

            # AsyncEngine 생성
            cls._engine = create_async_engine(
                database_url,
                echo=echo,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_pre_ping=True,  # 연결 체크
                pool_recycle=3600,  # 1시간마다 커넥션 재생성
            )

            # AsyncSession Factory 생성
            cls._session_factory = sessionmaker(
                cls._engine,
                class_=AsyncSession,
                expire_on_commit=False
            )

            # 테이블 생성 (개발 환경 전용)
            if create_tables:
                async with cls._engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                logger.info("📊 테이블 생성 완료 (개발 모드)")

            # 싱글톤 인스턴스 생성
            cls._instance = object.__new__(cls)
            cls._initialized = True

            # 연결 테스트
            async with cls._session_factory() as session:
                await session.execute(select(1))

            db_host_display = database_url.split('@')[1].split('/')[0] if '@' in database_url else 'local'
            logger.info(f"✅ AnalysisDBWriter 초기화 완료: {db_host_display}")

        except Exception as e:
            logger.error(f"❌ AnalysisDBWriter 초기화 실패: {e}")
            raise

        return cls._instance

    @classmethod
    def get_instance(cls) -> 'AnalysisDBWriter':
        """
        싱글톤 인스턴스 반환

        Returns:
            싱글톤 인스턴스

        Raises:
            RuntimeError: 초기화되지 않은 경우
        """
        if cls._instance is None or not cls._initialized:
            raise RuntimeError(
                "AnalysisDBWriter not initialized. "
                "Call await AnalysisDBWriter.initialize() first."
            )
        return cls._instance

    @classmethod
    async def close(cls):
        """엔진 종료 (앱 종료 시)"""
        if cls._engine:
            await cls._engine.dispose()
            cls._engine = None
            cls._session_factory = None
            cls._instance = None
            cls._initialized = False
            logger.info("🔒 AnalysisDBWriter 종료")

    def _get_session(self) -> AsyncSession:
        """세션 생성 (컨텍스트 매니저용)"""
        if not self._session_factory:
            raise RuntimeError("Session factory not initialized")
        return self._session_factory()

    async def save_repository_analysis(
        self,
        user_id: UUID,
        repository_url: str,
        result: dict,  # UserAggregatorResponse.model_dump()
        task_uuid: UUID,
        main_task_uuid: Optional[UUID] = None,  # 멀티 분석 시 종합 분석과 연결
        status: AnalysisStatus = AnalysisStatus.COMPLETED,
        error_message: Optional[str] = None
    ) -> RepositoryAnalysis:
        """
        각 레포지토리 분석 결과 저장

        Args:
            user_id: 사용자 UUID
            repository_url: 레포지토리 URL
            result: UserAggregatorResponse.model_dump() 결과
            task_uuid: 작업 UUID (레포별)
            main_task_uuid: 메인 작업 UUID (종합 분석용, 옵셔널)
            status: 분석 상태
            error_message: 에러 메시지 (실패 시)

        Returns:
            저장된 RepositoryAnalysis 객체
        """
        async with self._get_session() as session:
            async with session.begin():
                repo_analysis = RepositoryAnalysis(
                    user_id=user_id,
                    repository_url=repository_url,
                    result=result,
                    task_uuid=task_uuid,
                    main_task_uuid=main_task_uuid,
                    status=status,
                    error_message=error_message
                )
                session.add(repo_analysis)

            await session.commit()
            await session.refresh(repo_analysis)

            logger.info(
                f"📥 레포지토리 분석 결과 저장: {repository_url} "
                f"(task: {task_uuid}, status: {status})"
            )
            return repo_analysis

    async def save_final_analysis(
        self,
        user_id: UUID,
        repository_url: str,  # 대표 레포지토리 URL
        result: dict,  # RepoSynthesizerResponse.model_dump() 결과
        main_task_uuid: UUID,  # 종합 분석 식별자
        status: AnalysisStatus = AnalysisStatus.COMPLETED,
        error_message: Optional[str] = None
    ) -> Analysis:
        """
        전체 종합 분석 결과 저장

        Args:
            user_id: 사용자 UUID
            repository_url: 대표 레포지토리 URL
            result: RepoSynthesizerResponse.model_dump() 결과
            main_task_uuid: 메인 작업 UUID (종합 분석용, 필수)
            status: 분석 상태
            error_message: 에러 메시지 (실패 시)

        Returns:
            저장된 Analysis 객체
        """
        async with self._get_session() as session:
            async with session.begin():
                analysis = Analysis(
                    user_id=user_id,
                    repository_url=repository_url,
                    result=result,
                    main_task_uuid=main_task_uuid,
                    status=status,
                    error_message=error_message
                )
                session.add(analysis)

            await session.commit()
            await session.refresh(analysis)

            tech_count = len(result.get('tech_stack', []))
            logger.info(
                f"📊 종합 분석 결과 저장: user_id={user_id}, "
                f"techs={tech_count}, status={status}"
            )
            return analysis

    async def update_repository_status(
        self,
        task_uuid: UUID,
        status: AnalysisStatus,
        error_message: Optional[str] = None
    ) -> bool:
        """
        레포지토리 분석 상태 업데이트

        Args:
            task_uuid: 작업 UUID
            status: 새로운 상태
            error_message: 에러 메시지 (실패 시)

        Returns:
            업데이트 성공 여부
        """
        async with self._get_session() as session:
            async with session.begin():
                stmt = (
                    select(RepositoryAnalysis)
                    .where(RepositoryAnalysis.task_uuid == task_uuid)
                )
                result = await session.execute(stmt)
                repo_analysis = result.scalar_one_or_none()

                if repo_analysis:
                    repo_analysis.status = status
                    repo_analysis.error_message = error_message
                    await session.commit()
                    logger.info(f"🔄 레포지토리 분석 상태 업데이트: {task_uuid} → {status}")
                    return True
                else:
                    logger.warning(f"⚠️  task_uuid {task_uuid} 찾을 수 없음")
                    return False

    async def update_repository_result(
        self,
        task_uuid: UUID,
        result: dict,
        main_task_uuid: Optional[UUID] = None,  # 업데이트 시 main_task_uuid 추가 가능
        status: AnalysisStatus = AnalysisStatus.COMPLETED,
        error_message: Optional[str] = None
    ) -> bool:
        """
        레포지토리 분석 결과 및 상태 업데이트

        Args:
            task_uuid: 작업 UUID
            result: UserAggregatorResponse.model_dump() 결과
            main_task_uuid: 메인 작업 UUID (업데이트 시 추가, 옵셔널)
            status: 새로운 상태 (기본값: COMPLETED)
            error_message: 에러 메시지 (실패 시)

        Returns:
            업데이트 성공 여부
        """
        async with self._get_session() as session:
            async with session.begin():
                stmt = (
                    select(RepositoryAnalysis)
                    .where(RepositoryAnalysis.task_uuid == task_uuid)
                )
                query_result = await session.execute(stmt)
                repo_analysis = query_result.scalar_one_or_none()

                if repo_analysis:
                    repo_analysis.result = result
                    if main_task_uuid is not None:  # main_task_uuid가 제공되면 업데이트
                        repo_analysis.main_task_uuid = main_task_uuid
                    repo_analysis.status = status
                    repo_analysis.error_message = error_message
                    await session.commit()
                    logger.info(f"📥 레포지토리 분석 결과 업데이트: {task_uuid} → {status}")
                    return True
                else:
                    logger.warning(f"⚠️  task_uuid {task_uuid} 찾을 수 없음")
                    return False

    async def update_final_analysis(
        self,
        main_task_uuid: UUID,
        result: dict,
        status: AnalysisStatus = AnalysisStatus.COMPLETED,
        error_message: Optional[str] = None
    ) -> bool:
        """
        종합 분석 결과 및 상태 업데이트

        Args:
            main_task_uuid: 메인 작업 UUID (종합 분석 식별자)
            result: RepoSynthesizerResponse.model_dump() 결과
            status: 새로운 상태 (기본값: COMPLETED)
            error_message: 에러 메시지 (실패 시)

        Returns:
            업데이트 성공 여부
        """
        async with self._get_session() as session:
            async with session.begin():
                stmt = (
                    select(Analysis)
                    .where(Analysis.main_task_uuid == main_task_uuid)
                )
                query_result = await session.execute(stmt)
                analysis = query_result.scalar_one_or_none()

                if analysis:
                    analysis.result = result
                    analysis.status = status
                    analysis.error_message = error_message
                    await session.commit()
                    tech_count = len(result.get('tech_stack', []))
                    logger.info(
                        f"📊 종합 분석 결과 업데이트: main_task={main_task_uuid}, "
                        f"techs={tech_count}, status={status}"
                    )
                    return True
                else:
                    logger.warning(f"⚠️  main_task_uuid {main_task_uuid} 찾을 수 없음")
                    return False

    async def get_repository_analysis(
        self,
        task_uuid: UUID
    ) -> Optional[RepositoryAnalysis]:
        """
        task_uuid로 레포지토리 분석 결과 조회

        Args:
            task_uuid: 작업 UUID

        Returns:
            RepositoryAnalysis 객체 또는 None
        """
        async with self._get_session() as session:
            stmt = (
                select(RepositoryAnalysis)
                .where(RepositoryAnalysis.task_uuid == task_uuid)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_user_analyses(
        self,
        user_id: UUID,
        limit: int = 10
    ) -> list[Analysis]:
        """
        특정 유저의 종합 분석 결과 조회

        Args:
            user_id: 사용자 UUID
            limit: 최대 조회 개수

        Returns:
            Analysis 객체 리스트
        """
        async with self._get_session() as session:
            stmt = (
                select(Analysis)
                .where(Analysis.user_id == user_id)
                .order_by(Analysis.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_user_access_token(self, user_id: UUID) -> Optional[str]:
        """
        사용자의 Git 액세스 토큰 조회

        Args:
            user_id: 사용자 UUID

        Returns:
            access_token 문자열 또는 None (토큰이 없거나 사용자가 없는 경우)
        """
        try:
            async with self._get_session() as session:
                # users 테이블에서 access_token 조회
                # SQLAlchemy Core를 사용하여 직접 쿼리 (모델이 없을 수 있음)
                from sqlalchemy import text
                
                stmt = text("SELECT access_token FROM users WHERE id = :user_id")
                result = await session.execute(stmt, {"user_id": str(user_id)})
                row = result.fetchone()
                
                if row and row[0]:
                    token = row[0]
                    # 토큰 마스킹하여 로그 출력 (보안)
                    masked_token = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else "****"
                    logger.debug(f"✅ 사용자 {user_id}의 액세스 토큰 조회 성공: {masked_token}")
                    return token
                else:
                    logger.debug(f"ℹ️  사용자 {user_id}의 액세스 토큰이 없습니다")
                    return None
        except Exception as e:
            # users 테이블이 없거나 오류 발생 시 None 반환 (퍼블릭 레포 시도)
            logger.warning(f"⚠️  액세스 토큰 조회 실패 (사용자 {user_id}): {e}")
            return None
