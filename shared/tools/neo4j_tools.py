"""
Neo4j Tools for Deep Agents

서브에이전트가 사용할 수 있는 Neo4j 그래프 데이터베이스 접근 도구
"""

import logging
from typing import Any
from langchain_core.tools import tool
from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

# Neo4j 드라이버 (싱글톤)
_neo4j_driver: AsyncDriver | None = None


def get_neo4j_driver(uri: str, user: str, password: str) -> AsyncDriver:
    """
    Neo4j 드라이버 가져오기 (싱글톤)
    """
    global _neo4j_driver
    if _neo4j_driver is None:
        _neo4j_driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    return _neo4j_driver


@tool
async def get_user_commits(
    user_email: str,
    repo_url: str | None = None,
    limit: int = 100,
    neo4j_uri: str = "bolt://localhost:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "password",
) -> list[dict[str, Any]]:
    """
    특정 유저의 커밋 리스트 가져오기

    Args:
        user_email: 유저 이메일 또는 이름 (이메일 형식이 아니면 이름으로도 검색)
        repo_url: 레포지토리 URL (None이면 전체)
        limit: 최대 커밋 수
        neo4j_uri: Neo4j URI
        neo4j_user: Neo4j 유저명
        neo4j_password: Neo4j 비밀번호

    Returns:
        커밋 리스트 [{"hash": str, "message": str, "date": str, "lines_added": int, ...}, ...]

    Example:
        >>> commits = await get_user_commits(
        ...     user_email="user@example.com",
        ...     limit=50
        ... )
        >>> print(commits[0]["message"])
        "Add authentication feature"
    """
    try:
        driver = get_neo4j_driver(neo4j_uri, neo4j_user, neo4j_password)

        # 이메일 형식인지 확인 (@ 포함 여부)
        is_email = "@" in user_email
        
        if is_email:
            # 이메일로 검색
            query = """
            MATCH (u:User {email: $user_identifier})-[:COMMITTED]->(c:Commit)
            RETURN c.hash AS hash,
                   c.message AS message,
                   c.author_date AS date,
                   c.lines_added AS lines_added,
                   c.lines_deleted AS lines_deleted,
                   c.files_changed AS files_changed
            ORDER BY c.author_date DESC
            LIMIT $limit
            """
        else:
            # 이름으로 검색 (대소문자 무시)
            query = """
            MATCH (u:User)
            WHERE toLower(u.name) = toLower($user_identifier)
            MATCH (u)-[:COMMITTED]->(c:Commit)
            RETURN c.hash AS hash,
                   c.message AS message,
                   c.author_date AS date,
                   c.lines_added AS lines_added,
                   c.lines_deleted AS lines_deleted,
                   c.files_changed AS files_changed
            ORDER BY c.author_date DESC
            LIMIT $limit
            """

        async with driver.session() as session:
            result = await session.run(
                query,
                user_identifier=user_email,
                repo_url=repo_url,
                limit=limit,
            )
            records = await result.data()

        logger.info(f"🔍 Neo4j: user={user_email} - {len(records)}개 커밋")
        return records

    except Exception as e:
        logger.error(f"❌ Neo4j 커밋 조회 실패: {e}")
        return []


@tool
async def get_commit_details(
    commit_hash: str,
    neo4j_uri: str = "bolt://localhost:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "password",
) -> dict[str, Any]:
    """
    특정 커밋의 상세 정보 가져오기

    Args:
        commit_hash: 커밋 해시
        neo4j_uri: Neo4j URI
        neo4j_user: Neo4j 유저명
        neo4j_password: Neo4j 비밀번호

    Returns:
        커밋 상세 정보 {"hash": str, "message": str, "files": [...], ...}

    Example:
        >>> details = await get_commit_details("abc123def456")
        >>> print(details["files"])
        [{"path": "src/app.py", "added": 10, "deleted": 5}, ...]
    """
    try:
        driver = get_neo4j_driver(neo4j_uri, neo4j_user, neo4j_password)

        query = """
        MATCH (c:Commit {hash: $commit_hash})-[:MODIFIED]->(f:File)
        RETURN c.hash AS hash,
               c.message AS message,
               c.author_date AS date,
               c.lines_added AS lines_added,
               c.lines_deleted AS lines_deleted,
               collect({
                   path: f.path,
                   added: f.added_lines,
                   deleted: f.deleted_lines,
                   old_path: f.old_path,
                   new_path: f.new_path,
                   change_type: f.change_type
               }) AS files
        """

        async with driver.session() as session:
            result = await session.run(query, commit_hash=commit_hash)
            record = await result.single()

            if record:
                logger.info(f"🔍 Neo4j: commit={commit_hash} - {len(record['files'])}개 파일")
                return dict(record)
            else:
                logger.warning(f"⚠️  Neo4j: commit={commit_hash} - 결과 없음")
                return {}

    except Exception as e:
        logger.error(f"❌ Neo4j 커밋 상세 조회 실패: {e}")
        return {}


@tool
async def get_file_history(
    file_path: str,
    user_email: str | None = None,
    limit: int = 50,
    neo4j_uri: str = "bolt://localhost:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "password",
) -> list[dict[str, Any]]:
    """
    특정 파일의 수정 이력 가져오기

    Args:
        file_path: 파일 경로
        user_email: 유저 이메일 (None이면 전체 유저)
        limit: 최대 커밋 수
        neo4j_uri: Neo4j URI
        neo4j_user: Neo4j 유저명
        neo4j_password: Neo4j 비밀번호

    Returns:
        커밋 리스트

    Example:
        >>> history = await get_file_history(
        ...     file_path="src/models.py",
        ...     user_email="user@example.com"
        ... )
    """
    try:
        driver = get_neo4j_driver(neo4j_uri, neo4j_user, neo4j_password)

        query = """
        MATCH (c:Commit)-[:MODIFIED]->(f:File {path: $file_path})
        WHERE $user_email IS NULL OR EXISTS {
            MATCH (u:User {email: $user_email})-[:COMMITTED]->(c)
        }
        RETURN c.hash AS hash,
               c.message AS message,
               c.author_date AS date,
               f.added_lines AS added_lines,
               f.deleted_lines AS deleted_lines
        ORDER BY c.author_date DESC
        LIMIT $limit
        """

        async with driver.session() as session:
            result = await session.run(
                query,
                file_path=file_path,
                user_email=user_email,
                limit=limit,
            )
            records = await result.data()

        logger.info(f"🔍 Neo4j: file={file_path} - {len(records)}개 커밋")
        return records

    except Exception as e:
        logger.error(f"❌ Neo4j 파일 이력 조회 실패: {e}")
        return []


@tool
async def get_user_stats(
    user_email: str,
    repo_url: str | None = None,
    neo4j_uri: str = "bolt://localhost:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "password",
) -> dict[str, Any]:
    """
    유저 통계 가져오기

    Args:
        user_email: 유저 이메일
        repo_url: 레포지토리 URL (None이면 전체)
        neo4j_uri: Neo4j URI
        neo4j_user: Neo4j 유저명
        neo4j_password: Neo4j 비밀번호

    Returns:
        통계 정보 {"total_commits": int, "total_lines_added": int, ...}

    Example:
        >>> stats = await get_user_stats("user@example.com")
        >>> print(stats["total_commits"])
        152
    """
    try:
        driver = get_neo4j_driver(neo4j_uri, neo4j_user, neo4j_password)

        query = """
        MATCH (u:User {email: $user_email})-[:COMMITTED]->(c:Commit)
        WITH u, c
        MATCH (c)-[:MODIFIED]->(f:File)
        RETURN count(DISTINCT c) AS total_commits,
               sum(c.lines_added) AS total_lines_added,
               sum(c.lines_deleted) AS total_lines_deleted,
               count(DISTINCT f) AS total_files_modified
        """

        async with driver.session() as session:
            result = await session.run(
                query,
                user_email=user_email,
                repo_url=repo_url,
            )
            record = await result.single()

            if record:
                stats = dict(record)
                logger.info(f"📊 Neo4j: user={user_email} - {stats['total_commits']}개 커밋")
                return stats
            else:
                return {
                    "total_commits": 0,
                    "total_lines_added": 0,
                    "total_lines_deleted": 0,
                    "total_files_modified": 0,
                }

    except Exception as e:
        logger.error(f"❌ Neo4j 유저 통계 조회 실패: {e}")
        return {}


@tool
async def query_graph(
    cypher_query: str,
    parameters: dict[str, Any] | None = None,
    neo4j_uri: str = "bolt://localhost:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "password",
) -> list[dict[str, Any]]:
    """
    임의의 Cypher 쿼리 실행

    Args:
        cypher_query: Cypher 쿼리 문자열
        parameters: 쿼리 파라미터
        neo4j_uri: Neo4j URI
        neo4j_user: Neo4j 유저명
        neo4j_password: Neo4j 비밀번호

    Returns:
        쿼리 결과 리스트

    Example:
        >>> results = await query_graph(
        ...     cypher_query="MATCH (u:User) RETURN u.email AS email LIMIT 10"
        ... )
    """
    try:
        driver = get_neo4j_driver(neo4j_uri, neo4j_user, neo4j_password)

        async with driver.session() as session:
            result = await session.run(cypher_query, **(parameters or {}))
            records = await result.data()

        logger.info(f"🔍 Neo4j: 커스텀 쿼리 - {len(records)}개 결과")
        return records

    except Exception as e:
        logger.error(f"❌ Neo4j 커스텀 쿼리 실패: {e}")
        return []
