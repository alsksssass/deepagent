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
        user_emails = set(context.user_emails) if context.user_emails else set()

        logger.info(f"📊 CommitAnalyzer: {repo_path} 분석 시작 (repo_id: {repo_id})")

        # 디버깅: 입력 파라미터 상세 로그
        logger.info(f"🔍 Input parameters:")
        logger.info(f"   - target_user: {target_user}")
        logger.info(f"   - user_emails ({len(user_emails)}): {sorted(user_emails) if user_emails else 'None'}")
        logger.info(f"   - author_mapping_rules: {'Enabled' if context.author_mapping_rules else 'Disabled'}")

        if user_emails:
            logger.info(f"📧 사용자 식별자 {len(user_emails)}개 사용 (강화된 사용자 판단)")

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

                # 디버깅: 각 매핑 규칙 상세 로그
                for canonical_name, rule in mapping_dict.items():
                    logger.debug(f"  📋 Mapping rule: {canonical_name} (canonical_email: {rule['canonical_email']})")
                    logger.debug(f"     ← {len(rule.get('aliases', []))} aliases")
                    for alias in rule.get('aliases', []):
                        alias_name = alias.get('name', 'N/A')
                        alias_email = alias['email']
                        logger.debug(f"       - {alias_name} <{alias_email}>")
            else:
                self.author_mapper = None
                logger.info("ℹ️ AuthorMapper disabled: No mapping rules provided")

            # Neo4j 초기화 (인덱스, 제약조건) - Repository별로 격리
            await self._init_neo4j(repo_id)

            # Level 2-1: PyDriller로 커밋 마이닝 (강화된 사용자 판단)
            commits_data = await self._mine_commits(repo_path, target_user, user_emails)

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

    def _extract_username_from_email(self, email: str) -> str:
        """
        이메일 앞부분(username) 추출
        """
        prefix = email.split("@")[0] if "@" in email else email
        return prefix.split("+")[1] if "+" in prefix else prefix

    def _is_target_user(
        self, commit, target_user: str, user_emails: set[str]
    ) -> bool:
        """
        강화된 사용자 판단 로직

        Args:
            commit: PyDriller commit 객체
            target_user: 타겟 사용자 (이메일 또는 이름)
            user_emails: GitHub API로 조회한 사용자 이메일/식별자 목록 (소문자)

        Returns:
            target_user의 커밋이면 True
        """
        author_email = commit.author.email.lower() if commit.author.email else ""
        author_name = commit.author.name.lower() if commit.author.name else ""
        author_name_from_email = self._extract_username_from_email(commit.author.email) if commit.author.email else ""

        target_lower = target_user.lower()
        lower_target_emails = {email.lower() for email in user_emails}
        target_names_from_email = {self._extract_username_from_email(email) for email in lower_target_emails}

        # 1. 정확한 이메일/이름 매칭
        if target_lower == author_email or target_lower == author_name:
            logger.debug(
                f"✅ Match (exact): {commit.author.name} <{commit.author.email}> "
                f"matches target_user={target_user}"
            )
            return True

        # 2. GitHub API로 조회한 이메일 목록에 있는지 확인
        if author_email in lower_target_emails:
            logger.debug(
                f"✅ Match (user_emails): {commit.author.name} <{commit.author.email}> "
                f"found in user_emails"
            )
            return True

        # 3. 유저의 이메일 앞부분(username)과 작성자 이름 비교
        if author_name in target_names_from_email:
            logger.debug(
                f"✅ Match (username): {commit.author.name} <{commit.author.email}> "
                f"matches target username"
            )
            return True

        # 4. 유저의 이메일 앞부분(username)과 작성자 이메일 앞부분 비교
        if author_name_from_email in target_names_from_email:
            logger.debug(
                f"✅ Match (email prefix): {commit.author.name} <{commit.author.email}> "
                f"matches target email prefix"
            )
            return True

        # 매칭 실패 로그 (디버깅용)
        logger.debug(
            f"❌ No match: {commit.author.name} <{commit.author.email}> "
            f"vs target_user={target_user}, user_emails={user_emails}"
        )
        return False

    async def _mine_commits(
        self, repo_path: str, target_user: Optional[str], user_emails: set[str] = None
    ) -> list[dict[str, Any]]:
        """
        PyDriller로 커밋 마이닝 (강화된 사용자 판단 로직)

        Args:
            repo_path: Git 레포지토리 경로
            target_user: 특정 유저 이메일 또는 이름 (None이면 전체)
            user_emails: GitHub API로 조회한 사용자 이메일/식별자 목록 (소문자)

        Returns:
            list of commit data dictionaries
        """
        commits_data = []
        if user_emails is None:
            user_emails = set()

        # PyDriller는 동기 API이므로 executor에서 실행
        def _mine():
            repo = Repository(repo_path)
            author_mapping_log = {}  # 디버깅: 원본 → 정규화 매핑 추적

            for commit in repo.traverse_commits():
                # 특정 유저 필터링 (강화된 로직)
                if target_user:
                    if not self._is_target_user(commit, target_user, user_emails):
                        continue

                # 저자 정보 정규화 (AuthorMapper 사용)
                original_author_name = commit.author.name
                original_author_email = commit.author.email

                if self.author_mapper:
                    normalized_name, normalized_email = self.author_mapper.normalize_author(
                        original_author_name, original_author_email
                    )

                    # 디버깅: 매핑이 발생한 경우 로그 기록
                    if (normalized_name, normalized_email) != (original_author_name, original_author_email):
                        original_key = (original_author_name, original_author_email)
                        normalized_key = (normalized_name, normalized_email)

                        if original_key not in author_mapping_log:
                            author_mapping_log[original_key] = normalized_key
                            logger.debug(
                                f"🔄 Author mapped: {original_author_name} <{original_author_email}> "
                                f"→ {normalized_name} <{normalized_email}>"
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

        # 디버깅: 작성자 통계 집계
        if self.author_mapper:
            original_authors = set()
            normalized_authors = set()

            for commit in commits_data:
                original_authors.add((commit['original_author_name'], commit['original_author_email']))
                normalized_authors.add((commit['author_name'], commit['author_email']))

            logger.info(
                f"📊 Author consolidation: {len(original_authors)} original IDs → {len(normalized_authors)} normalized developers"
            )

            # 정규화된 개발자별 커밋 수 집계
            normalized_commit_counts = {}
            for commit in commits_data:
                key = (commit['author_name'], commit['author_email'])
                normalized_commit_counts[key] = normalized_commit_counts.get(key, 0) + 1

            logger.info(f"📊 Normalized developers ({len(normalized_commit_counts)}):")
            for (name, email), count in sorted(normalized_commit_counts.items(), key=lambda x: x[1], reverse=True):
                logger.info(f"   - {name} <{email}>: {count} commits")
        else:
            # AuthorMapper 비활성화 상태에서도 작성자 통계 출력
            author_commit_counts = {}
            for commit in commits_data:
                key = (commit['author_name'], commit['author_email'])
                author_commit_counts[key] = author_commit_counts.get(key, 0) + 1

            logger.info(f"📊 Authors ({len(author_commit_counts)}):")
            for (name, email), count in sorted(author_commit_counts.items(), key=lambda x: x[1], reverse=True):
                logger.info(f"   - {name} <{email}>: {count} commits")

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
