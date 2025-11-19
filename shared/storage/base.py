"""
Storage Backend 추상화 레이어

로컬 파일시스템과 S3를 투명하게 전환할 수 있는 추상 인터페이스
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Type, TypeVar, List, Any, Optional

from shared.schemas.common import BaseResponse

T = TypeVar("T", bound=BaseResponse)


class StorageBackend(ABC):
    """
    Storage Backend 추상 인터페이스

    구현체:
    - LocalStorageBackend: 로컬 파일시스템 (개발 환경)
    - S3StorageBackend: AWS S3 (프로덕션 환경)
    """

    def __init__(self, task_uuid: str, base_path: str | Path):
        """
        StorageBackend 초기화

        Args:
            task_uuid: 작업 고유 UUID
            base_path: 기본 경로 (local: "./data/analyze/{uuid}", S3: "s3://bucket/analyze/{uuid}")
        """
        self.task_uuid = task_uuid
        self.base_path = str(base_path)

    @abstractmethod
    def save_result(self, agent_name: str, result: BaseResponse) -> str:
        """
        에이전트 결과 저장

        Args:
            agent_name: 에이전트 이름
            result: Pydantic BaseResponse 인스턴스

        Returns:
            저장된 경로 (local: Path, S3: s3://bucket/key)
        """
        pass

    @abstractmethod
    def load_result(self, agent_name: str, result_class: Type[T]) -> T:
        """
        저장된 에이전트 결과 로드

        Args:
            agent_name: 에이전트 이름
            result_class: Pydantic Response 클래스

        Returns:
            로드된 Pydantic Response 인스턴스

        Raises:
            FileNotFoundError: 결과가 존재하지 않을 때
        """
        pass

    @abstractmethod
    def save_batched_result(
        self,
        agent_name: str,
        batch_id: int,
        result: BaseResponse | List[BaseResponse] | dict[str, Any],
    ) -> str:
        """
        대용량 결과를 배치별로 저장

        Args:
            agent_name: 에이전트 이름
            batch_id: 배치 번호
            result: 저장할 결과

        Returns:
            저장된 경로
        """
        pass

    @abstractmethod
    def load_batched_results(
        self,
        agent_name: str,
        result_class: Optional[Type[T]] = None,
    ) -> List[dict[str, Any]] | List[T]:
        """
        배치 결과 전체 로드

        Args:
            agent_name: 에이전트 이름
            result_class: Pydantic Response 클래스 (optional)

        Returns:
            배치 결과 리스트
        """
        pass

    @abstractmethod
    def save_metadata(self, metadata: dict[str, Any]) -> str:
        """
        작업 메타데이터 저장

        Args:
            metadata: 메타데이터 dict

        Returns:
            저장된 경로
        """
        pass

    @abstractmethod
    def load_metadata(self) -> dict[str, Any]:
        """
        작업 메타데이터 로드

        Returns:
            메타데이터 dict (없으면 빈 dict)
        """
        pass

    @abstractmethod
    def list_available_results(self) -> List[str]:
        """
        저장된 에이전트 결과 목록 조회

        Returns:
            에이전트 이름 리스트
        """
        pass

    @abstractmethod
    def list_batched_agents(self) -> List[str]:
        """
        배치 저장된 에이전트 목록 조회

        Returns:
            배치 저장된 에이전트 이름 리스트
        """
        pass

    @abstractmethod
    def get_result_path(self, agent_name: str) -> str:
        """
        에이전트 결과 경로 반환

        Args:
            agent_name: 에이전트 이름

        Returns:
            결과 경로 (local: Path string, S3: s3://bucket/key)
        """
        pass

    @abstractmethod
    def get_batch_dir(self, agent_name: str) -> str:
        """
        배치 결과 디렉토리 경로 반환

        Args:
            agent_name: 에이전트 이름

        Returns:
            배치 디렉토리 경로
        """
        pass

    @abstractmethod
    def save_report(self, report_name: str, content: str) -> str:
        """
        리포트 파일 저장

        Args:
            report_name: 리포트 파일명 (예: "report_20240115_143052.md")
            content: 리포트 내용 (문자열)

        Returns:
            저장된 경로 (local: Path string, S3: s3://bucket/key)
        """
        pass

    @abstractmethod
    def load_report(self, report_name: str) -> str:
        """
        리포트 파일 로드

        Args:
            report_name: 리포트 파일명

        Returns:
            리포트 내용 (문자열)

        Raises:
            FileNotFoundError: 리포트가 존재하지 않을 때
        """
        pass

    @abstractmethod
    def save_log(self, log_name: str, content: str) -> str:
        """
        로그 파일 저장

        Args:
            log_name: 로그 파일명 (예: "combined.log")
            content: 로그 내용 (문자열)

        Returns:
            저장된 경로 (local: Path string, S3: s3://bucket/key)
        """
        pass

    @abstractmethod
    def upload_log_directory(self, local_log_dir: Path, remote_subdir: str = None) -> List[str]:
        """
        로그 디렉토리 전체를 업로드 (S3용)

        Args:
            local_log_dir: 로컬 로그 디렉토리 경로
            remote_subdir: S3에 저장할 하위 디렉토리 (예: "debug" → logs/debug/)

        Returns:
            업로드된 파일 경로 리스트
        """
        pass

    @abstractmethod
    def save_debug_file(self, relative_path: str, content: str | bytes) -> str:
        """
        디버그 파일 저장 (디버그 로그용)

        Args:
            relative_path: 상대 경로 (예: "debug/agents/reporter/request.json")
            content: 파일 내용 (문자열 또는 bytes)

        Returns:
            저장된 경로 (local: Path string, S3: s3://bucket/key)
        """
        pass
