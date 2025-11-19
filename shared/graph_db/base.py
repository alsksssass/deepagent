"""
Graph Database Backend 추상화 레이어

Neo4j와 Neptune을 투명하게 전환할 수 있는 추상 인터페이스
"""

from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional


class GraphDBBackend(ABC):
    """
    Graph Database Backend 추상 인터페이스

    구현체:
    - Neo4jBackend: Neo4j (개발 환경) - Cypher 쿼리
    - NeptuneBackend: AWS Neptune (프로덕션 환경) - Gremlin 쿼리

    Repository Isolation:
    - 모든 노드에 자동으로 `Repo_{repo_id}` 라벨 추가
    - 쿼리 시 repo_id로 필터링하여 다른 repository 데이터와 격리
    """

    @abstractmethod
    async def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        repo_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        그래프 쿼리 실행

        Args:
            query: 쿼리 문자열 (Neo4j: Cypher, Neptune: Gremlin)
            params: 쿼리 파라미터
            repo_id: Repository ID (isolation 용)

        Returns:
            쿼리 결과 리스트
        """
        pass

    @abstractmethod
    async def create_node(
        self,
        labels: List[str],
        properties: Dict[str, Any],
        repo_id: str
    ) -> Dict[str, Any]:
        """
        노드 생성 (Repository isolation 자동 적용)

        Args:
            labels: 노드 라벨 리스트 (예: ["User", "Contributor"])
            properties: 노드 속성
            repo_id: Repository ID

        Returns:
            생성된 노드 정보
        """
        pass

    @abstractmethod
    async def create_relationship(
        self,
        from_node_id: str,
        to_node_id: str,
        rel_type: str,
        properties: Optional[Dict[str, Any]] = None,
        repo_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        관계 생성

        Args:
            from_node_id: 시작 노드 ID
            to_node_id: 종료 노드 ID
            rel_type: 관계 타입 (예: "COMMITTED", "MODIFIED")
            properties: 관계 속성
            repo_id: Repository ID

        Returns:
            생성된 관계 정보
        """
        pass

    @abstractmethod
    async def get_user_commits(
        self,
        user_email: str,
        repo_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        특정 유저의 커밋 리스트 조회

        Args:
            user_email: 유저 이메일 또는 이름
            repo_id: Repository ID (None이면 전체)
            limit: 최대 커밋 수

        Returns:
            커밋 리스트
        """
        pass

    @abstractmethod
    async def get_commit_details(
        self,
        commit_hash: str,
        repo_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        특정 커밋의 상세 정보 조회

        Args:
            commit_hash: 커밋 해시
            repo_id: Repository ID

        Returns:
            커밋 상세 정보
        """
        pass

    @abstractmethod
    async def get_file_history(
        self,
        file_path: str,
        user_email: Optional[str] = None,
        repo_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        특정 파일의 수정 이력 조회

        Args:
            file_path: 파일 경로
            user_email: 유저 이메일 (None이면 전체 유저)
            repo_id: Repository ID
            limit: 최대 커밋 수

        Returns:
            커밋 리스트
        """
        pass

    @abstractmethod
    async def get_user_stats(
        self,
        user_email: str,
        repo_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        유저 통계 조회

        Args:
            user_email: 유저 이메일
            repo_id: Repository ID

        Returns:
            통계 정보
        """
        pass

    @abstractmethod
    async def close(self):
        """
        데이터베이스 연결 종료
        """
        pass

    def get_repo_label(self, repo_id: str) -> str:
        """
        Repository 라벨 생성 (공통 헬퍼)

        Args:
            repo_id: Repository ID

        Returns:
            Repository 라벨 (예: "Repo_abc123def456")
        """
        # 하이픈을 언더스코어로 변경 (Neo4j 라벨 규칙)
        safe_repo_id = repo_id.replace("-", "_").replace(".", "_")
        return f"Repo_{safe_repo_id}"
