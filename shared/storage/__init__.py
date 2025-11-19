"""
Storage utilities for Deep Agents

에이전트 결과 저장 및 관리를 위한 스토리지 유틸리티
"""

from pathlib import Path

from shared.config import settings
from .result_store import ResultStore
from .base import StorageBackend
from .local_store import LocalStorageBackend
from .s3_store import S3StorageBackend


def create_storage_backend(task_uuid: str, base_path: str | Path = None) -> StorageBackend:
    """
    설정에 따라 적절한 StorageBackend 인스턴스 생성

    Args:
        task_uuid: 작업 고유 UUID
        base_path: 기본 경로 (None이면 자동 생성)

    Returns:
        StorageBackend 구현체 (LocalStorageBackend 또는 S3StorageBackend)

    Example:
        # 로컬 환경 (.env에 STORAGE_BACKEND=local)
        >>> storage = create_storage_backend("task-123")
        >>> isinstance(storage, LocalStorageBackend)
        True

        # AWS 환경 (.env에 STORAGE_BACKEND=s3)
        >>> storage = create_storage_backend("task-123")
        >>> isinstance(storage, S3StorageBackend)
        True
    """
    # base_path 자동 생성
    if base_path is None:
        if settings.STORAGE_BACKEND.value == "local":
            base_path = settings.LOCAL_DATA_DIR / "analyze" / task_uuid
        else:  # S3
            base_path = f"analyze/{task_uuid}"

    # Backend 선택
    if settings.STORAGE_BACKEND.value == "s3":
        return S3StorageBackend(task_uuid, str(base_path))
    else:  # local (default)
        return LocalStorageBackend(task_uuid, str(base_path))


__all__ = [
    "ResultStore",
    "StorageBackend",
    "LocalStorageBackend",
    "S3StorageBackend",
    "create_storage_backend",
]

