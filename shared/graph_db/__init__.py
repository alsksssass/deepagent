"""
Graph Database utilities for Deep Agents

그래프 데이터베이스 추상화 레이어 (Neo4j 전용)
Neptune은 비용 문제로 제외, EC2 Docker Neo4j 사용
"""

from shared.config import settings
from .base import GraphDBBackend
from .neo4j_backend import Neo4jBackend


def create_graph_db_backend() -> GraphDBBackend:
    """
    GraphDBBackend 인스턴스 생성 (Neo4j 전용)

    Returns:
        Neo4jBackend 인스턴스

    Note:
        Neptune은 비용 문제로 제외되었습니다.
        로컬 개발: bolt://localhost:7687
        AWS EC2: bolt://ec2-xxx.compute.amazonaws.com:7687

    Example:
        >>> graph_db = create_graph_db_backend()
        >>> isinstance(graph_db, Neo4jBackend)
        True
    """
    return Neo4jBackend()


__all__ = [
    "GraphDBBackend",
    "Neo4jBackend",
    "create_graph_db_backend",
]
