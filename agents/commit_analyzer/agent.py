"""
CommitAnalyzer Agent

Git 커밋을 분석하고 Neo4j에 적재 (Pydantic 스키마 사용, MERGE로 멱등성 보장)
"""

import logging
import asyncio
from pathlib import Path
from typing import Any, Optional

from pydriller import Repository
from neo4j import AsyncGraphDatabase

from .schemas import CommitAnalyzerContext, CommitAnalyzerResponse

logger = logging.getLogger(__name__)


class CommitAnalyzerAgent:
    """
    Git 커밋을 분석하고 Neo4j에 적재하는 서브에이전트

    Level 2 병렬 처리:
    - 커밋 마이닝 (PyDriller)
    - Neo4j 적재 (배치 단위, MERGE 사용)
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
        self.driver = None

    async def run(self, context: CommitAnalyzerContext) -> CommitAnalyzerResponse:
        """
        커밋 분석 및 Neo4j 적재 실행 (Pydantic 스키마 사용)

        Args:
            context: CommitAnalyzerContext (검증된 입력)

        Returns:
            CommitAnalyzerResponse (타입 안전 출력)
        """
        repo_path = context.repo_path
        target_user = context.target_user

        logger.info(f"📊 CommitAnalyzer: {repo_path} 분석 시작")

        try:
            # Neo4j 드라이버 초기화
            self.driver = AsyncGraphDatabase.driver(
                context.neo4j_uri,
                auth=(context.neo4j_user, context.neo4j_password),
            )

            # Neo4j 초기화 (인덱스, 제약조건)
            await self._init_neo4j()

            # Level 2-1: PyDriller로 커밋 마이닝
            commits_data = await self._mine_commits(repo_path, target_user)

            # Level 2-2: Neo4j에 배치 적재 (MERGE 사용)
            stats = await self._load_to_neo4j(commits_data)

            logger.info(
                f"✅ CommitAnalyzer: {stats['total_commits']}개 커밋, "
                f"{stats['total_users']}명 유저 적재 완료"
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
            if self.driver:
                await self.driver.close()

    async def _init_neo4j(self):
        """
        Neo4j 인덱스 및 제약조건 생성
        """
        async with self.driver.session() as session:
            # User 노드 제약조건
            await session.run(
                "CREATE CONSTRAINT user_email IF NOT EXISTS "
                "FOR (u:User) REQUIRE u.email IS UNIQUE"
            )

            # Commit 노드 제약조건
            await session.run(
                "CREATE CONSTRAINT commit_hash IF NOT EXISTS "
                "FOR (c:Commit) REQUIRE c.hash IS UNIQUE"
            )

            # File 노드 제약조건
            await session.run(
                "CREATE CONSTRAINT file_path IF NOT EXISTS "
                "FOR (f:File) REQUIRE f.path IS UNIQUE"
            )

            logger.info("✅ Neo4j 인덱스 및 제약조건 생성 완료")

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

                commit_data = {
                    "hash": commit.hash,
                    "message": commit.msg,
                    "author_name": commit.author.name,
                    "author_email": commit.author.email,
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

    async def _load_to_neo4j(self, commits_data: list[dict[str, Any]]) -> dict[str, int]:
        """
        커밋 데이터를 Neo4j에 배치 적재 (MERGE 사용하여 멱등성 보장)

        Args:
            commits_data: 커밋 데이터 리스트

        Returns:
            {"total_commits": int, "total_users": int, "total_files": int}
        """
        async with self.driver.session() as session:
            # 배치 크기
            batch_size = 100
            total_commits = 0
            users_set = set()
            files_set = set()

            for i in range(0, len(commits_data), batch_size):
                batch = commits_data[i : i + batch_size]

                # 배치 처리 쿼리 (MERGE 사용)
                query = """
                UNWIND $commits AS commit

                // User 노드 생성/병합
                MERGE (u:User {email: commit.author_email})
                ON CREATE SET
                    u.name = commit.author_name

                // Commit 노드 생성/병합 (멱등성 보장)
                MERGE (c:Commit {hash: commit.hash})
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

                MERGE (f:File {path: mod.new_path})
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

                await session.run(query, commits=batch)

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
