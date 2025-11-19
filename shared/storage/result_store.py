"""
ResultStore - 에이전트 결과 저장 및 관리

에이전트 실행 결과를 JSON 파일로 저장하고 타입 안전하게 로드하는 스토리지 매니저

환경변수에 따라 자동으로 LocalStorageBackend 또는 S3StorageBackend를 사용합니다.
- STORAGE_BACKEND=local: 로컬 파일시스템
- STORAGE_BACKEND=s3: AWS S3

구조:
    Local: data/analyze/{task_uuid}/
    S3: s3://bucket/analyze/{task_uuid}/
    ├── results/
    │   ├── repo_cloner.json
    │   ├── static_analyzer.json
    │   ├── commit_analyzer.json
    │   ├── commit_evaluator/
    │   │   ├── batch_0001.json
    │   │   ├── batch_0002.json
    │   │   └── summary.json
    │   └── reporter.json
    └── metadata.json
"""

import json
import logging
from pathlib import Path
from typing import Type, TypeVar, Optional, List, Any
from datetime import datetime

from shared.schemas.common import BaseResponse
from shared.storage.base import StorageBackend
from shared.storage.local_store import LocalStorageBackend

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseResponse)


class ResultStore:
    """
    에이전트 결과를 JSON 파일로 저장/로드하는 스토리지 매니저

    특징:
    - 타입 안전한 결과 저장/로드 (Pydantic 기반)
    - 대용량 결과 배치 분할 저장 지원
    - 메모리 효율적인 결과 관리
    - 에이전트별 자동 경로 관리
    - 환경변수에 따라 자동으로 Local/S3 백엔드 선택
    """

    def __init__(self, task_uuid: str, base_path: Path | str):
        """
        ResultStore 초기화

        Args:
            task_uuid: 작업 고유 UUID
            base_path: 작업 기본 경로 (예: Path("./data/analyze/{task_uuid}") 또는 "analyze/{task_uuid}")
        """
        self.task_uuid = task_uuid
        self.base_path = Path(base_path) if isinstance(base_path, Path) else base_path
        
        # 환경변수에 따라 동적으로 StorageBackend 생성 (순환 import 방지를 위해 함수 내부에서 import)
        from shared.storage import create_storage_backend
        self.backend: StorageBackend = create_storage_backend(task_uuid, base_path)
        
        # 호환성을 위한 results_dir 속성 (로컬일 때만 Path 객체)
        if isinstance(self.backend, LocalStorageBackend):
            self.results_dir = self.backend.results_dir
        else:
            # S3의 경우 results 디렉토리 경로 문자열 반환
            # get_batch_dir("")로 results 디렉토리 경로 얻기
            batch_dir = self.backend.get_batch_dir("")
            # s3://bucket/analyze/task_uuid/results/ -> s3://bucket/analyze/task_uuid/results
            self.results_dir = batch_dir.rstrip("/")

        logger.debug(f"📦 ResultStore 초기화: {type(self.backend).__name__} - {self.results_dir}")

    def save_result(
        self,
        agent_name: str,
        result: BaseResponse,
    ) -> Path | str:
        """
        에이전트 결과를 저장

        Args:
            agent_name: 에이전트 이름 (예: "repo_cloner", "static_analyzer")
            result: Pydantic BaseResponse 인스턴스

        Returns:
            저장된 파일 경로 (로컬: Path, S3: s3://bucket/key 문자열)

        Example:
            >>> store = ResultStore("task-123", Path("./data/analyze/task-123"))
            >>> response = RepoClonerResponse(status="success", repo_path="/path/to/repo")
            >>> file_path = store.save_result("repo_cloner", response)
            >>> print(file_path)
            Path("./data/analyze/task-123/results/repo_cloner.json")
        """
        saved_path = self.backend.save_result(agent_name, result)
        
        # 호환성을 위해 Path 객체로 변환 (로컬인 경우)
        if isinstance(self.backend, LocalStorageBackend):
            return Path(saved_path)
        return saved_path

    def load_result(
        self,
        agent_name: str,
        result_class: Type[T],
    ) -> T:
        """
        저장된 에이전트 결과를 타입 안전하게 로드

        Args:
            agent_name: 에이전트 이름
            result_class: Pydantic Response 클래스 (예: RepoClonerResponse)

        Returns:
            로드된 Pydantic Response 인스턴스

        Raises:
            FileNotFoundError: 결과 파일이 존재하지 않을 때
            ValueError: JSON 파싱 또는 Pydantic 검증 실패 시

        Example:
            >>> from agents.repo_cloner import RepoClonerResponse
            >>> store = ResultStore("task-123", Path("./data/analyze/task-123"))
            >>> result = store.load_result("repo_cloner", RepoClonerResponse)
            >>> print(result.repo_path)
            "/path/to/repo"
        """
        return self.backend.load_result(agent_name, result_class)

    def save_batched_result(
        self,
        agent_name: str,
        batch_id: int,
        result: BaseResponse | List[BaseResponse] | dict[str, Any],
    ) -> Path | str:
        """
        대용량 결과를 배치별로 저장 (CommitEvaluator 등)

        Args:
            agent_name: 에이전트 이름 (예: "commit_evaluator")
            batch_id: 배치 번호 (0부터 시작)
            result: 저장할 결과 (Pydantic Response, Response 리스트, 또는 dict)

        Returns:
            저장된 파일 경로 (로컬: Path, S3: s3://bucket/key 문자열)

        Example:
            >>> store = ResultStore("task-123", Path("./data/analyze/task-123"))
            >>> batch_results = [CommitEvaluatorResponse(...) for _ in range(100)]
            >>> file_path = store.save_batched_result("commit_evaluator", 0, batch_results)
            >>> print(file_path)
            Path("./data/analyze/task-123/results/commit_evaluator/batch_0000.json")
        """
        saved_path = self.backend.save_batched_result(agent_name, batch_id, result)
        
        # 호환성을 위해 Path 객체로 변환 (로컬인 경우)
        if isinstance(self.backend, LocalStorageBackend):
            return Path(saved_path)
        return saved_path

    def load_batched_results(
        self,
        agent_name: str,
        result_class: Optional[Type[T]] = None,
    ) -> List[dict[str, Any]] | List[T]:
        """
        배치 결과 전체를 로드

        Args:
            agent_name: 에이전트 이름
            result_class: Pydantic Response 클래스 (지정 시 타입 안전 로드)

        Returns:
            배치 결과 리스트 (result_class 지정 시 Pydantic 인스턴스 리스트, 아니면 dict 리스트)

        Example:
            >>> from agents.commit_evaluator import CommitEvaluatorResponse
            >>> store = ResultStore("task-123", Path("./data/analyze/task-123"))
            >>> batches = store.load_batched_results("commit_evaluator", CommitEvaluatorResponse)
            >>> print(len(batches))
            10
        """
        return self.backend.load_batched_results(agent_name, result_class)

    def get_result_path(self, agent_name: str) -> Path | str:
        """
        에이전트 결과 파일 경로 반환

        Args:
            agent_name: 에이전트 이름

        Returns:
            결과 파일 경로 (로컬: Path, S3: s3://bucket/key 문자열)

        Example:
            >>> store = ResultStore("task-123", Path("./data/analyze/task-123"))
            >>> path = store.get_result_path("static_analyzer")
            >>> if isinstance(path, Path) and path.exists():
            ...     data = json.loads(path.read_text(encoding="utf-8"))
        """
        path_str = self.backend.get_result_path(agent_name)
        if isinstance(self.backend, LocalStorageBackend):
            return Path(path_str)
        return path_str

    def get_batch_dir(self, agent_name: str) -> Path | str:
        """
        배치 결과 디렉토리 경로 반환

        Args:
            agent_name: 에이전트 이름

        Returns:
            배치 디렉토리 경로 (로컬: Path, S3: s3://bucket/key 문자열)
        """
        path_str = self.backend.get_batch_dir(agent_name)
        if isinstance(self.backend, LocalStorageBackend):
            return Path(path_str)
        return path_str

    def list_available_results(self) -> List[str]:
        """
        저장된 에이전트 결과 목록 조회

        Returns:
            에이전트 이름 리스트

        Example:
            >>> store = ResultStore("task-123", Path("./data/analyze/task-123"))
            >>> results = store.list_available_results()
            >>> print(results)
            ["repo_cloner", "static_analyzer", "commit_analyzer"]
        """
        return self.backend.list_available_results()

    def list_batched_agents(self) -> List[str]:
        """
        배치 저장된 에이전트 목록 조회

        Returns:
            배치 저장된 에이전트 이름 리스트

        Example:
            >>> store = ResultStore("task-123", Path("./data/analyze/task-123"))
            >>> batched = store.list_batched_agents()
            >>> print(batched)
            ["commit_evaluator"]
        """
        return self.backend.list_batched_agents()

    def save_metadata(self, metadata: dict[str, Any]) -> Path | str:
        """
        작업 메타데이터 저장

        Args:
            metadata: 메타데이터 dict

        Returns:
            저장된 파일 경로 (로컬: Path, S3: s3://bucket/key 문자열)
        """
        saved_path = self.backend.save_metadata(metadata)
        
        # 호환성을 위해 Path 객체로 변환 (로컬인 경우)
        if isinstance(self.backend, LocalStorageBackend):
            return Path(saved_path)
        return saved_path

    def load_metadata(self) -> dict[str, Any]:
        """
        작업 메타데이터 로드

        Returns:
            메타데이터 dict (파일이 없으면 빈 dict)
        """
        return self.backend.load_metadata()

    def save_report(self, report_name: str, content: str) -> str:
        """
        리포트 파일 저장

        Args:
            report_name: 리포트 파일명 (예: "report_20240115_143052.md")
            content: 리포트 내용

        Returns:
            저장된 경로 (로컬: Path string, S3: s3://bucket/key 문자열)
        """
        return self.backend.save_report(report_name, content)

    def load_report(self, report_name: str) -> str:
        """
        리포트 파일 로드

        Args:
            report_name: 리포트 파일명

        Returns:
            리포트 내용

        Raises:
            FileNotFoundError: 리포트가 존재하지 않을 때
        """
        return self.backend.load_report(report_name)

    def save_log(self, log_name: str, content: str) -> str:
        """
        로그 파일 저장

        Args:
            log_name: 로그 파일명 (예: "combined.log")
            content: 로그 내용

        Returns:
            저장된 경로 (로컬: Path string, S3: s3://bucket/key 문자열)
        """
        return self.backend.save_log(log_name, content)

    def upload_log_directory(self, local_log_dir: Path, remote_subdir: str = None) -> List[str]:
        """
        로그 디렉토리 전체를 업로드

        Args:
            local_log_dir: 로컬 로그 디렉토리 경로
            remote_subdir: S3에 저장할 하위 디렉토리 (예: "debug" → logs/debug/)

        Returns:
            업로드된 파일 경로 리스트
        """
        return self.backend.upload_log_directory(local_log_dir, remote_subdir)

    def save_debug_file(self, relative_path: str, content: str | bytes) -> str:
        """
        디버그 파일 저장

        Args:
            relative_path: 상대 경로 (예: "debug/agents/reporter/request.json")
            content: 파일 내용 (문자열 또는 bytes)

        Returns:
            저장된 경로 (로컬: Path string, S3: s3://bucket/key 문자열)
        """
        return self.backend.save_debug_file(relative_path, content)

