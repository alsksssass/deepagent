"""
ChromaDB Tools for Deep Agents

서브에이전트가 사용할 수 있는 ChromaDB 접근 도구
"""

import logging
from typing import Any
from langchain_core.tools import tool
import chromadb
from chromadb.config import Settings

from shared.config.settings import settings as app_settings

logger = logging.getLogger(__name__)

# ChromaDB 클라이언트 (싱글톤)
_chroma_client: chromadb.ClientAPI | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    """
    ChromaDB HTTP 클라이언트 가져오기 (싱글톤)
    
    마이크로서비스 환경에서는 원격 ChromaDB 서버에 접속합니다.
    """
    global _chroma_client

    if _chroma_client is None:
        logger.info(f"🔧 ChromaDB HTTP 클라이언트 생성: {app_settings.CHROMADB_HOST}:{app_settings.CHROMADB_PORT}")
        _chroma_client = chromadb.HttpClient(
            host=app_settings.CHROMADB_HOST,
            port=app_settings.CHROMADB_PORT
        )

    return _chroma_client


@tool
async def search_code(
    query: str,
    collection_name: str,
    n_results: int = 5,
) -> list[dict[str, Any]]:
    """
    ChromaDB에서 코드 검색

    Args:
        query: 검색 쿼리 (자연어 또는 코드 스니펫)
        collection_name: ChromaDB 컬렉션 이름 (예: "code_{task_uuid}")
        n_results: 반환할 결과 수

    Returns:
        검색 결과 리스트 [{"file": str, "code": str, "score": float}, ...]

    Example:
        >>> results = await search_code(
        ...     query="authentication function",
        ...     collection_name="code_abc123",
        ...     n_results=3
        ... )
        >>> print(results[0]["file"])
        "src/auth/login.py"
    """
    try:
        client = get_chroma_client()
        collection = client.get_collection(name=collection_name)

        results = collection.query(
            query_texts=[query],
            n_results=n_results,
        )

        # 결과 포맷팅
        formatted_results = []
        for doc, metadata, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            formatted_results.append(
                {
                    "file": metadata.get("file_path", "unknown"),
                    "code": doc,
                    "score": 1.0 - distance,  # 거리 → 유사도 변환
                    "language": metadata.get("language", "unknown"),
                    "lines": metadata.get("lines", "unknown"),
                }
            )

        logger.info(f"🔍 ChromaDB 검색: '{query}' - {len(formatted_results)}개 결과")
        return formatted_results

    except Exception as e:
        logger.error(f"❌ ChromaDB 검색 실패: {e}")
        return []


@tool
async def find_similar_code(
    code_snippet: str,
    collection_name: str,
    n_results: int = 3,
) -> list[dict[str, Any]]:
    """
    유사한 코드 패턴 찾기

    Args:
        code_snippet: 비교할 코드 스니펫
        collection_name: ChromaDB 컬렉션 이름
        n_results: 반환할 결과 수

    Returns:
        유사 코드 리스트

    Example:
        >>> similar = await find_similar_code(
        ...     code_snippet="def login(username, password):\n    ...",
        ...     collection_name="code_abc123"
        ... )
    """
    # search_code와 동일한 로직 사용
    return await search_code(
        query=code_snippet,
        collection_name=collection_name,
        n_results=n_results,
    )


@tool
async def get_code_context(
    user: str,
    skill: str,
    collection_name: str,
    n_results: int = 5,
) -> list[dict[str, Any]]:
    """
    특정 유저의 특정 스킬 관련 코드 컨텍스트 가져오기

    Args:
        user: 유저 이메일
        skill: 스킬 이름 (예: "React", "Django", "PostgreSQL")
        collection_name: ChromaDB 컬렉션 이름
        n_results: 반환할 결과 수

    Returns:
        관련 코드 컨텍스트 리스트

    Example:
        >>> context = await get_code_context(
        ...     user="user@example.com",
        ...     skill="React",
        ...     collection_name="code_abc123"
        ... )
    """
    try:
        client = get_chroma_client()
        collection = client.get_collection(name=collection_name)

        # 메타데이터 필터링 + 쿼리
        results = collection.query(
            query_texts=[skill],
            n_results=n_results,
            where={"user": user} if user else None,  # user 필터
        )

        formatted_results = []
        for doc, metadata, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            formatted_results.append(
                {
                    "file": metadata.get("file_path", "unknown"),
                    "code": doc,
                    "score": 1.0 - distance,
                    "skill": skill,
                    "user": metadata.get("user", "unknown"),
                }
            )

        logger.info(f"🔍 코드 컨텍스트: user={user}, skill={skill} - {len(formatted_results)}개")
        return formatted_results

    except Exception as e:
        logger.error(f"❌ 코드 컨텍스트 가져오기 실패: {e}")
        return []


@tool
async def query_embeddings(
    query: str,
    collection_name: str,
    filter_metadata: dict[str, Any] | None = None,
    n_results: int = 10,
) -> list[dict[str, Any]]:
    """
    고급 벡터 검색 (메타데이터 필터링 포함)

    Args:
        query: 검색 쿼리
        collection_name: ChromaDB 컬렉션 이름
        filter_metadata: 메타데이터 필터 (예: {"language": "python", "user": "user@example.com"})
        n_results: 반환할 결과 수

    Returns:
        필터링된 검색 결과

    Example:
        >>> results = await query_embeddings(
        ...     query="database connection",
        ...     collection_name="code_abc123",
        ...     filter_metadata={"language": "python"}
        ... )
    """
    try:
        client = get_chroma_client()
        collection = client.get_collection(name=collection_name)

        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=filter_metadata,
        )

        formatted_results = []
        for doc, metadata, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            formatted_results.append(
                {
                    "file": metadata.get("file_path", "unknown"),
                    "code": doc,
                    "score": 1.0 - distance,
                    "metadata": metadata,
                }
            )

        logger.info(f"🔍 고급 검색: '{query}' (필터: {filter_metadata}) - {len(formatted_results)}개")
        return formatted_results

    except Exception as e:
        logger.error(f"❌ 고급 검색 실패: {e}")
        return []
