"""
Repository Utility Functions

Git repository 관련 유틸리티 함수들
"""

import re
from urllib.parse import urlparse


def generate_repo_id(git_url: str) -> str:
    """
    Git URL에서 Repository ID 생성

    Repository Isolation을 위해 사용되는 고유 식별자를 생성합니다.
    Neo4j 노드 라벨로 사용되므로 안전한 문자만 포함합니다.

    Args:
        git_url: Git repository URL
            - HTTPS: "https://github.com/user/repo"
            - SSH: "git@github.com:user/repo.git"
            - Local: "/path/to/repo"

    Returns:
        Repository ID (형식: "platform_owner_repo")
        예시: "github_anthropics_claude"

    Examples:
        >>> generate_repo_id("https://github.com/user/repo")
        'github_user_repo'
        >>> generate_repo_id("git@github.com:user/repo.git")
        'github_user_repo'
        >>> generate_repo_id("https://gitlab.com/group/project")
        'gitlab_group_project'
        >>> generate_repo_id("/Users/user/local-repo")
        'local_local_repo'
    """
    # SSH 형식 처리: git@github.com:user/repo.git
    ssh_pattern = r"git@([^:]+):(.+)"
    ssh_match = re.match(ssh_pattern, git_url)

    if ssh_match:
        platform = ssh_match.group(1)
        path = ssh_match.group(2)
    else:
        # HTTPS 또는 로컬 경로 처리
        parsed = urlparse(git_url)

        if parsed.scheme in ("http", "https"):
            # HTTPS URL
            platform = parsed.netloc
            path = parsed.path
        else:
            # 로컬 경로
            platform = "local"
            path = git_url

    # 플랫폼 이름 정리 (github.com → github)
    platform = platform.split(".")[0]

    # 경로에서 .git 제거 및 슬래시로 분리
    path = path.rstrip("/").replace(".git", "")
    path_parts = [p for p in path.split("/") if p]

    # 마지막 2개 부분 추출 (owner/repo 또는 group/project)
    if len(path_parts) >= 2:
        owner = path_parts[-2]
        repo = path_parts[-1]
    elif len(path_parts) == 1:
        owner = "unknown"
        repo = path_parts[0]
    else:
        owner = "unknown"
        repo = "unknown"

    # Neo4j 라벨에 안전한 문자로 변환
    def sanitize(s: str) -> str:
        """특수문자를 언더스코어로 변환"""
        return re.sub(r"[^a-zA-Z0-9]", "_", s).lower()

    platform_clean = sanitize(platform)
    owner_clean = sanitize(owner)
    repo_clean = sanitize(repo)

    return f"{platform_clean}_{owner_clean}_{repo_clean}"


def extract_repo_name(git_url: str) -> str:
    """
    Git URL에서 repository 이름만 추출

    Args:
        git_url: Git repository URL

    Returns:
        Repository name (예: "repo", "project")

    Examples:
        >>> extract_repo_name("https://github.com/user/my-repo")
        'my-repo'
        >>> extract_repo_name("git@gitlab.com:group/project.git")
        'project'
    """
    # SSH 형식
    ssh_pattern = r"git@[^:]+:(.+)"
    ssh_match = re.match(ssh_pattern, git_url)

    if ssh_match:
        path = ssh_match.group(1)
    else:
        # HTTPS 또는 로컬 경로
        parsed = urlparse(git_url)
        path = parsed.path if parsed.scheme else git_url

    # 경로에서 .git 제거 및 마지막 부분 추출
    path = path.rstrip("/").replace(".git", "")
    path_parts = [p for p in path.split("/") if p]

    return path_parts[-1] if path_parts else "unknown"


def is_valid_git_url(git_url: str) -> bool:
    """
    Git URL이 유효한지 검증

    Args:
        git_url: 검증할 Git repository URL

    Returns:
        유효하면 True, 아니면 False

    Examples:
        >>> is_valid_git_url("https://github.com/user/repo")
        True
        >>> is_valid_git_url("git@github.com:user/repo.git")
        True
        >>> is_valid_git_url("invalid-url")
        False
    """
    # SSH 형식 체크
    ssh_pattern = r"^git@[^:]+:.+$"
    if re.match(ssh_pattern, git_url):
        return True

    # HTTPS 형식 체크
    parsed = urlparse(git_url)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return True

    # 로컬 경로 체크 (절대 경로 또는 상대 경로)
    if git_url.startswith("/") or git_url.startswith("./") or git_url.startswith("../"):
        return True

    return False
