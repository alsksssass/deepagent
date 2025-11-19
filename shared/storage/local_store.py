"""
LocalStorageBackend - 로컬 파일시스템 기반 스토리지

로컬 환경에서 JSON 파일로 결과를 저장/로드
"""

import json
import logging
from pathlib import Path
from typing import Type, TypeVar, Optional, List, Any

from shared.storage.base import StorageBackend
from shared.schemas.common import BaseResponse

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseResponse)


class LocalStorageBackend(StorageBackend):
    """
    로컬 파일시스템 기반 스토리지 백엔드

    구조:
        data/analyze/{task_uuid}/
        ├── results/
        │   ├── repo_cloner.json
        │   ├── static_analyzer.json
        │   ├── commit_evaluator/
        │   │   ├── batch_0000.json
        │   │   └── batch_0001.json
        │   └── reporter.json
        └── metadata.json
    """

    def __init__(self, task_uuid: str, base_path: str | Path):
        """
        LocalStorageBackend 초기화

        Args:
            task_uuid: 작업 고유 UUID
            base_path: 기본 경로 (예: "./data/analyze/{task_uuid}")
        """
        super().__init__(task_uuid, base_path)
        self.base_path_obj = Path(base_path)
        self.results_dir = self.base_path_obj / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"📦 LocalStorageBackend 초기화: {self.results_dir}")

    def save_result(self, agent_name: str, result: BaseResponse) -> str:
        """에이전트 결과를 JSON 파일로 저장"""
        file_path = self.results_dir / f"{agent_name}.json"

        try:
            json_content = result.model_dump_json(indent=2, ensure_ascii=False)
            file_path.write_text(json_content, encoding="utf-8")

            logger.info(f"💾 결과 저장 (Local): {agent_name} → {file_path}")
            return str(file_path)

        except Exception as e:
            logger.error(f"❌ 결과 저장 실패 ({agent_name}): {e}")
            raise

    def load_result(self, agent_name: str, result_class: Type[T]) -> T:
        """저장된 에이전트 결과를 타입 안전하게 로드"""
        file_path = self.results_dir / f"{agent_name}.json"

        if not file_path.exists():
            raise FileNotFoundError(
                f"결과 파일을 찾을 수 없습니다: {agent_name} ({file_path})"
            )

        try:
            json_content = file_path.read_text(encoding="utf-8")
            data = json.loads(json_content)
            result = result_class(**data)

            logger.debug(f"📂 결과 로드 (Local): {agent_name} ← {file_path}")
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
    ) -> str:
        """대용량 결과를 배치별로 저장"""
        batch_dir = self.results_dir / agent_name
        batch_dir.mkdir(parents=True, exist_ok=True)

        file_path = batch_dir / f"batch_{batch_id:04d}.json"

        try:
            # 결과 타입에 따라 직렬화
            if isinstance(result, BaseResponse):
                json_content = result.model_dump_json(indent=2, ensure_ascii=False)
            elif isinstance(result, list) and result and isinstance(result[0], BaseResponse):
                json_content = json.dumps(
                    [r.model_dump() for r in result],
                    indent=2,
                    ensure_ascii=False,
                )
            elif isinstance(result, dict):
                json_content = json.dumps(result, indent=2, ensure_ascii=False)
            else:
                json_content = json.dumps(result, indent=2, ensure_ascii=False, default=str)

            file_path.write_text(json_content, encoding="utf-8")

            logger.info(f"💾 배치 결과 저장 (Local): {agent_name}/batch_{batch_id:04d} → {file_path}")
            return str(file_path)

        except Exception as e:
            logger.error(f"❌ 배치 결과 저장 실패 ({agent_name}/batch_{batch_id}): {e}")
            raise

    def load_batched_results(
        self,
        agent_name: str,
        result_class: Optional[Type[T]] = None,
    ) -> List[dict[str, Any]] | List[T]:
        """배치 결과 전체를 로드"""
        batch_dir = self.results_dir / agent_name

        if not batch_dir.exists():
            raise FileNotFoundError(
                f"배치 디렉토리를 찾을 수 없습니다: {agent_name} ({batch_dir})"
            )

        batch_files = sorted(batch_dir.glob("batch_*.json"))

        if not batch_files:
            logger.warning(f"⚠️  배치 파일이 없습니다: {agent_name}")
            return []

        results = []

        for batch_file in batch_files:
            try:
                json_content = batch_file.read_text(encoding="utf-8")
                data = json.loads(json_content)

                if result_class:
                    if isinstance(data, list):
                        results.extend([result_class(**item) for item in data])
                    else:
                        results.append(result_class(**data))
                else:
                    if isinstance(data, list):
                        results.extend(data)
                    else:
                        results.append(data)

            except Exception as e:
                logger.error(f"❌ 배치 파일 로드 실패 ({batch_file}): {e}")
                continue

        logger.debug(f"📂 배치 결과 로드 (Local): {agent_name} - {len(results)}개 항목")
        return results

    def save_metadata(self, metadata: dict[str, Any]) -> str:
        """작업 메타데이터 저장"""
        from datetime import datetime

        metadata_path = self.base_path_obj / "metadata.json"

        # 타임스탬프 추가
        metadata["updated_at"] = datetime.now().isoformat()

        try:
            json_content = json.dumps(metadata, indent=2, ensure_ascii=False, default=str)
            metadata_path.write_text(json_content, encoding="utf-8")

            logger.debug(f"💾 메타데이터 저장 (Local): {metadata_path}")
            return str(metadata_path)

        except Exception as e:
            logger.error(f"❌ 메타데이터 저장 실패: {e}")
            raise

    def load_metadata(self) -> dict[str, Any]:
        """작업 메타데이터 로드"""
        metadata_path = self.base_path_obj / "metadata.json"

        if not metadata_path.exists():
            return {}

        try:
            json_content = metadata_path.read_text(encoding="utf-8")
            return json.loads(json_content)

        except Exception as e:
            logger.error(f"❌ 메타데이터 로드 실패: {e}")
            return {}

    def list_available_results(self) -> List[str]:
        """저장된 에이전트 결과 목록 조회"""
        if not self.results_dir.exists():
            return []

        result_files = [
            f.stem
            for f in self.results_dir.iterdir()
            if f.is_file() and f.suffix == ".json"
        ]

        return sorted(result_files)

    def list_batched_agents(self) -> List[str]:
        """배치 저장된 에이전트 목록 조회"""
        if not self.results_dir.exists():
            return []

        batched_agents = [
            d.name
            for d in self.results_dir.iterdir()
            if d.is_dir() and any(d.glob("batch_*.json"))
        ]

        return sorted(batched_agents)

    def get_result_path(self, agent_name: str) -> str:
        """에이전트 결과 파일 경로 반환"""
        return str(self.results_dir / f"{agent_name}.json")

    def get_batch_dir(self, agent_name: str) -> str:
        """배치 결과 디렉토리 경로 반환"""
        return str(self.results_dir / agent_name)

    def save_report(self, report_name: str, content: str) -> str:
        """리포트 파일 저장"""
        reports_dir = self.base_path_obj / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        report_path = reports_dir / report_name
        report_path.write_text(content, encoding="utf-8")
        
        logger.info(f"💾 리포트 저장 (Local): {report_path}")
        return str(report_path)

    def load_report(self, report_name: str) -> str:
        """리포트 파일 로드"""
        report_path = self.base_path_obj / "reports" / report_name
        
        if not report_path.exists():
            raise FileNotFoundError(f"리포트 파일을 찾을 수 없습니다: {report_name}")
        
        return report_path.read_text(encoding="utf-8")

    def save_log(self, log_name: str, content: str) -> str:
        """로그 파일 저장"""
        logs_dir = self.base_path_obj / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        log_path = logs_dir / log_name
        log_path.write_text(content, encoding="utf-8")
        
        logger.info(f"💾 로그 저장 (Local): {log_path}")
        return str(log_path)

    def upload_log_directory(self, local_log_dir: Path, remote_subdir: str = None) -> List[str]:
        """로컬에서는 단순히 경로 반환 (업로드 불필요)"""
        if not local_log_dir.exists():
            return []
        
        uploaded_paths = []
        for log_file in local_log_dir.rglob("*"):
            if log_file.is_file():
                uploaded_paths.append(str(log_file))
        
        return uploaded_paths

    def save_debug_file(self, relative_path: str, content: str | bytes) -> str:
        """디버그 파일 저장 (로컬)"""
        file_path = self.base_path_obj / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        if isinstance(content, bytes):
            file_path.write_bytes(content)
        else:
            file_path.write_text(content, encoding="utf-8")
        
        return str(file_path)
