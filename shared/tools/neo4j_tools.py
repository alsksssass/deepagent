"""
Neo4j Tools for Deep Agents

서브에이전트가 사용할 수 있는 Neo4j 그래프 데이터베이스 접근 도구
GraphDBBackend 추상화 레이어 사용
"""

import logging
from typing import Any
from langchain_core.tools import tool

from shared.graph_db import create_graph_db_backend, GraphDBBackend

logger = logging.getLogger(__name__)

# GraphDB 백엔드 (싱글톤)
_graph_db_backend: GraphDBBackend | None = None


def get_graph_db_backend() -> GraphDBBackend:
    """
    GraphDB 백엔드 가져오기 (싱글톤)
    환경변수 기반으로 자동 설정 (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    """
    global _graph_db_backend
    if _graph_db_backend is None:
        _graph_db_backend = create_graph_db_backend()
    return _graph_db_backend


@tool
async def get_user_commits(
    user_email: str,
    repo_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    특정 유저의 커밋 리스트 가져오기

    Args:
        user_email: 유저 이메일 또는 이름 (이메일 형식이 아니면 이름으로도 검색)
        repo_id: Repository ID (⚠️ 필수: 복합 키 제약조건 때문에 필수입니다)
        limit: 최대 커밋 수

    Returns:
        커밋 리스트 [{"hash": str, "message": str, "date": str, "lines_added": int, ...}, ...]

    Example:
        >>> commits = await get_user_commits(
        ...     user_email="user@example.com",
        ...     repo_id="github_user_repo",  # 필수
        ...     limit=50
        ... )
        >>> print(commits[0]["message"])
        "Add authentication feature"
    """
    try:
        backend = get_graph_db_backend()
        commits = await backend.get_user_commits(
            user_email=user_email,
            repo_id=repo_id,
            limit=limit
        )
        return commits

    except Exception as e:
        logger.error(f"❌ GraphDB 커밋 조회 실패: {e}")
        return []


@tool
async def get_commit_details(
    commit_hash: str,
    repo_id: str | None = None,
) -> dict[str, Any]:
    """
    특정 커밋의 상세 정보 가져오기

    Args:
        commit_hash: 커밋 해시
        repo_id: Repository ID (⚠️ 필수: 복합 키 제약조건 때문에 필수입니다)

    Returns:
        커밋 상세 정보 {"hash": str, "message": str, "files": [...], ...}

    Example:
        >>> details = await get_commit_details(
        ...     commit_hash="abc123def456",
        ...     repo_id="github_user_repo"  # 필수
        ... )
        >>> print(details["files"])
        [{"path": "src/app.py", "added": 10, "deleted": 5}, ...]
    """
    try:
        backend = get_graph_db_backend()
        details = await backend.get_commit_details(
            commit_hash=commit_hash,
            repo_id=repo_id
        )
        return details

    except Exception as e:
        logger.error(f"❌ GraphDB 커밋 상세 조회 실패: {e}")
        return {}


@tool
async def get_file_history(
    file_path: str,
    user_email: str | None = None,
    repo_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    특정 파일의 수정 이력 가져오기

    Args:
        file_path: 파일 경로
        user_email: 유저 이메일 (None이면 전체 유저)
        repo_id: Repository ID (⚠️ 필수: 복합 키 제약조건 때문에 필수입니다)
        limit: 최대 커밋 수

    Returns:
        커밋 리스트

    Example:
        >>> history = await get_file_history(
        ...     file_path="src/models.py",
        ...     user_email="user@example.com",
        ...     repo_id="github_user_repo"  # 필수
        ... )
    """
    try:
        backend = get_graph_db_backend()
        history = await backend.get_file_history(
            file_path=file_path,
            user_email=user_email,
            repo_id=repo_id,
            limit=limit
        )
        return history

    except Exception as e:
        logger.error(f"❌ GraphDB 파일 이력 조회 실패: {e}")
        return []


@tool
async def get_user_stats(
    user_email: str,
    repo_id: str | None = None,
) -> dict[str, Any]:
    """
    유저 통계 가져오기

    Args:
        user_email: 유저 이메일
        repo_id: Repository ID (⚠️ 필수: 복합 키 제약조건 때문에 필수입니다)

    Returns:
        통계 정보 {"total_commits": int, "total_lines_added": int, ...}

    Example:
        >>> stats = await get_user_stats(
        ...     user_email="user@example.com",
        ...     repo_id="github_user_repo"  # 필수
        ... )
        >>> print(stats["total_commits"])
        152
    """
    try:
        backend = get_graph_db_backend()
        stats = await backend.get_user_stats(
            user_email=user_email,
            repo_id=repo_id
        )
        return stats

    except Exception as e:
        logger.error(f"❌ GraphDB 유저 통계 조회 실패: {e}")
        return {}


@tool
async def query_graph(
    cypher_query: str,
    parameters: dict[str, Any] | None = None,
    repo_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    임의의 Cypher 쿼리 실행

    Args:
        cypher_query: Cypher 쿼리 문자열
        parameters: 쿼리 파라미터
        repo_id: Repository ID (None이면 전체)

    Returns:
        쿼리 결과 리스트

    Example:
        >>> results = await query_graph(
        ...     cypher_query="MATCH (u:User) RETURN u.email AS email LIMIT 10"
        ... )
    """
    try:
        backend = get_graph_db_backend()
        results = await backend.execute_query(
            query=cypher_query,
            params=parameters,
            repo_id=repo_id
        )
        return results

    except Exception as e:
        logger.error(f"❌ GraphDB 커스텀 쿼리 실패: {e}")
        return []
