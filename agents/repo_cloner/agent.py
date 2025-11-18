"""
RepoCloner Agent

Git 레포지토리 클론 작업 수행 (Pydantic 스키마 사용)
"""

import logging
import asyncio
from pathlib import Path
from .schemas import RepoClonerContext, RepoClonerResponse

logger = logging.getLogger(__name__)


class RepoClonerAgent:
    """
    Git 레포지토리를 클론하는 서브에이전트

    Level 1 작업:
    - Git clone 명령 실행
    - 디렉토리 생성 및 권한 관리
    """

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

        # 레포지토리 이름 추출
        repo_name = git_url.split("/")[-1].replace(".git", "")
        repo_path = base_path / "repo" / repo_name

        logger.info(f"🌱 RepoCloner: 클론 시작 - {git_url}")

        try:
            # 디렉토리 생성
            repo_path.parent.mkdir(parents=True, exist_ok=True)

            # 이미 존재하는 경우 삭제 (재실행 시)
            if repo_path.exists():
                logger.warning(f"⚠️  기존 레포지토리 존재, 삭제 후 재클론: {repo_path}")
                import shutil
                shutil.rmtree(repo_path)

            # Git clone 실행
            cmd = f"git clone {git_url} {repo_path}"
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info(f"✅ RepoCloner: 클론 완료 - {repo_path}")
                return RepoClonerResponse(
                    status="success",
                    repo_path=str(repo_path),
                    repo_name=repo_name,
                    error=None,
                )
            else:
                error_msg = stderr.decode()
                logger.error(f"❌ RepoCloner: 클론 실패 - {error_msg}")
                return RepoClonerResponse(
                    status="failed",
                    repo_path=None,
                    repo_name=repo_name,
                    error=error_msg,
                )

        except Exception as e:
            logger.error(f"❌ RepoCloner: 예외 발생 - {e}")
            return RepoClonerResponse(
                status="failed",
                repo_path=None,
                repo_name=repo_name,
                error=str(e),
            )
