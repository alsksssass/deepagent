"""
Shared Pydantic schemas for Deep Agents

모든 에이전트가 공통으로 사용하는 스키마 정의
"""

from .common import (
    BaseContext,
    BaseResponse,
    ErrorResponse,
)

__all__ = [
    "BaseContext",
    "BaseResponse",
    "ErrorResponse",
]
