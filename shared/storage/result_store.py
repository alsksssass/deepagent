"""
ResultStore - 에이전트 결과 저장 및 관리

에이전트 실행 결과를 JSON 파일로 저장하고 타입 안전하게 로드하는 스토리지 매니저

구조:
    data/analyze/{task_uuid}/
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
    """

    def __init__(self, task_uuid: str, base_path: Path):
        """
        ResultStore 초기화

        Args:
            task_uuid: 작업 고유 UUID
            base_path: 작업 기본 경로 (예: Path("./data/analyze/{task_uuid}"))
        """
        self.task_uuid = task_uuid
        self.base_path = Path(base_path)
        self.results_dir = self.base_path / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"📦 ResultStore 초기화: {self.results_dir}")

    def save_result(
        self,
        agent_name: str,
        result: BaseResponse,
    ) -> Path:
        """
        에이전트 결과를 JSON 파일로 저장

        Args:
            agent_name: 에이전트 이름 (예: "repo_cloner", "static_analyzer")
            result: Pydantic BaseResponse 인스턴스

        Returns:
            저장된 파일 경로

        Example:
            >>> store = ResultStore("task-123", Path("./data/analyze/task-123"))
            >>> response = RepoClonerResponse(status="success", repo_path="/path/to/repo")
            >>> file_path = store.save_result("repo_cloner", response)
            >>> print(file_path)
            Path("./data/analyze/task-123/results/repo_cloner.json")
        """
        file_path = self.results_dir / f"{agent_name}.json"

        try:
            # Pydantic 모델을 JSON으로 직렬화
            json_content = result.model_dump_json(indent=2, ensure_ascii=False)
            file_path.write_text(json_content, encoding="utf-8")

            logger.info(f"💾 결과 저장: {agent_name} → {file_path}")
            return file_path

        except Exception as e:
            logger.error(f"❌ 결과 저장 실패 ({agent_name}): {e}")
            raise

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
        file_path = self.results_dir / f"{agent_name}.json"

        if not file_path.exists():
            raise FileNotFoundError(
                f"결과 파일을 찾을 수 없습니다: {agent_name} ({file_path})"
            )

        try:
            # JSON 파일 읽기
            json_content = file_path.read_text(encoding="utf-8")
            data = json.loads(json_content)

            # Pydantic 모델로 역직렬화
            result = result_class(**data)

            logger.debug(f"📂 결과 로드: {agent_name} ← {file_path}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON 파싱 실패 ({agent_name}): {e}")
            raise ValueError(f"잘못된 JSON 형식: {agent_name}") from e
        except Exception as e:
            logger.error(f"❌ 결과 로드 실패 ({agent_name}): {e}")
            raise

    def save_batched_result(
        self,
        agent_name: str,
        batch_id: int,
        result: BaseResponse | List[BaseResponse] | dict[str, Any],
    ) -> Path:
        """
        대용량 결과를 배치별로 저장 (CommitEvaluator 등)

        Args:
            agent_name: 에이전트 이름 (예: "commit_evaluator")
            batch_id: 배치 번호 (0부터 시작)
            result: 저장할 결과 (Pydantic Response, Response 리스트, 또는 dict)

        Returns:
            저장된 파일 경로

        Example:
            >>> store = ResultStore("task-123", Path("./data/analyze/task-123"))
            >>> batch_results = [CommitEvaluatorResponse(...) for _ in range(100)]
            >>> file_path = store.save_batched_result("commit_evaluator", 0, batch_results)
            >>> print(file_path)
            Path("./data/analyze/task-123/results/commit_evaluator/batch_0000.json")
        """
        batch_dir = self.results_dir / agent_name
        batch_dir.mkdir(parents=True, exist_ok=True)

        file_path = batch_dir / f"batch_{batch_id:04d}.json"

        try:
            # 결과 타입에 따라 직렬화
            if isinstance(result, BaseResponse):
                json_content = result.model_dump_json(indent=2, ensure_ascii=False)
            elif isinstance(result, list) and result and isinstance(result[0], BaseResponse):
                # Pydantic Response 리스트
                json_content = json.dumps(
                    [r.model_dump() for r in result],
                    indent=2,
                    ensure_ascii=False,
                )
            elif isinstance(result, dict):
                # dict 직접 저장
                json_content = json.dumps(result, indent=2, ensure_ascii=False)
            else:
                # 기타 타입은 JSON 직렬화 시도
                json_content = json.dumps(result, indent=2, ensure_ascii=False, default=str)

            file_path.write_text(json_content, encoding="utf-8")

            logger.info(f"💾 배치 결과 저장: {agent_name}/batch_{batch_id:04d} → {file_path}")
            return file_path

        except Exception as e:
            logger.error(f"❌ 배치 결과 저장 실패 ({agent_name}/batch_{batch_id}): {e}")
            raise

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
        batch_dir = self.results_dir / agent_name

        if not batch_dir.exists():
            raise FileNotFoundError(
                f"배치 디렉토리를 찾을 수 없습니다: {agent_name} ({batch_dir})"
            )

        # 배치 파일 목록 가져오기 (정렬)
        batch_files = sorted(batch_dir.glob("batch_*.json"))

        if not batch_files:
            logger.warning(f"⚠️  배치 파일이 없습니다: {agent_name}")
            return []

        results = []

        for batch_file in batch_files:
            try:
                json_content = batch_file.read_text(encoding="utf-8")
                data = json.loads(json_content)

                # result_class가 지정된 경우 Pydantic으로 변환
                if result_class:
                    if isinstance(data, list):
                        # 리스트인 경우 각 항목을 Pydantic으로 변환
                        results.extend([result_class(**item) for item in data])
                    else:
                        # 단일 객체인 경우
                        results.append(result_class(**data))
                else:
                    # dict 그대로 반환
                    if isinstance(data, list):
                        results.extend(data)
                    else:
                        results.append(data)

            except Exception as e:
                logger.error(f"❌ 배치 파일 로드 실패 ({batch_file}): {e}")
                continue

        logger.debug(f"📂 배치 결과 로드: {agent_name} - {len(results)}개 항목")
        return results

    def get_result_path(self, agent_name: str) -> Path:
        """
        에이전트 결과 파일 경로 반환 (에이전트가 직접 파일 읽기 가능)

        Args:
            agent_name: 에이전트 이름

        Returns:
            결과 파일 경로 (존재하지 않을 수 있음)

        Example:
            >>> store = ResultStore("task-123", Path("./data/analyze/task-123"))
            >>> path = store.get_result_path("static_analyzer")
            >>> if path.exists():
            ...     data = json.loads(path.read_text())
        """
        return self.results_dir / f"{agent_name}.json"

    def get_batch_dir(self, agent_name: str) -> Path:
        """
        배치 결과 디렉토리 경로 반환

        Args:
            agent_name: 에이전트 이름

        Returns:
            배치 디렉토리 경로
        """
        return self.results_dir / agent_name

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
        if not self.results_dir.exists():
            return []

        # JSON 파일만 필터링 (디렉토리 제외)
        result_files = [
            f.stem
            for f in self.results_dir.iterdir()
            if f.is_file() and f.suffix == ".json"
        ]

        return sorted(result_files)

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
        if not self.results_dir.exists():
            return []

        # 배치 디렉토리만 필터링
        batched_agents = [
            d.name
            for d in self.results_dir.iterdir()
            if d.is_dir() and any(d.glob("batch_*.json"))
        ]

        return sorted(batched_agents)

    def save_metadata(self, metadata: dict[str, Any]) -> Path:
        """
        작업 메타데이터 저장

        Args:
            metadata: 메타데이터 dict

        Returns:
            저장된 파일 경로
        """
        metadata_path = self.base_path / "metadata.json"

        # 타임스탬프 추가
        metadata["updated_at"] = datetime.now().isoformat()

        try:
            json_content = json.dumps(metadata, indent=2, ensure_ascii=False, default=str)
            metadata_path.write_text(json_content, encoding="utf-8")

            logger.debug(f"💾 메타데이터 저장: {metadata_path}")
            return metadata_path

        except Exception as e:
            logger.error(f"❌ 메타데이터 저장 실패: {e}")
            raise

    def load_metadata(self) -> dict[str, Any]:
        """
        작업 메타데이터 로드

        Returns:
            메타데이터 dict (파일이 없으면 빈 dict)
        """
        metadata_path = self.base_path / "metadata.json"

        if not metadata_path.exists():
            return {}

        try:
            json_content = metadata_path.read_text(encoding="utf-8")
            return json.loads(json_content)

        except Exception as e:
            logger.error(f"❌ 메타데이터 로드 실패: {e}")
            return {}

