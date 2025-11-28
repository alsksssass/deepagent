"""
RepoCloner Agent

Git 레포지토리 클론 작업 수행 (Pydantic 스키마 사용)
"""

import logging
import asyncio
from pathlib import Path
from uuid import UUID
import aiohttp
from .schemas import RepoClonerContext, RepoClonerResponse

logger = logging.getLogger(__name__)


class RepoClonerAgent:
    """
    Git 레포지토리를 클론하는 서브에이전트

    Level 1 작업:
    - Git clone 명령 실행
    - 디렉토리 생성 및 권한 관리
    """

    def _convert_ssh_to_https(self, git_url: str) -> str:
        """
        SSH URL을 HTTPS URL로 변환

        Args:
            git_url: Git URL (git@github.com:owner/repo.git 형식)

        Returns:
            HTTPS URL (https://github.com/owner/repo.git 형식)
        """
        if git_url.startswith("git@"):
            # git@github.com:owner/repo.git -> https://github.com/owner/repo.git
            url_part = git_url.replace("git@", "").replace(":", "/", 1)
            if url_part.startswith("github.com"):
                return f"https://{url_part}"
            elif url_part.startswith("gitlab.com"):
                return f"https://{url_part}"
            else:
                # 다른 Git 호스팅 서비스 (예: Bitbucket)
                return f"https://{url_part}"
        return git_url

    def _add_token_to_url(self, git_url: str, token: str) -> str:
        """
        HTTPS URL에 액세스 토큰 추가

        Args:
            git_url: HTTPS URL
            token: Git 액세스 토큰

        Returns:
            토큰이 포함된 URL (https://{token}@github.com/owner/repo.git)
        """
        if git_url.startswith("https://"):
            # https://github.com/owner/repo.git -> https://{token}@github.com/owner/repo.git
            return git_url.replace("https://", f"https://{token}@", 1)
        return git_url

    async def _extract_user_emails_from_git(
        self, repo_path: str, target_user: str
    ) -> set[str]:
        """
        Git 로그에서 target_user와 관련된 모든 이메일 추출 (Fallback)

        Args:
            repo_path: 클론된 Git 레포지토리 경로
            target_user: 타겟 사용자 (GitHub username 또는 이름)

        Returns:
            사용자의 이메일 주소 set (소문자 변환)
        """
        try:
            # Git 로그에서 작성자 정보 추출 (author name + email)
            # 형식: "Name <email@example.com>"
            cmd = f"cd {repo_path} && git log --all --format='%an|%ae' | sort -u"

            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.warning(f"⚠️ Git 로그 조회 실패: {stderr.decode()}")
                return set()

            # 파싱: "Name|email" 형식
            lines = stdout.decode().strip().split("\n")
            user_emails = set()
            target_lower = target_user.lower()

            for line in lines:
                if "|" not in line:
                    continue

                name, email = line.split("|", 1)
                name_lower = name.lower().strip()
                email_lower = email.lower().strip()

                # target_user와 매칭되는 이메일 수집
                # 1. 이름이 정확히 일치
                # 2. 이메일 앞부분이 일치 (user@domain.com → user)
                # 3. 이름이 이메일 앞부분과 일치
                # 4. 부분 문자열 매칭 (대소문자 무시, 유사 이름 처리)
                email_prefix = email_lower.split("@")[0] if "@" in email_lower else ""

                # GitHub noreply 이메일에서 실제 username 추출
                # 예: 128468293+functionpointerxdd@users.noreply.github.com → functionpointerxdd
                github_username = None
                if "users.noreply.github.com" in email_lower and "+" in email_prefix:
                    github_username = email_prefix.split("+")[1]

                if (
                    target_lower == name_lower
                    or target_lower == email_prefix
                    or name_lower == email_prefix
                    or (github_username and target_lower == github_username)
                    or (github_username and github_username in target_lower)
                    or (github_username and target_lower in github_username)
                ):
                    user_emails.add(email_lower)
                    # GitHub noreply 이메일도 추가
                    if name_lower == target_lower or (github_username and target_lower == github_username):
                        user_emails.add(f"{name_lower}@users.noreply.github.com")

            return user_emails

        except Exception as e:
            logger.warning(f"⚠️ Git 로그 이메일 추출 중 오류: {e}")
            return set()

    async def _fetch_github_user_emails(self, github_token: str) -> set[str]:
        """
        GitHub API를 사용하여 인증된 사용자의 이메일 목록 조회

        Args:
            github_token: GitHub Personal Access Token

        Returns:
            사용자의 이메일 주소 set (소문자 변환)
        """
        try:
            headers = {
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"
            }
            
            async with aiohttp.ClientSession() as session:
                # 먼저 사용자 정보 조회 (username 가져오기)
                async with session.get(
                    "https://api.github.com/user",
                    headers=headers
                ) as user_response:
                    if user_response.status != 200:
                        logger.warning(f"⚠️ GitHub API 사용자 조회 실패 (status: {user_response.status})")
                        return set()
                    
                    user_data = await user_response.json()
                    username = user_data.get("login", "").lower()
                    
                # 이메일 목록 조회
                async with session.get(
                    "https://api.github.com/user/emails",
                    headers=headers
                ) as email_response:
                    if email_response.status == 200:
                        emails_data = await email_response.json()
                        # 모든 이메일을 소문자로 변환하여 set으로 수집
                        emails = {email["email"].lower() for email in emails_data}
                        
                        # username도 추가 (커밋에서 username@users.noreply.github.com 형태로 나올 수 있음)
                        if username:
                            emails.add(username)
                            emails.add(f"{username}@users.noreply.github.com")
                        
                        logger.info(f"✅ GitHub API: {len(emails)}개 이메일/식별자 조회 완료")
                        return emails
                    else:
                        error_text = await email_response.text()
                        logger.warning(f"⚠️ GitHub API 이메일 조회 실패 (status: {email_response.status}): {error_text}")
                        # username만이라도 반환
                        return {username, f"{username}@users.noreply.github.com"} if username else set()
        except Exception as e:
            logger.warning(f"⚠️ GitHub API 이메일 조회 중 오류: {e}")
            return set()

    async def run(self, context: RepoClonerContext) -> RepoClonerResponse:
        """
        레포지토리 클론 실행 (Pydantic 스키마 사용)

        Args:
            context: RepoClonerContext (검증된 입력)

        Returns:
            RepoClonerResponse (타입 안전 출력)
        """
        git_url = context.git_url
        base_path = Path(context.base_path)
        target_user = context.target_user
        user_id = context.user_id
        db_writer = context.db_writer

        # 레포지토리 이름 추출
        repo_name = git_url.split("/")[-1].replace(".git", "")
        repo_path = base_path / "repo" / repo_name

        logger.info(f"🌱 RepoCloner: 클론 시작 - {git_url}")
        if target_user:
            logger.info(f"🎯 타겟 사용자: {target_user} (Git 로그 이메일 추출 예정)")

        try:
            # 디렉토리 생성
            repo_path.parent.mkdir(parents=True, exist_ok=True)

            # 이미 존재하는 경우 삭제 (재실행 시)
            if repo_path.exists():
                logger.warning(f"⚠️  기존 레포지토리 존재, 삭제 후 재클론: {repo_path}")
                import shutil
                shutil.rmtree(repo_path)

            # 액세스 토큰 조회 (user_id와 db_writer가 있는 경우)
            access_token = None
            user_emails = set()
            
            if user_id and db_writer:
                try:
                    logger.info(f"🔍 액세스 토큰 조회 시도: user_id={user_id}")
                    user_uuid = UUID(user_id)
                    access_token = await db_writer.get_user_access_token(user_uuid)
                    if access_token:
                        masked_token = f"{access_token[:4]}...{access_token[-4:]}" if len(access_token) > 8 else "***"
                        logger.info(f"🔑 액세스 토큰 조회 성공 (사용자: {user_id}, 토큰: {masked_token})")
                        
                        # GitHub 사용자 이메일 목록 조회 (GitHub URL인 경우만)
                        if "github.com" in git_url.lower():
                            user_emails = await self._fetch_github_user_emails(access_token)
                            if user_emails:
                                logger.info(f"📧 GitHub 사용자 이메일/식별자 조회 완료: {len(user_emails)}개")
                    else:
                        logger.warning(f"⚠️  액세스 토큰 조회 결과 없음 (None 반환) - 사용자: {user_id}")
                        logger.info(f"ℹ️  액세스 토큰 없음 (사용자: {user_id}), 퍼블릭 레포로 시도")
                except Exception as e:
                    logger.error(f"❌ 액세스 토큰 조회 중 예외 발생: {e}")
                    logger.warning(f"⚠️  액세스 토큰 조회 실패: {e}, 원래 URL로 시도")

            # URL 변환 및 토큰 추가
            clone_url = git_url
            
            # SSH URL인 경우 HTTPS로 변환
            if git_url.startswith("git@"):
                clone_url = self._convert_ssh_to_https(git_url)
                logger.info(f"🔄 SSH URL을 HTTPS로 변환: {git_url} -> {clone_url}")

            # 토큰이 있으면 URL에 포함
            if access_token:
                clone_url = self._add_token_to_url(clone_url, access_token)
                # 로그에는 토큰을 마스킹하여 출력
                masked_url = clone_url.replace(access_token, "***", 1)
                logger.info(f"🔐 토큰 포함 URL로 클론: {masked_url}")
            else:
                logger.info(f"🌐 토큰 없이 클론 시도 (퍼블릭 레포 가능): {clone_url}")

            # Git clone 실행 (재시도 로직 포함)
            max_retries = 3
            retry_delay = 5  # 초
            
            for attempt in range(1, max_retries + 1):
                try:
                    # 첫 시도 전에 네트워크 연결 테스트
                    if attempt == 1:
                        logger.info("🔍 네트워크 연결 테스트 중...")
                        test_process = await asyncio.create_subprocess_shell(
                            f"timeout 10 curl -I https://github.com 2>&1 | head -3 || echo 'Connection test failed'",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        test_stdout, _ = await test_process.communicate()
                        logger.info(f"📡 연결 테스트 결과: {test_stdout.decode()[:100]}")
                    
                    # Git 설정: 타임아웃 증가 및 연결 최적화
                    git_config_cmd = (
                        "git config --global http.postBuffer 524288000 && "
                        "git config --global http.lowSpeedLimit 0 && "
                        "git config --global http.lowSpeedTime 0 && "
                        "git config --global http.timeout 300"
                    )
                    
                    # Git clone 명령 (타임아웃 설정 포함)
                    clone_cmd = f"timeout 600 git clone {clone_url} {repo_path}"
                    cmd = f"{git_config_cmd} && {clone_cmd}"
                    
                    logger.info(f"🔄 클론 시도 {attempt}/{max_retries}: {clone_url}")
                    
                    process = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await process.communicate()

                    if process.returncode == 0:
                        logger.info(f"✅ RepoCloner: 클론 완료 - {repo_path}")

                        # Fallback: GitHub API 실패 시 Git 로그에서 target_user 이메일 추출
                        if not user_emails and target_user:
                            logger.info(f"🔍 Fallback: Git 로그에서 {target_user} 이메일 추출 시도")
                            user_emails = await self._extract_user_emails_from_git(
                                str(repo_path), target_user
                            )
                            if user_emails:
                                logger.info(
                                    f"✅ Git 로그에서 {len(user_emails)}개 이메일 추출 완료"
                                )

                        return RepoClonerResponse(
                            status="success",
                            repo_path=str(repo_path),
                            repo_name=repo_name,
                            user_emails=list(user_emails) if user_emails else None,
                            error=None,
                        )
                    else:
                        error_msg = stderr.decode() if stderr else stdout.decode()
                        logger.warning(f"⚠️  클론 시도 {attempt}/{max_retries} 실패: {error_msg[:200]}")
                        
                        # 마지막 시도가 아니면 재시도
                        if attempt < max_retries:
                            logger.info(f"⏳ {retry_delay}초 후 재시도...")
                            await asyncio.sleep(retry_delay)
                            # 실패한 디렉토리 정리
                            if repo_path.exists():
                                import shutil
                                shutil.rmtree(repo_path, ignore_errors=True)
                        else:
                            # 모든 시도 실패
                            logger.error(f"❌ RepoCloner: 클론 실패 (모든 시도 실패) - {error_msg}")
                            return RepoClonerResponse(
                                status="failed",
                                repo_path=None,
                                repo_name=repo_name,
                                error=error_msg,
                            )
                            
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️  클론 시도 {attempt}/{max_retries} 타임아웃")
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay)
                        if repo_path.exists():
                            import shutil
                            shutil.rmtree(repo_path, ignore_errors=True)
                    else:
                        return RepoClonerResponse(
                            status="failed",
                            repo_path=None,
                            repo_name=repo_name,
                            error="Git clone timeout after all retries",
                        )

        except Exception as e:
            logger.error(f"❌ RepoCloner: 예외 발생 - {e}")
            return RepoClonerResponse(
                status="failed",
                repo_path=None,
                repo_name=repo_name,
                error=str(e),
            )
