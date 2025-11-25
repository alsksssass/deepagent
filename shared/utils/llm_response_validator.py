"""
LLM 응답 검증 및 재시도 관리 유틸리티

Pydantic 모델 기반 검증과 자동 재시도 로직을 통합하여
코드 중복을 제거하고 유지보수성을 향상시킵니다.
"""

import asyncio
import json
import logging
from typing import TypeVar, Type, Optional, Callable, Any
from pydantic import BaseModel, Field, ValidationError

T = TypeVar('T', bound=BaseModel)

logger = logging.getLogger(__name__)


class RetryConfig(BaseModel):
    """재시도 설정 (Pydantic 모델)"""
    max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description="최대 재시도 횟수"
    )
    retry_delay: float = Field(
        default=0.5,
        ge=0,
        le=5.0,
        description="재시도 대기 시간 (초)"
    )
    exponential_backoff: bool = Field(
        default=False,
        description="지수 백오프 사용 여부"
    )
    retry_on_validation_error: bool = Field(
        default=True,
        description="ValidationError 시 재시도"
    )
    retry_on_json_error: bool = Field(
        default=True,
        description="JSONDecodeError 시 재시도"
    )
    retry_on_timeout: bool = Field(
        default=True,
        description="TimeoutError 시 재시도"
    )
    default_on_final_failure: Optional[Callable[[], T]] = Field(
        default=None,
        description="최종 실패 시 기본값 생성 함수"
    )


class LLMResponseValidator:
    """
    LLM 응답 검증 및 재시도 관리 클래스
    
    사용 예시:
        validator = LLMResponseValidator(
            response_model=SkillAnalysisOutput,
            retry_config=RetryConfig(max_retries=2, retry_delay=0.5)
        )
        
        result = await validator.validate_with_retry(
            llm_call=lambda: structured_llm.ainvoke(messages),
            normalize_fn=lambda r: normalize_response(r)
        )
    """
    
    def __init__(
        self,
        response_model: Type[T],
        retry_config: RetryConfig = RetryConfig()
    ):
        """
        Args:
            response_model: 검증할 Pydantic 모델 클래스
            retry_config: 재시도 설정
        """
        self.response_model = response_model
        self.config = retry_config
        self.logger = logging.getLogger(__name__)
    
    async def validate_with_retry(
        self,
        llm_call: Callable[[], Any],
        normalize_fn: Optional[Callable[[Any], Any]] = None,
        context: Optional[str] = None
    ) -> T:
        """
        LLM 호출, 검증, 재시도 통합 처리
        
        Args:
            llm_call: LLM 호출 함수 (async)
            normalize_fn: 응답 정규화 함수 (선택적)
            context: 컨텍스트 정보 (로깅용)
            
        Returns:
            검증된 Pydantic 모델 인스턴스
            
        Raises:
            ValidationError: 최종 검증 실패 시 (default_on_final_failure가 없으면)
        """
        last_error = None
        context_str = context or "LLM"
        
        for attempt in range(self.config.max_retries + 1):
            try:
                # LLM 호출
                raw_result = await llm_call()
                
                # 정규화 (선택적)
                if normalize_fn:
                    raw_result = normalize_fn(raw_result)
                
                # Pydantic 검증
                if isinstance(raw_result, self.response_model):
                    return raw_result
                elif isinstance(raw_result, dict):
                    return self.response_model(**raw_result)
                else:
                    raise ValueError(f"Unexpected response type: {type(raw_result)}")
                    
            except ValidationError as e:
                last_error = e
                if not self.config.retry_on_validation_error or attempt >= self.config.max_retries:
                    if self.config.default_on_final_failure:
                        self.logger.warning(
                            f"⚠️ {context_str} ValidationError 최종 실패, 기본값 사용: {e}"
                        )
                        return self.config.default_on_final_failure()
                    raise
                
                self.logger.warning(
                    f"⚠️ {context_str} ValidationError (시도 {attempt + 1}/{self.config.max_retries + 1}): {e}"
                )
                await self._wait_before_retry(attempt)
                
            except (json.JSONDecodeError, ValueError) as e:
                last_error = e
                if not self.config.retry_on_json_error or attempt >= self.config.max_retries:
                    if self.config.default_on_final_failure:
                        self.logger.warning(
                            f"⚠️ {context_str} JSON 파싱 최종 실패, 기본값 사용: {e}"
                        )
                        return self.config.default_on_final_failure()
                    raise
                
                self.logger.warning(
                    f"⚠️ {context_str} JSON 파싱 실패 (시도 {attempt + 1}/{self.config.max_retries + 1}): {e}"
                )
                await self._wait_before_retry(attempt)
                
            except asyncio.TimeoutError as e:
                last_error = e
                if not self.config.retry_on_timeout or attempt >= self.config.max_retries:
                    if self.config.default_on_final_failure:
                        self.logger.warning(
                            f"⚠️ {context_str} Timeout 최종 실패, 기본값 사용"
                        )
                        return self.config.default_on_final_failure()
                    raise
                
                self.logger.warning(
                    f"⚠️ {context_str} Timeout (시도 {attempt + 1}/{self.config.max_retries + 1})"
                )
                await self._wait_before_retry(attempt)
                
            except Exception as e:
                last_error = e
                if attempt >= self.config.max_retries:
                    if self.config.default_on_final_failure:
                        self.logger.error(
                            f"❌ {context_str} 예상치 못한 오류 최종 실패, 기본값 사용: {e}"
                        )
                        return self.config.default_on_final_failure()
                    raise
                
                self.logger.error(f"❌ {context_str} 예상치 못한 오류 (시도 {attempt + 1}/{self.config.max_retries + 1}): {e}")
                await self._wait_before_retry(attempt)
        
        # 모든 재시도 실패
        if self.config.default_on_final_failure:
            return self.config.default_on_final_failure()
        raise last_error or ValueError("Unknown error")
    
    async def _wait_before_retry(self, attempt: int):
        """재시도 전 대기"""
        if self.config.exponential_backoff:
            delay = self.config.retry_delay * (2 ** attempt)
        else:
            delay = self.config.retry_delay
        await asyncio.sleep(delay)

