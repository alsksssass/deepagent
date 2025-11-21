"""
ChromaDB Tools for Deep Agents

서브에이전트가 사용할 수 있는 ChromaDB 접근 도구

저장소 분리 정책:
- 스킬차트: 원격 ChromaDB (공유 데이터, 다중 서비스 접근)
- 코드 RAG: 로컬 ChromaDB (대용량, task별 독립, 빠른 접근)
"""

import logging
from pathlib import Path
from typing import Any
from langchain_core.tools import tool
import chromadb
from chromadb.config import Settings

from shared.config.settings import settings as app_settings

logger = logging.getLogger(__name__)

# ============================================================
# 클라이언트 관리 (스킬: 원격, 코드: 로컬)
# ============================================================

# 스킬차트용 원격 클라이언트 (싱글톤)
_skill_chroma_client: chromadb.ClientAPI | None = None

# 코드 RAG용 로컬 클라이언트 캐시 (task_uuid별)
_code_chroma_clients: dict[str, chromadb.ClientAPI] = {}


def get_skill_chroma_client() -> chromadb.ClientAPI:
    """
    스킬차트용 원격 ChromaDB 클라이언트 (싱글톤)

    공유 데이터로 원격 서버에 저장됩니다.
    """
    global _skill_chroma_client

    if _skill_chroma_client is None:
        logger.info(f"🔧 스킬차트 ChromaDB (원격): {app_settings.CHROMADB_HOST}:{app_settings.CHROMADB_PORT}")
        _skill_chroma_client = chromadb.HttpClient(
            host=app_settings.CHROMADB_HOST,
            port=app_settings.CHROMADB_PORT
        )

    return _skill_chroma_client


def get_code_chroma_client(task_uuid: str, base_dir: str | None = None) -> chromadb.ClientAPI:
    """
    코드 RAG용 로컬 ChromaDB 클라이언트

    task_uuid별로 독립된 로컬 저장소를 사용합니다.

    Args:
        task_uuid: 태스크 고유 ID
        base_dir: 기본 저장 디렉토리

    Returns:
        PersistentClient for local storage
    """
    global _code_chroma_clients

    if task_uuid not in _code_chroma_clients:
        # 기본 경로: 프로젝트 루트의 data/chroma_db
        if base_dir is None:
            base_dir = Path(__file__).parent.parent.parent / "data" / "chroma_db"
        else:
            base_dir = Path(base_dir)

        persist_dir = base_dir / task_uuid
        persist_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"🔧 코드 RAG ChromaDB (로컬): {persist_dir}")
        _code_chroma_clients[task_uuid] = chromadb.PersistentClient(
            path=str(persist_dir)
        )

    return _code_chroma_clients[task_uuid]


def get_chroma_client(persist_dir: str | None = None) -> chromadb.ClientAPI:
    """
    하위 호환성을 위한 범용 클라이언트 getter

    - persist_dir 제공: 로컬 PersistentClient (기존 동작 유지)
    - persist_dir 미제공: 원격 HttpClient (스킬차트용)

    Args:
        persist_dir: 로컬 저장 경로 (None이면 원격 사용)
    """
    return get_skill_chroma_client()


@tool
async def search_code(
    query: str,
    collection_name: str,
    n_results: int = 5,
) -> list[dict[str, Any]]:
    """
    ChromaDB에서 코드 검색 (로컬 저장소 사용)

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
        # collection_name에서 task_uuid 추출 (code_{task_uuid} 형식)
        task_uuid = collection_name.replace("code_", "") if collection_name.startswith("code_") else collection_name

        # 로컬 클라이언트 사용
        client = get_code_chroma_client(task_uuid)
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
                    "file": metadata.get("file_path", metadata.get("file", "unknown")),
                    "code": doc,
                    "score": 1.0 - distance,  # 거리 → 유사도 변환
                    "language": metadata.get("language", "unknown"),
                    "lines": metadata.get("lines", "unknown"),
                }
            )

        logger.info(f"🔍 코드 검색 (로컬): '{query[:30]}...' - {len(formatted_results)}개 결과")
        return formatted_results

    except Exception as e:
        logger.error(f"❌ 코드 검색 실패: {e}")
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
    특정 유저의 특정 스킬 관련 코드 컨텍스트 가져오기 (로컬 저장소)

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
        # collection_name에서 task_uuid 추출
        task_uuid = collection_name.replace("code_", "") if collection_name.startswith("code_") else collection_name

        # 로컬 클라이언트 사용
        client = get_code_chroma_client(task_uuid)
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
                    "file": metadata.get("file_path", metadata.get("file", "unknown")),
                    "code": doc,
                    "score": 1.0 - distance,
                    "skill": skill,
                    "user": metadata.get("user", "unknown"),
                }
            )

        logger.info(f"🔍 코드 컨텍스트 (로컬): user={user}, skill={skill} - {len(formatted_results)}개")
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
    고급 벡터 검색 (메타데이터 필터링 포함, 로컬 저장소)

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
        # collection_name에서 task_uuid 추출
        task_uuid = collection_name.replace("code_", "") if collection_name.startswith("code_") else collection_name

        # 로컬 클라이언트 사용
        client = get_code_chroma_client(task_uuid)
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
                    "file": metadata.get("file_path", metadata.get("file", "unknown")),
                    "code": doc,
                    "score": 1.0 - distance,
                    "metadata": metadata,
                }
            )

        logger.info(f"🔍 고급 검색 (로컬): '{query[:30]}...' (필터: {filter_metadata}) - {len(formatted_results)}개")
        return formatted_results

    except Exception as e:
        logger.error(f"❌ 고급 검색 실패: {e}")
        return []
