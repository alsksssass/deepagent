"""
Database Connection Utility
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.config.settings import settings

# PostgreSQL Connection URL
# asyncpg 드라이버 사용
SQLALCHEMY_DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@"
    f"{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=settings.POSTGRES_ECHO,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 등의 의존성 주입을 위한 DB 세션 생성기
    Context Manager로도 사용 가능
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_database_if_not_exists():
    """데이터베이스가 없으면 생성"""
    import logging
    from sqlalchemy import text
    
    logger = logging.getLogger(__name__)
    target_db = settings.POSTGRES_DB
    
    # postgres 기본 DB로 접속하는 URL 생성
    # 기존 URL: postgresql+asyncpg://user:pass@host:port/target_db
    # 변경 URL: postgresql+asyncpg://user:pass@host:port/postgres
    postgres_db_url = SQLALCHEMY_DATABASE_URL.rsplit('/', 1)[0] + '/postgres'
    
    # CREATE DATABASE는 트랜잭션 블록 안에서 실행 불가 -> isolation_level="AUTOCOMMIT"
    temp_engine = create_async_engine(
        postgres_db_url,
        isolation_level="AUTOCOMMIT",
        echo=settings.POSTGRES_ECHO
    )
    
    try:
        async with temp_engine.connect() as conn:
            # DB 존재 여부 확인
            result = await conn.execute(
                text(f"SELECT 1 FROM pg_database WHERE datname = '{target_db}'")
            )
            if not result.scalar():
                logger.info(f"Database '{target_db}' does not exist. Creating...")
                # 식별자 quoting 처리
                await conn.execute(text(f'CREATE DATABASE "{target_db}"'))
                logger.info(f"Database '{target_db}' created successfully.")
            else:
                logger.info(f"Database '{target_db}' already exists.")
    except Exception as e:
        logger.error(f"Failed to check/create database: {e}")
        # 권한 문제 등으로 실패할 수 있으나, 이미 존재할 수도 있으므로 
        # 치명적이지 않은 경우를 위해 로그만 남기고 넘어갈 수도 있지만,
        # 여기서는 명시적으로 실패를 알림
        raise
    finally:
        await temp_engine.dispose()
