"""
Orchestrator 설정 로더

YAML 파일에서 Orchestrator 설정을 로드
"""

import yaml
from pathlib import Path
from functools import lru_cache
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class OrchestratorConfig:
    """
    Orchestrator 설정 관리

    YAML 파일에서 설정을 로드하고 기본값 제공
    """

    def __init__(self, config_path: Path | None = None):
        """
        설정 초기화

        Args:
            config_path: 설정 파일 경로 (None이면 기본 경로 사용)
        """
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"

        self.config_path = config_path
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """설정 파일 로드"""
        if not self.config_path.exists():
            logger.warning(f"⚠️ 설정 파일 없음: {self.config_path}, 기본값 사용")
            return self._get_default_config()

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            logger.debug(f"✅ Orchestrator 설정 로드: {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"❌ 설정 파일 로드 실패: {e}, 기본값 사용")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """기본 설정 반환"""
        return {
            "parallel": {
                "commit_evaluator_batch_size": 10,
                "max_concurrent_agents": 4,
            },
            "timeout": {
                "agent_execution": 3600,
                "workflow": 7200,
            },
            "storage": {
                "encoding": "utf-8",
                "json_indent": 2,
            },
            "logging": {
                "level": "INFO",
                "show_progress": True,
            },
        }

    @property
    def commit_evaluator_batch_size(self) -> int:
        """CommitEvaluator 배치 크기"""
        return self._config.get("parallel", {}).get("commit_evaluator_batch_size", 10)

    @property
    def max_concurrent_agents(self) -> int:
        """최대 동시 실행 에이전트 수"""
        return self._config.get("parallel", {}).get("max_concurrent_agents", 4)

    @property
    def agent_execution_timeout(self) -> int:
        """에이전트 실행 타임아웃 (초)"""
        return self._config.get("timeout", {}).get("agent_execution", 3600)

    @property
    def workflow_timeout(self) -> int:
        """워크플로우 타임아웃 (초)"""
        return self._config.get("timeout", {}).get("workflow", 7200)

    @property
    def storage_encoding(self) -> str:
        """저장 인코딩"""
        return self._config.get("storage", {}).get("encoding", "utf-8")

    @property
    def json_indent(self) -> int:
        """JSON 들여쓰기"""
        return self._config.get("storage", {}).get("json_indent", 2)

    @property
    def log_level(self) -> str:
        """로그 레벨"""
        return self._config.get("logging", {}).get("level", "INFO")

    @property
    def show_progress(self) -> bool:
        """진행 상황 로그 출력 여부"""
        return self._config.get("logging", {}).get("show_progress", True)

