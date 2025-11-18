"""
CodeBatchProcessor Agent

코드 배치 병렬 처리 하위 에이전트

Level 1 워커 에이전트로서, 10개 내외의 코드 샘플을 병렬로 LLM 분석하여
부모 에이전트(UserSkillProfiler)의 성능을 획기적으로 향상시킵니다.

주요 기능:
- 코드 배치 병렬 LLM 분석
- Pydantic validation 자체 검증
- 계층적 재시도 메커니즘 (최대 3회)
- 성공률 80% 이상 보장
- 실패한 코드 추적 및 재처리
"""

# agent는 나중에 구현되므로 조건부 import
try:
    from .agent import CodeBatchProcessorAgent
    _has_agent = True
except ImportError:
    _has_agent = False

from .schemas import CodeBatchContext, CodeBatchResponse, CodeSample
from .smart_batcher import SmartBatcher

__all__ = [
    "CodeBatchContext",
    "CodeBatchResponse",
    "CodeSample",
    "SmartBatcher",
]

if _has_agent:
    __all__.append("CodeBatchProcessorAgent")
