"""
Skill Tools for Deep Agents

서브에이전트가 사용할 수 있는 Skill Charts 접근 도구
"""

import logging
import os
from collections import defaultdict
from typing import Any
from langchain_core.tools import tool
import chromadb
from chromadb.config import Settings
from shared.config import settings

logger = logging.getLogger(__name__)

# ChromaDB 클라이언트 (싱글톤 - persist_dir별로 관리)
_skill_chroma_clients: dict[str, chromadb.ClientAPI] = {}


def get_skill_chroma_client(persist_dir: str) -> chromadb.ClientAPI:
    """
    Skill Charts용 ChromaDB 클라이언트 가져오기 (싱글톤)
    
    ⚠️ 스킬 시스템은 무조건 원격 호스트 사용 (CHROMADB_HOST 필수)
    persist_dir 파라미터는 무시됨 (원격 서버 사용 시 불필요)
    """
    global _skill_chroma_clients

    # 원격 서버 설정 가져오기
    chromadb_host = os.getenv("CHROMADB_HOST", settings.CHROMADB_HOST)
    chromadb_port = int(os.getenv("CHROMADB_PORT", str(settings.CHROMADB_PORT)))
    chromadb_auth_token = os.getenv("CHROMADB_AUTH_TOKEN", settings.CHROMADB_AUTH_TOKEN)
    
    # 원격 서버 정보 검증
    if not chromadb_host or chromadb_host == "localhost":
        raise ValueError(
            "스킬 시스템은 원격 ChromaDB 서버를 사용해야 합니다. "
            "CHROMADB_HOST 환경변수를 설정해주세요. (예: CHROMADB_HOST=13.125.186.57)"
        )
    
    # host:port를 키로 사용 (persist_dir 무시)
    client_key = f"{chromadb_host}:{chromadb_port}"
    
    if client_key not in _skill_chroma_clients:
        # 원격 ChromaDB 서버 사용 (무조건)
        logger.info(f"🔧 Skill ChromaDB 원격 클라이언트 생성: {chromadb_host}:{chromadb_port}")
        client_settings = chromadb.Settings(
            chroma_api_impl="rest",
            chroma_server_host=chromadb_host,
            chroma_server_http_port=chromadb_port,
        )
        if chromadb_auth_token:
            client_settings.chroma_client_auth_provider = "chromadb.auth.token.TokenAuthClientProvider"
            client_settings.chroma_client_auth_credentials = chromadb_auth_token
        
        _skill_chroma_clients[client_key] = chromadb.HttpClient(
            host=chromadb_host,
            port=chromadb_port,
            settings=client_settings,
        )
    
    return _skill_chroma_clients[client_key]


@tool
async def search_skills_by_code(
    code_snippet: str,
    n_results: int = 10,
    persist_dir: str = "./data/chroma_db",
) -> list[dict[str, Any]]:
    """
    코드 스니펫에서 관련 스킬 검색

    Args:
        code_snippet: 분석할 코드 스니펫
        n_results: 반환할 스킬 수
        persist_dir: ChromaDB 저장 디렉토리

    Returns:
        관련 스킬 리스트 [{"skill_name": str, "level": str, "category": str, ...}, ...]

    Example:
        >>> skills = await search_skills_by_code(
        ...     code_snippet="async def fetch_data():\n    async with aiohttp..."
        ... )
        >>> print(skills[0]["skill_name"])
        "비동기 프로그래밍"
    """
    try:
        client = get_skill_chroma_client(persist_dir)
        collection = client.get_collection(name="skill_charts")

        results = collection.query(
            query_texts=[code_snippet],
            n_results=n_results,
        )

        # 결과 포맷팅
        formatted_skills = []
        for metadata, distance in zip(
            results["metadatas"][0],
            results["distances"][0],
        ):
            formatted_skills.append({
                "skill_name": metadata["skill_name"],
                "level": metadata["level"],
                "category": metadata["category"],
                "subcategory": metadata["subcategory"],
                "base_score": metadata["base_score"],
                "weighted_score": metadata["weighted_score"],
                "relevance_score": 1.0 - distance,  # 유사도
            })

        logger.info(f"🔍 코드 → 스킬 매칭: {len(formatted_skills)}개 스킬 발견")
        return formatted_skills

    except Exception as e:
        logger.error(f"❌ 스킬 검색 실패: {e}")
        return []


@tool
async def get_skill_by_name(
    skill_name: str,
    level: str | None = None,
    persist_dir: str = "./data/chroma_db",
) -> list[dict[str, Any]]:
    """
    스킬 이름으로 스킬 정보 조회

    Args:
        skill_name: 스킬 이름 (예: "데코레이터 사용", "Django ORM")
        level: 레벨 필터 (Basic, Intermediate, Advanced)
        persist_dir: ChromaDB 저장 디렉토리

    Returns:
        스킬 정보 리스트

    Example:
        >>> skills = await get_skill_by_name(
        ...     skill_name="데코레이터 사용",
        ...     level="Advanced"
        ... )
    """
    try:
        client = get_skill_chroma_client(persist_dir)
        collection = client.get_collection(name="skill_charts")

        # 메타데이터 필터링
        where_filter = {"skill_name": skill_name}
        if level:
            where_filter["level"] = level

        results = collection.get(
            where=where_filter,
            include=["metadatas"],
        )

        formatted_skills = []
        for metadata in results["metadatas"]:
            formatted_skills.append({
                "skill_name": metadata["skill_name"],
                "level": metadata["level"],
                "category": metadata["category"],
                "subcategory": metadata["subcategory"],
                "base_score": metadata["base_score"],
                "weighted_score": metadata["weighted_score"],
            })

        logger.info(f"🔍 스킬 조회: '{skill_name}' - {len(formatted_skills)}개 결과")
        return formatted_skills

    except Exception as e:
        logger.error(f"❌ 스킬 조회 실패: {e}")
        return []


@tool
async def get_skills_by_category(
    category: str,
    level: str | None = None,
    persist_dir: str = "./data/chroma_db",
) -> list[dict[str, Any]]:
    """
    카테고리별 스킬 목록 조회

    Args:
        category: 카테고리 (예: "기본 문법 및 제어 구조", "데이터베이스")
        level: 레벨 필터 (Basic, Intermediate, Advanced)
        persist_dir: ChromaDB 저장 디렉토리

    Returns:
        스킬 리스트

    Example:
        >>> skills = await get_skills_by_category(
        ...     category="객체지향 프로그래밍 (OOP)",
        ...     level="Advanced"
        ... )
    """
    try:
        client = get_skill_chroma_client(persist_dir)
        collection = client.get_collection(name="skill_charts")

        where_filter = {"category": category}
        if level:
            where_filter["level"] = level

        results = collection.get(
            where=where_filter,
            include=["metadatas"],
        )

        formatted_skills = []
        for metadata in results["metadatas"]:
            formatted_skills.append({
                "skill_name": metadata["skill_name"],
                "level": metadata["level"],
                "category": metadata["category"],
                "subcategory": metadata["subcategory"],
                "base_score": metadata["base_score"],
                "weighted_score": metadata["weighted_score"],
            })

        logger.info(f"🔍 카테고리 '{category}': {len(formatted_skills)}개 스킬")
        return formatted_skills

    except Exception as e:
        logger.error(f"❌ 카테고리 조회 실패: {e}")
        return []


@tool
async def get_all_categories(
    persist_dir: str = "./data/chroma_db",
) -> list[str]:
    """
    모든 스킬 카테고리 목록 조회

    Args:
        persist_dir: ChromaDB 저장 디렉토리

    Returns:
        카테고리 리스트

    Example:
        >>> categories = await get_all_categories()
        >>> print(categories)
        ["기본 문법 및 제어 구조", "객체지향 프로그래밍 (OOP)", ...]
    """
    try:
        client = get_skill_chroma_client(persist_dir)
        collection = client.get_collection(name="skill_charts")

        # 전체 메타데이터 가져오기
        results = collection.get(include=["metadatas"])

        # 카테고리 중복 제거
        categories = list(set([meta["category"] for meta in results["metadatas"]]))
        categories.sort()

        logger.info(f"📋 전체 카테고리: {len(categories)}개")
        return categories

    except Exception as e:
        logger.error(f"❌ 카테고리 목록 조회 실패: {e}")
        return []


@tool
async def calculate_category_coverage(
    user_skills: list[dict[str, Any]],
    persist_dir: str = "./data/chroma_db",
) -> dict[str, Any]:
    """
    사용자의 카테고리별 스킬 커버리지 계산

    Args:
        user_skills: 사용자가 보유한 스킬 리스트 [{"skill_name": str, "level": str, "category": str}, ...]
        persist_dir: ChromaDB 저장 디렉토리

    Returns:
        카테고리별 커버리지 {
            "total_coverage": float,
            "category_coverage": {"카테고리명": {"count": int, "total": int, "percentage": float}, ...}
        }

    Example:
        >>> coverage = await calculate_category_coverage(user_skills=[...])
        >>> print(coverage["category_coverage"]["데이터베이스"]["percentage"])
        40.5
    """
    try:
        client = get_skill_chroma_client(persist_dir)
        collection = client.get_collection(name="skill_charts")

        # 전체 스킬 가져오기
        all_skills = collection.get(include=["metadatas"])

        # 카테고리별 전체 스킬 수 계산
        category_total = {}
        for meta in all_skills["metadatas"]:
            cat = meta["category"]
            category_total[cat] = category_total.get(cat, 0) + 1

        # 사용자 스킬 카테고리별 분류 (중복 제거)
        # 같은 스킬(skill_name + level)이 여러 번 나타날 수 있으므로 중복 제거 필요
        user_category_skills = defaultdict(set)  # 카테고리별 고유 스킬 집합
        all_unique_skills = set()  # 전체 고유 스킬 집합 (전체 커버리지 계산용)
        
        for skill in user_skills:
            cat = skill["category"]
            # skill_name과 level의 조합으로 고유성 판단
            skill_key = f"{skill.get('skill_name', '')}_{skill.get('level', '')}"
            user_category_skills[cat].add(skill_key)
            all_unique_skills.add(skill_key)
        
        # 카테고리별 고유 스킬 수 계산
        user_category_count = {
            cat: len(skills_set) for cat, skills_set in user_category_skills.items()
        }

        # 카테고리별 커버리지 계산
        category_coverage = {}
        total_user_skills = len(all_unique_skills)  # 중복 제거된 고유 스킬 수
        total_all_skills = len(all_skills["metadatas"])

        for cat, total in category_total.items():
            count = user_category_count.get(cat, 0)
            percentage = (count / total) * 100 if total > 0 else 0.0

            category_coverage[cat] = {
                "count": count,
                "total": total,
                "percentage": round(percentage, 1),
            }

        # 전체 커버리지
        total_coverage = (
            (total_user_skills / total_all_skills) * 100
            if total_all_skills > 0
            else 0.0
        )

        logger.info(f"📊 커버리지 계산 완료: {total_coverage:.1f}% ({total_user_skills}/{total_all_skills})")

        return {
            "total_coverage": round(total_coverage, 1),
            "category_coverage": category_coverage,
        }

    except Exception as e:
        logger.error(f"❌ 커버리지 계산 실패: {e}")
        return {"total_coverage": 0.0, "category_coverage": {}}
