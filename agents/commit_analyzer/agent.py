"""
CommitAnalyzer Agent

Git 커밋을 분석하고 Neo4j에 적재 (Pydantic 스키마 사용, MERGE로 멱등성 보장)
Repository Isolation 지원: 각 Git repository 데이터를 격리하여 저장
"""

import logging
import asyncio
from pathlib import Path
from typing import Any, Optional

from pydriller import Repository

from shared.graph_db import GraphDBBackend, Neo4jBackend
from .schemas import CommitAnalyzerContext, CommitAnalyzerResponse
from .author_mapper import AuthorMapper

logger = logging.getLogger(__name__)


class CommitAnalyzerAgent:
    """
    Git 커밋을 분석하고 Neo4j에 적재하는 서브에이전트

    Level 2 병렬 처리:
    - 커밋 마이닝 (PyDriller)
    - Neo4j 적재 (배치 단위, MERGE 사용)

    Repository Isolation:
    - 각 노드에 Repo_{repo_id} 라벨 자동 추가
    - 쿼리 시 repo_id로 필터링하여 다른 repository 데이터와 격리
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
    ):
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.backend: Optional[GraphDBBackend] = None
        self.author_mapper: Optional[AuthorMapper] = None

    async def run(self, context: CommitAnalyzerContext) -> CommitAnalyzerResponse:
        """
        커밋 분석 및 Neo4j 적재 실행 (Pydantic 스키마 사용)
        Repository Isolation 적용: repo_id로 데이터 격리

        Args:
            context: CommitAnalyzerContext (검증된 입력, git_url 포함)

        Returns:
            CommitAnalyzerResponse (타입 안전 출력)
        """
        repo_path = context.repo_path
        target_user = context.target_user
        repo_id = context.repo_id  # Repository Isolation용 ID

        logger.info(f"📊 CommitAnalyzer: {repo_path} 분석 시작 (repo_id: {repo_id})")

        try:
            # GraphDBBackend 초기화 (Neo4j)
            self.backend = Neo4jBackend()

            # AuthorMapper 초기화 (매핑 규칙이 있는 경우)
            if context.author_mapping_rules:
                mapping_dict = context.author_mapping_rules.to_dict()
                self.author_mapper = AuthorMapper(mapping_dict)
                stats = self.author_mapper.get_mapping_stats()
                logger.info(
                    f"✅ AuthorMapper enabled: {stats['total_developers']} developers, "
                    f"{stats['total_aliases']} aliases"
                )
            else:
                self.author_mapper = None
                logger.info("ℹ️ AuthorMapper disabled: No mapping rules provided")

            # Neo4j 초기화 (인덱스, 제약조건) - Repository별로 격리
            await self._init_neo4j(repo_id)

            # Level 2-1: PyDriller로 커밋 마이닝
            commits_data = await self._mine_commits(repo_path, target_user)

            # Level 2-2: Neo4j에 배치 적재 (MERGE 사용, Repository Isolation 적용)
            stats = await self._load_to_neo4j(commits_data, repo_id)

            logger.info(
                f"✅ CommitAnalyzer: {stats['total_commits']}개 커밋, "
                f"{stats['total_users']}명 유저 적재 완료 (repo_id: {repo_id})"
            )

            return CommitAnalyzerResponse(
                status="success",
                total_commits=stats["total_commits"],
                total_users=stats["total_users"],
                total_files=stats["total_files"],
                error=None,
            )

        except Exception as e:
            logger.error(f"❌ CommitAnalyzer: {e}")
            return CommitAnalyzerResponse(
                status="failed",
                total_commits=0,
                total_users=0,
                total_files=0,
                error=str(e),
            )

        finally:
            if self.backend:
                await self.backend.close()

    async def _init_neo4j(self, repo_id: str):
        """
        Neo4j 인덱스 및 제약조건 생성 (Repository Isolation 적용)

        Args:
            repo_id: Repository ID (예: github_user_repo)
        """
        # Repository 라벨 생성
        repo_label = self.backend.get_repo_label(repo_id)

        # 제약조건 생성 쿼리 (Repository별로 격리)
        # Neo4j 5.x에서는 여러 라벨을 직접 사용할 수 없으므로,
        # 단일 라벨 + 복합 키(repo_id 속성 포함)로 제약조건 생성
        safe_repo_id = repo_id.replace('-', '_').replace('.', '_')
        constraints = [
            # User 노드: (email, repo_id) 복합 키로 repository별 uniqueness 보장
            f"CREATE CONSTRAINT user_email_{safe_repo_id} IF NOT EXISTS "
            f"FOR (u:User) REQUIRE (u.email, u.repo_id) IS UNIQUE",

            # Commit 노드: (hash, repo_id) 복합 키로 repository별 uniqueness 보장
            f"CREATE CONSTRAINT commit_hash_{safe_repo_id} IF NOT EXISTS "
            f"FOR (c:Commit) REQUIRE (c.hash, c.repo_id) IS UNIQUE",

            # File 노드: (path, repo_id) 복합 키로 repository별 uniqueness 보장
            f"CREATE CONSTRAINT file_path_{safe_repo_id} IF NOT EXISTS "
            f"FOR (f:File) REQUIRE (f.path, f.repo_id) IS UNIQUE",
        ]

        for constraint_query in constraints:
            try:
                await self.backend.execute_query(constraint_query, repo_id=repo_id)
            except Exception as e:
                # 제약조건이 이미 존재하는 경우 무시
                if "already exists" not in str(e).lower():
                    logger.warning(f"⚠️ 제약조건 생성 실패: {e}")

        logger.info(f"✅ Neo4j 인덱스 및 제약조건 생성 완료 (repo_id: {repo_id})")

    async def _mine_commits(
        self, repo_path: str, target_user: Optional[str]
    ) -> list[dict[str, Any]]:
        """
        PyDriller로 커밋 마이닝

        Args:
            repo_path: Git 레포지토리 경로
            target_user: 특정 유저 이메일 (None이면 전체)

        Returns:
            list of commit data dictionaries
        """
        commits_data = []

        # PyDriller는 동기 API이므로 executor에서 실행
        def _mine():
            repo = Repository(repo_path)

            for commit in repo.traverse_commits():
                # 특정 유저 필터링 (이메일 또는 이름으로 비교, 대소문자 무시)
                if target_user:
                    target_lower = target_user.lower()
                    author_email_lower = commit.author.email.lower() if commit.author.email else ""
                    author_name_lower = commit.author.name.lower() if commit.author.name else ""
                    
                    # 이메일 또는 이름 중 하나라도 일치하면 포함
                    if (target_lower != author_email_lower and 
                        target_lower != author_name_lower):
                        continue

                # 저자 정보 정규화 (AuthorMapper 사용)
                original_author_name = commit.author.name
                original_author_email = commit.author.email

                if self.author_mapper:
                    normalized_name, normalized_email = self.author_mapper.normalize_author(
                        original_author_name, original_author_email
                    )
                else:
                    normalized_name = original_author_name
                    normalized_email = original_author_email

                commit_data = {
                    "hash": commit.hash,
                    "message": commit.msg,
                    "author_name": normalized_name,  # 정규화된 이름
                    "author_email": normalized_email,  # 정규화된 이메일
                    "original_author_name": original_author_name,  # 원본 이름 (참고용)
                    "original_author_email": original_author_email,  # 원본 이메일 (참고용)
                    "author_date": commit.author_date.isoformat(),
                    "committer_name": commit.committer.name,
                    "committer_email": commit.committer.email,
                    "committer_date": commit.committer_date.isoformat(),
                    "lines_added": commit.insertions,
                    "lines_deleted": commit.deletions,
                    "files_changed": commit.files,
                    "modifications": [],
                }

                # 파일 수정 내역
                for modification in commit.modified_files:
                    # NULL 경로 필터링 (삭제된 파일 등)
                    file_path = modification.new_path or modification.old_path

                    if file_path is None:
                        logger.warning(
                            f"⚠️ Commit {commit.hash[:7]}: 파일 경로가 None인 수정사항 스킵 "
                            f"(change_type: {modification.change_type.name})"
                        )
                        continue

                    commit_data["modifications"].append({
                        "filename": modification.filename,
                        "old_path": modification.old_path,
                        "new_path": file_path,  # NULL 대신 유효한 경로 사용
                        "change_type": modification.change_type.name,
                        "added_lines": modification.added_lines,
                        "deleted_lines": modification.deleted_lines,
                        "complexity": modification.complexity if modification.complexity else 0,
                    })

                commits_data.append(commit_data)

            return commits_data

        # 동기 함수를 비동기로 실행
        loop = asyncio.get_event_loop()
        commits_data = await loop.run_in_executor(None, _mine)

        logger.info(f"📊 PyDriller: {len(commits_data)}개 커밋 마이닝 완료")
        return commits_data

    async def _load_to_neo4j(
        self, commits_data: list[dict[str, Any]], repo_id: str
    ) -> dict[str, int]:
        """
        커밋 데이터를 Neo4j에 배치 적재 (MERGE 사용하여 멱등성 보장)
        Repository Isolation 적용: repo_id로 데이터 격리

        Args:
            commits_data: 커밋 데이터 리스트
            repo_id: Repository ID (예: github_user_repo)

        Returns:
            {"total_commits": int, "total_users": int, "total_files": int}
        """
        # Repository 라벨 생성
        repo_label = self.backend.get_repo_label(repo_id)

        # 배치 크기
        batch_size = 100
        total_commits = 0
        users_set = set()
        files_set = set()

        for i in range(0, len(commits_data), batch_size):
            batch = commits_data[i : i + batch_size]

            # 배치 처리 쿼리 (MERGE 사용, Repository Isolation 적용)
            # 제약조건이 복합 키이므로 MERGE도 복합 키로 매칭하되, 라벨은 여전히 추가
            query = f"""
            UNWIND $commits AS commit

            // User 노드 생성/병합 (복합 키: email + repo_id, Repository 라벨 포함)
            MERGE (u:{repo_label}:User {{email: commit.author_email, repo_id: $repo_id}})
            ON CREATE SET
                u.name = commit.author_name
            ON MATCH SET
                u.name = commit.author_name  // 정규화된 이름으로 업데이트

            // Commit 노드 생성/병합 (복합 키: hash + repo_id, Repository 라벨 포함, 멱등성 보장)
            MERGE (c:{repo_label}:Commit {{hash: commit.hash, repo_id: $repo_id}})
            ON CREATE SET
                c.message = commit.message,
                c.author_date = datetime(commit.author_date),
                c.committer_date = datetime(commit.committer_date),
                c.lines_added = commit.lines_added,
                c.lines_deleted = commit.lines_deleted,
                c.files_changed = commit.files_changed
            ON MATCH SET
                c.message = commit.message,
                c.author_date = datetime(commit.author_date),
                c.committer_date = datetime(commit.committer_date),
                c.lines_added = commit.lines_added,
                c.lines_deleted = commit.lines_deleted,
                c.files_changed = commit.files_changed

            // User-Commit 관계 생성/병합
            MERGE (u)-[:COMMITTED]->(c)

            // File 노드 및 관계
            WITH c, commit
            UNWIND commit.modifications AS mod

            // File 노드 생성/병합 (복합 키: path + repo_id, Repository 라벨 포함)
            MERGE (f:{repo_label}:File {{path: mod.new_path, repo_id: $repo_id}})
            ON CREATE SET
                f.filename = mod.filename,
                f.old_path = mod.old_path,
                f.new_path = mod.new_path

            // Commit-File 관계 생성/병합 (멱등성 보장)
            MERGE (c)-[r:MODIFIED]->(f)
            ON CREATE SET
                r.change_type = mod.change_type,
                r.added_lines = mod.added_lines,
                r.deleted_lines = mod.deleted_lines,
                r.complexity = mod.complexity
            ON MATCH SET
                r.change_type = mod.change_type,
                r.added_lines = mod.added_lines,
                r.deleted_lines = mod.deleted_lines,
                r.complexity = mod.complexity
            """

            await self.backend.execute_query(
                query, params={"commits": batch, "repo_id": repo_id}, repo_id=repo_id
            )

            total_commits += len(batch)

            # 통계 수집
            for commit in batch:
                users_set.add(commit["author_email"])
                for mod in commit["modifications"]:
                    files_set.add(mod["new_path"])

            logger.info(f"📊 Neo4j: {total_commits}/{len(commits_data)} 커밋 적재 중...")

        return {
            "total_commits": total_commits,
            "total_users": len(users_set),
            "total_files": len(files_set),
        }
