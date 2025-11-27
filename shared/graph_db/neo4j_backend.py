"""
Neo4jBackend - Neo4j 기반 그래프 데이터베이스

로컬 개발 환경에서 Neo4j를 사용하는 구현체
"""

import logging
from typing import Any, List, Dict, Optional

from neo4j import AsyncGraphDatabase, AsyncDriver

from shared.graph_db.base import GraphDBBackend
from shared.config import settings

logger = logging.getLogger(__name__)


class Neo4jBackend(GraphDBBackend):
    """
    Neo4j 기반 그래프 데이터베이스 백엔드

    특징:
    - Cypher 쿼리 언어 사용
    - Repository isolation: 모든 노드에 Repo_{repo_id} 라벨 자동 추가
    - Async 드라이버 사용
    """

    def __init__(self):
        """Neo4jBackend 초기화"""
        self.uri = settings.NEO4J_URI
        self.user = settings.NEO4J_USER
        self.password = settings.NEO4J_PASSWORD

        self.driver: AsyncDriver = AsyncGraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password)
        )

        logger.debug(f"📦 Neo4jBackend 초기화: {self.uri}")

    async def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        repo_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Cypher 쿼리 실행"""
        try:
            async with self.driver.session() as session:
                result = await session.run(query, **(params or {}))
                records = await result.data()

            logger.debug(f"🔍 Neo4j: {len(records)}개 결과")
            return records

        except Exception as e:
            logger.error(f"❌ Neo4j 쿼리 실행 실패: {e}")
            return []

    async def create_node(
        self,
        labels: List[str],
        properties: Dict[str, Any],
        repo_id: str
    ) -> Dict[str, Any]:
        """노드 생성 with Repository isolation"""
        try:
            # Repository 라벨 자동 추가
            repo_label = self.get_repo_label(repo_id)
            all_labels = [repo_label] + labels

            # Cypher 라벨 문자열 생성
            label_str = ":".join(all_labels)

            # Repository ID를 속성으로도 추가
            props_with_repo = {**properties, "repo_id": repo_id}

            query = f"""
            CREATE (n:{label_str})
            SET n = $properties
            RETURN n, labels(n) AS labels
            """

            async with self.driver.session() as session:
                result = await session.run(query, properties=props_with_repo)
                record = await result.single()

                if record:
                    node_data = dict(record["n"])
                    node_data["labels"] = record["labels"]  # 라벨 정보 추가
                    logger.info(f"✅ Neo4j: 노드 생성 - {labels} (repo: {repo_id})")
                    return node_data
                return {}

        except Exception as e:
            logger.error(f"❌ Neo4j 노드 생성 실패: {e}")
            return {}

    async def create_relationship(
        self,
        from_node_id: str,
        to_node_id: str,
        rel_type: str,
        properties: Optional[Dict[str, Any]] = None,
        repo_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """관계 생성"""
        try:
            query = """
            MATCH (from), (to)
            WHERE id(from) = $from_id AND id(to) = $to_id
            CREATE (from)-[r:%s]->(to)
            SET r = $properties
            RETURN r
            """ % rel_type

            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    from_id=from_node_id,
                    to_id=to_node_id,
                    properties=properties or {}
                )
                record = await result.single()

                if record:
                    logger.info(f"✅ Neo4j: 관계 생성 - {rel_type}")
                    return dict(record["r"])
                return {}

        except Exception as e:
            logger.error(f"❌ Neo4j 관계 생성 실패: {e}")
            return {}

    async def get_user_commits(
        self,
        user_email: str,
        repo_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """특정 유저의 커밋 리스트 조회"""
        try:
            # 이메일 형식 확인
            is_email = "@" in user_email

            # Repository isolation: 제약조건이 복합 키이므로 repo_id 필수
            if not repo_id:
                logger.warning("⚠️  repo_id가 없으면 커밋 조회 불가 (복합 키 제약조건)")
                return []

            if is_email:
                query = f"""
                MATCH (u:User {{email: $user_identifier, repo_id: $repo_id}})-[:COMMITTED]->(c:Commit)
                WHERE c.repo_id = $repo_id
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
                query = f"""
                MATCH (u:User)
                WHERE toLower(u.name) = toLower($user_identifier) AND u.repo_id = $repo_id
                MATCH (u)-[:COMMITTED]->(c:Commit)
                WHERE c.repo_id = $repo_id
                RETURN c.hash AS hash,
                       c.message AS message,
                       c.author_date AS date,
                       c.lines_added AS lines_added,
                       c.lines_deleted AS lines_deleted,
                       c.files_changed AS files_changed
                ORDER BY c.author_date DESC
                LIMIT $limit
                """

            # 제약조건이 복합 키이므로 repo_id 필수
            params = {"user_identifier": user_email, "repo_id": repo_id, "limit": limit}
            records = await self.execute_query(
                query,
                params
            )

            logger.info(f"🔍 Neo4j: user={user_email} - {len(records)}개 커밋")
            return records

        except Exception as e:
            logger.error(f"❌ Neo4j 커밋 조회 실패: {e}")
            return []

    async def get_all_commits(
        self,
        repo_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        특정 repository의 모든 커밋 조회 (User 필터링 없음)
        
        CommitAnalyzer에서 이미 target_user로 필터링해서 저장했으므로,
        조회 시에는 해당 repo_id의 모든 커밋을 반환
        
        Args:
            repo_id: Repository ID (필수)
            limit: 최대 조회 개수 (기본값 100)
            
        Returns:
            커밋 리스트
        """
        try:
            if not repo_id:
                logger.warning("⚠️  repo_id가 없으면 커밋 조회 불가 (복합 키 제약조건)")
                return []

            query = f"""
            MATCH (c:Commit {{repo_id: $repo_id}})
            RETURN c.hash AS hash,
                   c.message AS message,
                   c.author_date AS date,
                   c.lines_added AS lines_added,
                   c.lines_deleted AS lines_deleted,
                   c.files_changed AS files_changed
            ORDER BY c.author_date DESC
            LIMIT $limit
            """

            records = await self.execute_query(
                query,
                {"repo_id": repo_id, "limit": limit}
            )

            logger.info(f"🔍 Neo4j: repo_id={repo_id} - {len(records)}개 커밋 조회")
            return records

        except Exception as e:
            logger.error(f"❌ Neo4j 전체 커밋 조회 실패: {e}")
            return []

    async def get_commit_details(
        self,
        commit_hash: str,
        repo_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """특정 커밋의 상세 정보 조회"""
        try:
            # 제약조건이 복합 키이므로 repo_id 속성으로 필터링
            query = f"""
            MATCH (c:Commit {{hash: $commit_hash, repo_id: $repo_id}})-[:MODIFIED]->(f:File)
            WHERE f.repo_id = $repo_id
            RETURN c.hash AS hash,
                   c.message AS message,
                   c.author_date AS date,
                   c.lines_added AS lines_added,
                   c.lines_deleted AS lines_deleted,
                   collect({{
                       path: f.path,
                       added: f.added_lines,
                       deleted: f.deleted_lines,
                       old_path: f.old_path,
                       new_path: f.new_path,
                       change_type: f.change_type
                   }}) AS files
            """

            params = {"commit_hash": commit_hash}
            if repo_id:
                params["repo_id"] = repo_id
            else:
                # repo_id가 없으면 빈 결과 반환 (제약조건이 복합 키이므로 필수)
                logger.warning("⚠️  repo_id가 없으면 커밋 조회 불가 (복합 키 제약조건)")
                return {}

            async with self.driver.session() as session:
                result = await session.run(query, **params)
                record = await result.single()

                if record:
                    details = dict(record)
                    logger.info(f"🔍 Neo4j: commit={commit_hash} - {len(details.get('files', []))}개 파일")
                    return details
                else:
                    # 결과 없음은 정상적인 경우일 수 있으므로 DEBUG 레벨로 변경
                    logger.debug(f"⚠️  Neo4j: commit={commit_hash} - 결과 없음 (repo_id: {repo_id})")
                    return {}

        except Exception as e:
            logger.error(f"❌ Neo4j 커밋 상세 조회 실패: {e}")
            return {}

    async def get_file_history(
        self,
        file_path: str,
        user_email: Optional[str] = None,
        repo_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """특정 파일의 수정 이력 조회"""
        try:
            # 제약조건이 복합 키이므로 repo_id 속성으로 필터링
            if not repo_id:
                logger.warning("⚠️  repo_id가 없으면 파일 이력 조회 불가 (복합 키 제약조건)")
                return []

            query = f"""
            MATCH (c:Commit)-[:MODIFIED]->(f:File {{path: $file_path, repo_id: $repo_id}})
            WHERE c.repo_id = $repo_id AND f.repo_id = $repo_id
            AND ($user_email IS NULL OR EXISTS {{
                MATCH (u:User {{email: $user_email, repo_id: $repo_id}})-[:COMMITTED]->(c)
            }})
            RETURN c.hash AS hash,
                   c.message AS message,
                   c.author_date AS date,
                   f.added_lines AS added_lines,
                   f.deleted_lines AS deleted_lines
            ORDER BY c.author_date DESC
            LIMIT $limit
            """

            records = await self.execute_query(
                query,
                {"file_path": file_path, "user_email": user_email, "repo_id": repo_id, "limit": limit}
            )

            logger.info(f"🔍 Neo4j: file={file_path} - {len(records)}개 커밋")
            return records

        except Exception as e:
            logger.error(f"❌ Neo4j 파일 이력 조회 실패: {e}")
            return []

    async def get_user_stats(
        self,
        user_email: str,
        repo_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """유저 통계 조회"""
        try:
            # 제약조건이 복합 키이므로 repo_id 속성으로 필터링
            if not repo_id:
                logger.warning("⚠️  repo_id가 없으면 유저 통계 조회 불가 (복합 키 제약조건)")
                return {}

            query = f"""
            MATCH (u:User {{email: $user_email, repo_id: $repo_id}})-[:COMMITTED]->(c:Commit)
            WHERE c.repo_id = $repo_id
            WITH u, c
            MATCH (c)-[:MODIFIED]->(f:File)
            WHERE f.repo_id = $repo_id
            RETURN count(DISTINCT c) AS total_commits,
                   sum(c.lines_added) AS total_lines_added,
                   sum(c.lines_deleted) AS total_lines_deleted,
                   count(DISTINCT f) AS total_files_modified
            """

            async with self.driver.session() as session:
                result = await session.run(query, user_email=user_email, repo_id=repo_id)
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

    async def close(self):
        """Neo4j 드라이버 연결 종료"""
        if self.driver:
            await self.driver.close()
            logger.debug("🔌 Neo4j 연결 종료")
