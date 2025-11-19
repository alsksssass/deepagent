"""
Agent Logging Utilities - 에이전트 로깅을 간소화하는 유틸리티

에이전트마다 반복되는 로깅 코드를 간소화하기 위한 데코레이터와 헬퍼 함수를 제공합니다.

Usage:
    # 방법 1: 데코레이터 사용 (가장 간단)
    from shared.utils.agent_logging import log_agent_execution
    
    class MyAgent:
        @log_agent_execution(agent_name="my_agent")
        async def run(self, context: MyAgentContext) -> MyAgentResponse:
            # 로깅이 자동으로 처리됨
            # context에서 task_uuid, result_store_path 자동 추출
            return MyAgentResponse(status="success", ...)
    
    # 방법 2: 헬퍼 함수 사용 (더 세밀한 제어)
    from shared.utils.agent_logging import with_agent_logging
    
    class MyAgent:
        async def run(self, context: MyAgentContext) -> MyAgentResponse:
            async with with_agent_logging(context, "my_agent") as logger:
                logger.log_intermediate("step1", data)
                # ... 작업 수행
                return MyAgentResponse(status="success", ...)
    
    # 방법 3: 베이스 클래스 사용 (가장 구조적)
    from shared.utils.agent_logging import BaseAgent
    
    class MyAgent(BaseAgent):
        agent_name = "my_agent"  # 클래스 변수로 정의
        
        async def run(self, context: MyAgentContext) -> MyAgentResponse:
            # self.logger가 자동으로 초기화됨
            self.logger.log_intermediate("step1", data)
            # ... 작업 수행
            return MyAgentResponse(status="success", ...)
"""

import functools
import inspect
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar, Generic
from contextlib import asynccontextmanager

import logging

from shared.utils.agent_debug_logger import AgentDebugLogger
from shared.schemas.common import BaseContext, BaseResponse

T = TypeVar("T", bound=BaseResponse)
C = TypeVar("C", bound=BaseContext)

logger = logging.getLogger(__name__)


def _extract_logging_info(context: BaseContext) -> tuple[str, Path]:
    """
    Context에서 로깅에 필요한 정보 추출
    
    Args:
        context: BaseContext 인스턴스
        
    Returns:
        (task_uuid, base_path) 튜플
    """
    task_uuid = context.task_uuid
    
    # base_path 추출: result_store_path가 있으면 그 부모, 없으면 기본 경로
    if hasattr(context, "result_store_path") and context.result_store_path:
        result_store_path = context.result_store_path
        # S3 경로인 경우 로컬 경로로 변환
        if isinstance(result_store_path, str) and result_store_path.startswith("s3://"):
            # S3 경로는 로컬 경로로 변환: s3://bucket/.../analyze/{task_uuid}/results -> ./data/analyze/{task_uuid}
            base_path = Path(f"./data/analyze/{task_uuid}")
        else:
            base_path = Path(result_store_path).parent
    else:
        base_path = Path(f"./data/analyze/{task_uuid}")
    
    return task_uuid, base_path


def log_agent_execution(agent_name: Optional[str] = None, auto_log_request: bool = True, auto_log_response: bool = True):
    """
    에이전트 run() 메서드를 자동으로 로깅하는 데코레이터
    
    Args:
        agent_name: 에이전트 이름 (None이면 클래스명에서 추출)
        auto_log_request: 자동으로 요청 로깅 여부 (기본값: True)
        auto_log_response: 자동으로 응답 로깅 여부 (기본값: True)
    
    Usage:
        @log_agent_execution(agent_name="my_agent")
        async def run(self, context: MyAgentContext) -> MyAgentResponse:
            # 로깅이 자동으로 처리됨
            return MyAgentResponse(status="success", ...)
        
        # 또는 agent_name 생략 시 클래스명에서 자동 추출
        class MyAgent:
            @log_agent_execution()  # "my_agent"로 자동 추출
            async def run(self, context: MyAgentContext) -> MyAgentResponse:
                return MyAgentResponse(status="success", ...)
    """
    def decorator(func: Callable) -> Callable:
        # agent_name이 없으면 클래스명에서 추출
        actual_agent_name = agent_name
        if actual_agent_name is None:
            # 함수의 qualname에서 클래스명 추출 시도
            # 예: "MyAgent.run" -> "MyAgent" -> "my_agent"
            qualname = getattr(func, "__qualname__", "")
            if "." in qualname:
                class_name = qualname.split(".")[0]
                # "Agent" 접미사 제거 후 소문자로 변환
                actual_agent_name = class_name.replace("Agent", "").lower()
                # CamelCase를 snake_case로 변환
                import re
                actual_agent_name = re.sub(r'(?<!^)(?=[A-Z])', '_', actual_agent_name).lower()
            else:
                # 클래스명을 찾을 수 없으면 함수명 사용
                actual_agent_name = func.__name__
        
        @functools.wraps(func)
        async def async_wrapper(self, context: BaseContext, *args, **kwargs) -> BaseResponse:
            # 런타임에 클래스명에서 agent_name 추출 시도 (데코레이터 시점에는 self가 없음)
            final_agent_name = actual_agent_name
            if final_agent_name is None or final_agent_name == func.__name__:
                # self에서 클래스명 추출
                class_name = self.__class__.__name__
                # "Agent" 접미사 제거 후 소문자로 변환
                final_agent_name = class_name.replace("Agent", "").lower()
                # CamelCase를 snake_case로 변환
                import re
                final_agent_name = re.sub(r'(?<!^)(?=[A-Z])', '_', final_agent_name).lower()
            
            task_uuid, base_path = _extract_logging_info(context)
            debug_logger = AgentDebugLogger.get_logger(task_uuid, base_path, final_agent_name)
            
            with debug_logger.track_execution():
                if auto_log_request:
                    debug_logger.log_request(context)
                
                try:
                    # 원본 함수 실행
                    response = await func(self, context, *args, **kwargs)
                    
                    if auto_log_response and isinstance(response, BaseResponse):
                        debug_logger.log_response(response)
                    
                    return response
                except Exception as e:
                    # track_execution이 자동으로 예외 로깅하지만, 에러 응답도 로깅
                    if auto_log_response:
                        try:
                            # 에러 응답 생성 시도
                            error_response = BaseResponse(
                                status="failed",
                                error=str(e)
                            )
                            debug_logger.log_response(error_response)
                        except:
                            pass
                    raise
        
        @functools.wraps(func)
        def sync_wrapper(self, context: BaseContext, *args, **kwargs) -> BaseResponse:
            # 런타임에 클래스명에서 agent_name 추출 시도
            final_agent_name = actual_agent_name
            if final_agent_name is None or final_agent_name == func.__name__:
                # self에서 클래스명 추출
                class_name = self.__class__.__name__
                # "Agent" 접미사 제거 후 소문자로 변환
                final_agent_name = class_name.replace("Agent", "").lower()
                # CamelCase를 snake_case로 변환
                import re
                final_agent_name = re.sub(r'(?<!^)(?=[A-Z])', '_', final_agent_name).lower()
            
            task_uuid, base_path = _extract_logging_info(context)
            debug_logger = AgentDebugLogger.get_logger(task_uuid, base_path, final_agent_name)
            
            with debug_logger.track_execution():
                if auto_log_request:
                    debug_logger.log_request(context)
                
                try:
                    # 원본 함수 실행
                    response = func(self, context, *args, **kwargs)
                    
                    if auto_log_response and isinstance(response, BaseResponse):
                        debug_logger.log_response(response)
                    
                    return response
                except Exception as e:
                    # track_execution이 자동으로 예외 로깅하지만, 에러 응답도 로깅
                    if auto_log_response:
                        try:
                            # 에러 응답 생성 시도
                            error_response = BaseResponse(
                                status="failed",
                                error=str(e)
                            )
                            debug_logger.log_response(error_response)
                        except:
                            pass
                    raise
        
        # 함수가 async인지 확인
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def log_subagent_execution(parent_agent_name: str, subagent_name: Optional[str] = None, auto_log_request: bool = True, auto_log_response: bool = True):
    """
    서브에이전트 run() 메서드를 자동으로 로깅하는 데코레이터
    
    서브에이전트는 부모 에이전트의 logger를 통해 서브 로거를 가져옵니다.
    
    Args:
        parent_agent_name: 부모 에이전트 이름 (예: "user_skill_profiler")
        subagent_name: 서브에이전트 이름 (None이면 클래스명에서 추출)
        auto_log_request: 자동으로 요청 로깅 여부 (기본값: True)
        auto_log_response: 자동으로 응답 로깅 여부 (기본값: True)
    
    Usage:
        @log_subagent_execution(parent_agent_name="user_skill_profiler", subagent_name="code_batch_processor_batch_0")
        async def run(self, context: CodeBatchContext) -> CodeBatchResponse:
            # 로깅이 자동으로 처리됨
            return CodeBatchResponse(...)
    """
    def decorator(func: Callable) -> Callable:
        # subagent_name이 없으면 클래스명에서 추출
        actual_subagent_name = subagent_name
        if actual_subagent_name is None:
            qualname = getattr(func, "__qualname__", "")
            if "." in qualname:
                class_name = qualname.split(".")[0]
                actual_subagent_name = class_name.replace("Agent", "").lower()
                import re
                actual_subagent_name = re.sub(r'(?<!^)(?=[A-Z])', '_', actual_subagent_name).lower()
            else:
                actual_subagent_name = func.__name__
        
        @functools.wraps(func)
        async def async_wrapper(self, context: BaseContext, *args, **kwargs) -> BaseResponse:
            # 런타임에 subagent_name 추출 시도
            final_subagent_name = actual_subagent_name
            if final_subagent_name is None or final_subagent_name == func.__name__:
                class_name = self.__class__.__name__
                final_subagent_name = class_name.replace("Agent", "").lower()
                import re
                final_subagent_name = re.sub(r'(?<!^)(?=[A-Z])', '_', final_subagent_name).lower()
            
            # Context에서 batch_id 등 추가 정보 추출하여 subagent_name 구성
            if hasattr(context, "batch_id"):
                final_subagent_name = f"{final_subagent_name}_batch_{context.batch_id}"
            
            task_uuid, base_path = _extract_logging_info(context)
            
            # 부모 에이전트 logger 가져오기
            parent_logger = AgentDebugLogger.get_logger(task_uuid, base_path, parent_agent_name)
            # 서브에이전트 logger 가져오기
            debug_logger = parent_logger.get_subagent_logger(final_subagent_name)
            
            with debug_logger.track_execution():
                if auto_log_request:
                    debug_logger.log_request(context)
                
                try:
                    # 원본 함수 실행
                    response = await func(self, context, *args, **kwargs)
                    
                    if auto_log_response and isinstance(response, BaseResponse):
                        debug_logger.log_response(response)
                    
                    return response
                except Exception as e:
                    if auto_log_response:
                        try:
                            error_response = BaseResponse(
                                status="failed",
                                error=str(e)
                            )
                            debug_logger.log_response(error_response)
                        except:
                            pass
                    raise
        
        @functools.wraps(func)
        def sync_wrapper(self, context: BaseContext, *args, **kwargs) -> BaseResponse:
            # 런타임에 subagent_name 추출 시도
            final_subagent_name = actual_subagent_name
            if final_subagent_name is None or final_subagent_name == func.__name__:
                class_name = self.__class__.__name__
                final_subagent_name = class_name.replace("Agent", "").lower()
                import re
                final_subagent_name = re.sub(r'(?<!^)(?=[A-Z])', '_', final_subagent_name).lower()
            
            # Context에서 batch_id 등 추가 정보 추출하여 subagent_name 구성
            if hasattr(context, "batch_id"):
                final_subagent_name = f"{final_subagent_name}_batch_{context.batch_id}"
            
            task_uuid, base_path = _extract_logging_info(context)
            
            # 부모 에이전트 logger 가져오기
            parent_logger = AgentDebugLogger.get_logger(task_uuid, base_path, parent_agent_name)
            # 서브에이전트 logger 가져오기
            debug_logger = parent_logger.get_subagent_logger(final_subagent_name)
            
            with debug_logger.track_execution():
                if auto_log_request:
                    debug_logger.log_request(context)
                
                try:
                    # 원본 함수 실행
                    response = func(self, context, *args, **kwargs)
                    
                    if auto_log_response and isinstance(response, BaseResponse):
                        debug_logger.log_response(response)
                    
                    return response
                except Exception as e:
                    if auto_log_response:
                        try:
                            error_response = BaseResponse(
                                status="failed",
                                error=str(e)
                            )
                            debug_logger.log_response(error_response)
                        except:
                            pass
                    raise
        
        # 함수가 async인지 확인
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


@asynccontextmanager
async def with_agent_logging(context: BaseContext, agent_name: str, auto_log_request: bool = True):
    """
    에이전트 로깅을 위한 비동기 컨텍스트 매니저
    
    Args:
        context: BaseContext 인스턴스
        agent_name: 에이전트 이름
        auto_log_request: 자동으로 요청 로깅 여부 (기본값: True)
    
    Usage:
        async with with_agent_logging(context, "my_agent") as logger:
            logger.log_intermediate("step1", data)
            # ... 작업 수행
            logger.log_response(response)
    """
    task_uuid, base_path = _extract_logging_info(context)
    debug_logger = AgentDebugLogger.get_logger(task_uuid, base_path, agent_name)
    
    with debug_logger.track_execution():
        if auto_log_request:
            debug_logger.log_request(context)
        
        yield debug_logger


class BaseAgent:
    """
    모든 에이전트가 상속받을 수 있는 베이스 클래스
    
    자동으로 로깅을 초기화하고, self.logger를 통해 접근할 수 있게 합니다.
    
    Usage:
        class MyAgent(BaseAgent):
            agent_name = "my_agent"  # 필수: 클래스 변수로 정의
            
            async def run(self, context: MyAgentContext) -> MyAgentResponse:
                # self.logger가 자동으로 초기화됨
                self.logger.log_intermediate("step1", data)
                # ... 작업 수행
                self.logger.log_response(response)
                return MyAgentResponse(status="success", ...)
    """
    
    agent_name: str = None  # 하위 클래스에서 반드시 정의해야 함
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._logger: Optional[AgentDebugLogger] = None
        self._current_context: Optional[BaseContext] = None
    
    def _init_logger(self, context: BaseContext) -> AgentDebugLogger:
        """로거 초기화 (내부 메서드)"""
        if self.agent_name is None:
            raise ValueError(f"{self.__class__.__name__} must define 'agent_name' class variable")
        
        task_uuid, base_path = _extract_logging_info(context)
        self._logger = AgentDebugLogger.get_logger(task_uuid, base_path, self.agent_name)
        self._current_context = context
        return self._logger
    
    @property
    def logger(self) -> AgentDebugLogger:
        """로거 접근 (Context가 설정된 후에만 사용 가능)"""
        if self._logger is None:
            raise RuntimeError(
                f"Logger not initialized. Call _init_logger(context) first, "
                f"or use run() method with @log_agent_execution decorator."
            )
        return self._logger
    
    async def run(self, context: BaseContext) -> BaseResponse:
        """
        에이전트 실행 메서드 (하위 클래스에서 오버라이드)
        
        이 메서드를 오버라이드할 때는 @log_agent_execution 데코레이터를 사용하거나,
        수동으로 _init_logger()를 호출해야 합니다.
        """
        raise NotImplementedError("Subclasses must implement run() method")

