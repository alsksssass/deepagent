"""
AgentDebugLogger - 에이전트 디버깅 로그를 구조화하여 저장하는 클래스

에이전트별/서브에이전트별로 요청, 응답, LLM 호출 등을 파일로 저장하여
디버깅 시 쉽게 확인할 수 있도록 지원합니다.

구조:
    data/analyze/{task_uuid}/
    ├── results/              # 기존 ResultStore
    └── debug/                # 디버깅 로그
        ├── agents/
        │   ├── {agent_name}/
        │   │   ├── request.json
        │   │   ├── response.json
        │   │   ├── llm_calls/
        │   │   │   ├── call_001_request.json
        │   │   │   ├── call_001_response.json
        │   │   │   └── call_001_metadata.json
        │   │   ├── intermediate/
        │   │   │   └── {step_name}.json
        │   │   ├── subagents/
        │   │   │   └── {subagent_name}/
        │   │   └── loaded_data/  # Reporter용
        │   │       └── {agent_name}.json
        └── metadata.json

Usage:
    # 에이전트 run() 메서드에서
    debug_logger = AgentDebugLogger.get_logger(task_uuid, base_path, "agent_name")
    
    # 실행 추적 (예외 자동 로깅)
    with debug_logger.track_execution():
        # 요청 로깅
        debug_logger.log_request(context)
        
        try:
            # LLM 호출 로깅 (Context Manager)
            with debug_logger.track_llm_call() as llm_tracker:
                response = await self.llm.ainvoke(messages)
                llm_tracker.set_messages(messages)
                llm_tracker.set_response(response)
            
            # 중간 단계 로깅
            debug_logger.log_intermediate("step_name", data)
            
            # 서브에이전트 로깅
            subagent_logger = debug_logger.get_subagent_logger("subagent_name")
            subagent_logger.log_request(sub_request)
            subagent_logger.log_response(sub_response)
            
            # 최종 응답 로깅
            debug_logger.log_response(response)
            
        except Exception as e:
            # 수동 오류 로깅 (선택적 - track_execution이 자동으로도 로깅함)
            debug_logger.log_exception(
                e,
                context={"step": "processing", "input": input_data},
                step_name="data_processing"
            )
            raise
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class LLMCallMetadata:
    """LLM 호출 메타데이터"""
    call_id: str
    timestamp: str
    agent_name: str
    model_id: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    execution_time_ms: Optional[float] = None
    error: Optional[str] = None


class LLMCallTracker:
    """LLM 호출 추적 Context Manager (개선판)"""
    
    def __init__(self, debug_logger: 'AgentDebugLogger'):
        self.debug_logger = debug_logger
        self.call_id = None
        self.messages = None
        self.response = None
        self.start_time = None
        self.metadata: Optional[LLMCallMetadata] = None
        
        # 프롬프트 정보
        self.template_name: Optional[str] = None
        self.variables: Optional[Dict[str, Any]] = None
        self.system_prompt: Optional[str] = None
        self.user_prompt: Optional[str] = None
        
        # 응답 처리 정보
        self.raw_response: Optional[str] = None
        self.parsed_json: Optional[Dict[str, Any]] = None
        self.validated_model: Optional[Any] = None
        self.processing_error: Optional[str] = None
        
    def __enter__(self):
        self.call_id = self.debug_logger._get_next_call_id()
        self.start_time = datetime.now()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.messages and self.response:
            execution_time_ms = None
            if self.start_time:
                execution_time_ms = (datetime.now() - self.start_time).total_seconds() * 1000
            
            # 메타데이터 추출
            model_id = None
            input_tokens = None
            output_tokens = None
            
            if hasattr(self.response, 'response_metadata'):
                metadata = self.response.response_metadata
                if isinstance(metadata, dict):
                    usage = metadata.get("usage", {})
                    if isinstance(usage, dict):
                        input_tokens = usage.get("input_tokens")
                        output_tokens = usage.get("output_tokens")
                    model_id = metadata.get("model_id")
            
            self.metadata = LLMCallMetadata(
                call_id=self.call_id,
                timestamp=datetime.now().isoformat(),
                agent_name=self.debug_logger.agent_name,
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                execution_time_ms=execution_time_ms,
                error=str(exc_val) if exc_val else None
            )
            
            self.debug_logger._save_llm_call_enhanced(
                self.call_id,
                self.messages,
                self.response,
                self.metadata,
                template_name=self.template_name,
                variables=self.variables,
                system_prompt=self.system_prompt,
                user_prompt=self.user_prompt,
                raw_response=self.raw_response,
                parsed_json=self.parsed_json,
                validated_model=self.validated_model,
                processing_error=self.processing_error,
            )
        
        return False  # 예외를 다시 발생시킴
    
    def log_prompts(
        self,
        template_name: str,
        variables: Dict[str, Any],
        system_prompt: str,
        user_prompt: str,
    ):
        """
        프롬프트 생성 정보 로깅
        
        Args:
            template_name: 프롬프트 템플릿 이름 (예: "security_agent")
            variables: 프롬프트 변수 딕셔너리
            system_prompt: 최종 System Prompt
            user_prompt: 최종 User Prompt
        """
        self.template_name = template_name
        self.variables = variables
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
    
    def log_response_stages(
        self,
        raw: str,
        parsed: Optional[Dict[str, Any]] = None,
        validated: Optional[Any] = None,
        error: Optional[str] = None,
    ):
        """
        LLM 응답 처리 단계별 로깅
        
        Args:
            raw: LLM 원본 응답
            parsed: JSON 파싱 결과
            validated: Pydantic 검증 결과
            error: 에러 메시지 (있는 경우)
        """
        self.raw_response = raw
        self.parsed_json = parsed
        self.validated_model = validated
        self.processing_error = error
    
    def set_messages(self, messages: List[Any]):
        """LLM 호출 메시지 설정"""
        self.messages = messages
        
    def set_response(self, response: Any):
        """LLM 응답 설정"""
        self.response = response


class AgentDebugLogger:
    """
    에이전트 디버깅 로그를 구조화하여 저장하는 클래스
    
    TokenTracker와 유사한 패턴으로 사용:
    - 싱글톤 패턴 (에이전트별 인스턴스)
    - Context Manager로 자동 로깅
    - 최소한의 코드 변경으로 적용
    - 서브 에이전트 로깅 지원 (환경 변수로 제어)
    """
    
    _loggers: Dict[str, 'AgentDebugLogger'] = {}
    _enabled: Optional[bool] = None
    _subagent_enabled: Optional[bool] = None
    
    def __init__(self, task_uuid: str, base_path: Path, agent_name: str, is_subagent: bool = False):
        """
        AgentDebugLogger 초기화
        
        Args:
            task_uuid: 작업 고유 UUID
            base_path: 작업 기본 경로 (예: Path("./data/analyze/{task_uuid}"))
            agent_name: 에이전트 이름 (예: "user_skill_profiler", "reporter")
            is_subagent: 서브 에이전트 여부 (기본값: False)
        """
        self.task_uuid = task_uuid
        self.base_path = Path(base_path)
        self.agent_name = agent_name
        self.is_subagent = is_subagent
        
        # 디버그 디렉토리: data/analyze/{task_uuid}/debug/agents/{agent_name}
        self.debug_dir = self.base_path / "debug" / "agents" / agent_name
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        
        # 하위 디렉토리 생성
        (self.debug_dir / "llm_calls").mkdir(exist_ok=True)
        (self.debug_dir / "intermediate").mkdir(exist_ok=True)
        (self.debug_dir / "subagents").mkdir(exist_ok=True)
        (self.debug_dir / "loaded_data").mkdir(exist_ok=True)
        (self.debug_dir / "errors").mkdir(exist_ok=True)  # ✅ 오류 로그 디렉토리
        
        self.llm_call_counter = 0
        self.error_counter = 0  # ✅ 오류 카운터
        self.start_time = None
        self.errors_summary = []  # ✅ 오류 요약 리스트
        
        logger.debug(f"🔍 AgentDebugLogger 초기화: {self.debug_dir} (서브에이전트: {is_subagent})")
    
    @classmethod
    def is_enabled(cls) -> bool:
        """디버깅 로깅 활성화 여부 확인"""
        if cls._enabled is None:
            # 환경 변수 확인 (기본값: True)
            cls._enabled = os.getenv("ENABLE_DEBUG_LOGGING", "true").lower() == "true"
        return cls._enabled
    
    @classmethod
    def is_subagent_enabled(cls) -> bool:
        """서브 에이전트 디버깅 로깅 활성화 여부 확인"""
        if cls._subagent_enabled is None:
            # 환경 변수 확인 (기본값: False - 성능을 위해)
            cls._subagent_enabled = os.getenv("ENABLE_SUBAGENT_DEBUG_LOGGING", "false").lower() == "true"
        return cls._subagent_enabled
    
    @classmethod
    def get_logger(cls, task_uuid: str, base_path: str | Path, agent_name: str, is_subagent: bool = False) -> 'AgentDebugLogger':
        """
        에이전트별 로거 인스턴스 가져오기 (싱글톤)
        
        Args:
            task_uuid: 작업 고유 UUID
            base_path: 작업 기본 경로
            agent_name: 에이전트 이름
            is_subagent: 서브 에이전트 여부 (기본값: False)
            
        Returns:
            AgentDebugLogger 인스턴스 (비활성화 시 DummyDebugLogger)
        """
        # 메인 에이전트는 ENABLE_DEBUG_LOGGING으로 제어
        if not is_subagent and not cls.is_enabled():
            return DummyDebugLogger()
        
        # 서브 에이전트는 ENABLE_SUBAGENT_DEBUG_LOGGING으로 제어
        if is_subagent and not cls.is_subagent_enabled():
            return DummyDebugLogger()
        
        key = f"{task_uuid}:{agent_name}"
        if key not in cls._loggers:
            cls._loggers[key] = cls(task_uuid, base_path, agent_name, is_subagent)
        return cls._loggers[key]
    
    @contextmanager
    def track_execution(self):
        """에이전트 실행 시간 추적 Context Manager (예외 자동 로깅)"""
        import traceback
        
        self.start_time = datetime.now()
        error_occurred = False
        error_info = None
        
        try:
            yield
        except Exception as e:
            error_occurred = True
            error_info = e
            # 자동으로 오류 로깅
            try:
                traceback_str = traceback.format_exc()
                self.log_exception(e, traceback_str=traceback_str, step_name="agent_execution")
            except Exception as log_error:
                # 로깅 실패 시에도 원래 예외를 유지
                logger.warning(f"⚠️ 오류 로깅 실패 ({self.agent_name}): {log_error}")
            raise  # 예외를 다시 발생시킴
        finally:
            execution_time = None
            if self.start_time:
                execution_time = (datetime.now() - self.start_time).total_seconds() * 1000
            
            # 메타데이터 저장 (에러 정보 포함)
            metadata = {
                "agent_name": self.agent_name,
                "task_uuid": self.task_uuid,
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "end_time": datetime.now().isoformat(),
                "execution_time_ms": execution_time,
                "llm_call_count": self.llm_call_counter,
                "error_count": self.error_counter,  # ✅ 에러 카운트 추가
                "has_errors": error_occurred,  # ✅ 에러 발생 여부
                "last_error_type": type(error_info).__name__ if error_info else None,  # ✅ 마지막 에러 타입
            }
            
            metadata_path = self.debug_dir / "metadata.json"
            try:
                metadata_path.write_text(
                    json.dumps(metadata, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
            except Exception as e:
                logger.warning(f"⚠️ 메타데이터 저장 실패 ({self.agent_name}): {e}")
            
            # 에러 요약 저장
            if self.errors_summary:
                try:
                    self._save_errors_summary()
                except Exception as e:
                    logger.warning(f"⚠️ 에러 요약 저장 실패 ({self.agent_name}): {e}")
    
    def track_llm_call(self) -> LLMCallTracker:
        """LLM 호출 추적 Context Manager"""
        return LLMCallTracker(self)
    
    def log_request(self, context: Any):
        """
        에이전트 요청(Context) 로깅
        
        Args:
            context: 에이전트 Context 객체 (Pydantic 모델 또는 dict)
        """
        try:
            if hasattr(context, 'model_dump'):
                # Pydantic 모델
                data = context.model_dump()
            elif hasattr(context, 'dict'):
                # Pydantic 모델 (구버전)
                data = context.dict()
            elif isinstance(context, dict):
                data = context
            else:
                data = {"raw": str(context)}
            
            request_data = {
                "timestamp": datetime.now().isoformat(),
                "agent_name": self.agent_name,
                "task_uuid": self.task_uuid,
                "context": data,
            }
            
            request_path = self.debug_dir / "request.json"
            request_path.write_text(
                json.dumps(request_data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8"
            )
            
            logger.debug(f"🔍 디버그 로그 저장: {request_path}")
            
        except Exception as e:
            logger.warning(f"⚠️ 요청 로깅 실패 ({self.agent_name}): {e}")
    
    def log_response(self, response: Any):
        """
        에이전트 응답(Response) 로깅
        
        Args:
            response: 에이전트 Response 객체 (Pydantic 모델 또는 dict)
        """
        try:
            if hasattr(response, 'model_dump'):
                # Pydantic 모델
                data = response.model_dump()
            elif hasattr(response, 'dict'):
                # Pydantic 모델 (구버전)
                data = response.dict()
            elif isinstance(response, dict):
                data = response
            else:
                data = {"raw": str(response)}
            
            response_data = {
                "timestamp": datetime.now().isoformat(),
                "agent_name": self.agent_name,
                "task_uuid": self.task_uuid,
                "response": data,
            }
            
            response_path = self.debug_dir / "response.json"
            response_path.write_text(
                json.dumps(response_data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8"
            )
            
            logger.debug(f"🔍 디버그 로그 저장: {response_path}")
            
        except Exception as e:
            logger.warning(f"⚠️ 응답 로깅 실패 ({self.agent_name}): {e}")
    
    def log_intermediate(self, step_name: str, data: Any):
        """
        중간 단계 데이터 로깅
        
        Args:
            step_name: 단계 이름 (파일명으로 사용)
            data: 로깅할 데이터
        """
        try:
            if hasattr(data, 'model_dump'):
                data_dict = data.model_dump()
            elif hasattr(data, 'dict'):
                data_dict = data.dict()
            elif isinstance(data, dict):
                data_dict = data
            else:
                data_dict = {"raw": str(data)}
            
            intermediate_data = {
                "timestamp": datetime.now().isoformat(),
                "step_name": step_name,
                "agent_name": self.agent_name,
                "data": data_dict,
            }
            
            # 파일명에서 특수문자 제거
            safe_step_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in step_name)
            intermediate_path = self.debug_dir / "intermediate" / f"{safe_step_name}.json"
            intermediate_path.write_text(
                json.dumps(intermediate_data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8"
            )
            
            logger.debug(f"🔍 중간 단계 로그 저장: {intermediate_path}")
            
        except Exception as e:
            logger.warning(f"⚠️ 중간 단계 로깅 실패 ({self.agent_name}/{step_name}): {e}")
    
    def get_subagent_logger(self, subagent_name: str) -> 'AgentDebugLogger':
        """
        서브에이전트 로거 가져오기
        
        서브 에이전트는 부모 에이전트의 subagents/ 디렉토리 아래에 위치합니다.
        예: debug/agents/user_skill_profiler/subagents/code_batch_processor_batch_0/
        
        Args:
            subagent_name: 서브에이전트 이름 (예: "code_batch_processor_batch_0")
            
        Returns:
            AgentDebugLogger 인스턴스 (서브에이전트용)
        """
        # 서브 에이전트 로깅이 비활성화되어 있으면 더미 로거 반환
        if not AgentDebugLogger.is_subagent_enabled():
            return DummyDebugLogger()
        
        # 서브에이전트 경로: {parent_debug_dir}/subagents/{subagent_name}
        subagent_path = self.debug_dir / "subagents" / subagent_name
        subagent_logger = AgentDebugLogger(
            self.task_uuid,
            self.base_path,
            f"{self.agent_name}/subagents/{subagent_name}",
            is_subagent=True
        )
        # 서브에이전트 디렉토리로 변경
        subagent_logger.debug_dir = subagent_path
        subagent_logger.debug_dir.mkdir(parents=True, exist_ok=True)
        (subagent_logger.debug_dir / "llm_calls").mkdir(exist_ok=True)
        (subagent_logger.debug_dir / "intermediate").mkdir(exist_ok=True)
        (subagent_logger.debug_dir / "errors").mkdir(exist_ok=True)  # ✅ 서브에이전트도 errors 디렉토리 생성
        
        return subagent_logger
    
    def log_loaded_data(self, agent_name: str, data: Any, error: Optional[str] = None):
        """
        ResultStore에서 로드한 데이터 로깅 (Reporter용)
        
        Args:
            agent_name: 로드한 에이전트 이름
            data: 로드한 데이터 (None이면 로드 실패)
            error: 에러 메시지 (있는 경우)
        """
        try:
            loaded_data = {
                "timestamp": datetime.now().isoformat(),
                "loaded_by": self.agent_name,
                "source_agent": agent_name,
                "load_success": data is not None,
                "error": error,
            }
            
            if data is not None:
                if hasattr(data, 'model_dump'):
                    loaded_data["data"] = data.model_dump()
                elif hasattr(data, 'dict'):
                    loaded_data["data"] = data.dict()
                elif isinstance(data, dict):
                    loaded_data["data"] = data
                else:
                    loaded_data["data"] = {"raw": str(data)}
            
            loaded_path = self.debug_dir / "loaded_data" / f"{agent_name}.json"
            loaded_path.write_text(
                json.dumps(loaded_data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8"
            )
            
            logger.debug(f"🔍 로드 데이터 로그 저장: {loaded_path}")
            
        except Exception as e:
            logger.warning(f"⚠️ 로드 데이터 로깅 실패 ({self.agent_name}/{agent_name}): {e}")
    
    def log_error(
        self,
        error: Exception | str,
        context: Optional[Dict[str, Any]] = None,
        traceback_str: Optional[str] = None,
        step_name: Optional[str] = None,
    ):
        """
        에러 로깅 (일반)
        
        Args:
            error: Exception 객체 또는 에러 메시지 문자열
            context: 에러 발생 시점의 컨텍스트 정보
            traceback_str: 트레이스백 문자열
            step_name: 에러가 발생한 단계 이름
        """
        import traceback
        
        try:
            # 에러 정보 추출
            if isinstance(error, Exception):
                error_type = type(error).__name__
                error_message = str(error)
                if traceback_str is None:
                    traceback_str = traceback.format_exc()
            else:
                error_type = "Error"
                error_message = str(error)
                if traceback_str is None:
                    traceback_str = None
            
            self._save_error_log(
                error_type=error_type,
                error_message=error_message,
                traceback_str=traceback_str,
                context=context,
                step_name=step_name,
            )
            
        except Exception as e:
            logger.warning(f"⚠️ 에러 로깅 실패 ({self.agent_name}): {e}")
    
    def log_exception(
        self,
        exception: Exception,
        context: Optional[Dict[str, Any]] = None,
        traceback_str: Optional[str] = None,
        step_name: Optional[str] = None,
    ):
        """
        예외 로깅 (Exception 객체 전용, 트레이스백 포함)
        
        Args:
            exception: Exception 객체
            context: 예외 발생 시점의 컨텍스트 정보
            traceback_str: 트레이스백 문자열 (없으면 자동 생성)
            step_name: 예외가 발생한 단계 이름
        """
        import traceback
        
        try:
            error_type = type(exception).__name__
            error_message = str(exception)
            
            if traceback_str is None:
                traceback_str = traceback.format_exc()
            
            self._save_error_log(
                error_type=error_type,
                error_message=error_message,
                traceback_str=traceback_str,
                context=context,
                step_name=step_name,
            )
            
        except Exception as e:
            logger.warning(f"⚠️ 예외 로깅 실패 ({self.agent_name}): {e}")
    
    def _save_error_log(
        self,
        error_type: str,
        error_message: str,
        traceback_str: Optional[str],
        context: Optional[Dict[str, Any]],
        step_name: Optional[str],
    ):
        """에러 로그 파일 저장 (내부 메서드)"""
        try:
            self.error_counter += 1
            error_id = f"error_{self.error_counter:03d}"
            timestamp = datetime.now().isoformat()
            
            # 실행 시간 계산
            execution_time_ms = None
            if self.start_time:
                execution_time_ms = (datetime.now() - self.start_time).total_seconds() * 1000
            
            # 에러 로그 데이터
            error_data = {
                "error_id": error_id,
                "timestamp": timestamp,
                "agent_name": self.agent_name,
                "task_uuid": self.task_uuid,
                "error_type": error_type,
                "error_message": error_message,
                "step_name": step_name,
                "context": context or {},
                "traceback": traceback_str,
                "execution_time_ms": execution_time_ms,
                "llm_call_count": self.llm_call_counter,
            }
            
            # 에러 로그 파일 저장
            error_path = self.debug_dir / "errors" / f"{error_id}.json"
            error_path.write_text(
                json.dumps(error_data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8"
            )
            
            # 에러 요약에 추가
            self.errors_summary.append({
                "error_id": error_id,
                "timestamp": timestamp,
                "error_type": error_type,
                "error_message": error_message[:200],  # 메시지 길이 제한
                "step_name": step_name,
            })
            
            logger.error(f"❌ 에러 로그 저장: {error_path} ({error_type}: {error_message[:100]})")
            
        except Exception as e:
            # 에러 로깅 실패 시에도 원래 에러 정보를 로거에 기록
            logger.error(f"❌ 에러 로그 저장 실패 ({self.agent_name}): {e}")
    
    def _save_errors_summary(self):
        """에러 요약 파일 저장"""
        try:
            if not self.errors_summary:
                return
            
            # 에러 타입별 통계
            errors_by_type = {}
            errors_by_step = {}
            
            for error in self.errors_summary:
                error_type = error["error_type"]
                step_name = error.get("step_name", "unknown")
                
                errors_by_type[error_type] = errors_by_type.get(error_type, 0) + 1
                errors_by_step[step_name] = errors_by_step.get(step_name, 0) + 1
            
            summary_data = {
                "total_errors": len(self.errors_summary),
                "errors_by_type": errors_by_type,
                "errors_by_step": errors_by_step,
                "first_error": self.errors_summary[0]["timestamp"] if self.errors_summary else None,
                "last_error": self.errors_summary[-1]["timestamp"] if self.errors_summary else None,
                "errors": self.errors_summary,  # 모든 에러 요약
            }
            
            summary_path = self.debug_dir / "errors" / "errors_summary.json"
            summary_path.write_text(
                json.dumps(summary_data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8"
            )
            
            logger.debug(f"🔍 에러 요약 저장: {summary_path}")
            
        except Exception as e:
            logger.warning(f"⚠️ 에러 요약 저장 실패 ({self.agent_name}): {e}")
    
    def _get_next_call_id(self) -> str:
        """다음 LLM 호출 ID 생성"""
        self.llm_call_counter += 1
        return f"call_{self.llm_call_counter:03d}"
    
    def _save_llm_call_enhanced(
        self,
        call_id: str,
        messages: List[Any],
        response: Any,
        metadata: LLMCallMetadata,
        template_name: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        raw_response: Optional[str] = None,
        parsed_json: Optional[Dict[str, Any]] = None,
        validated_model: Optional[Any] = None,
        processing_error: Optional[str] = None,
    ):
        """
        LLM 호출 상세 정보 저장 (개선판)
        
        디렉토리 구조:
            llm_calls/call_001/
                ├── 01_prompt_template_info.json
                ├── 02_prompt_variables.json
                ├── 03_system_prompt.txt
                ├── 04_user_prompt.txt
                ├── 05_llm_request.json
                ├── 06_llm_response_raw.txt
                ├── 07_llm_response_parsed.json
                ├── 08_pydantic_validated.json
                ├── 09_metadata.json
                └── summary.md
        
        Args:
            call_id: 호출 ID
            messages: LLM 입력 메시지 리스트
            response: LLM 응답 객체
            metadata: 메타데이터
            template_name: 프롬프트 템플릿 이름
            variables: 프롬프트 변수
            system_prompt: 최종 System Prompt
            user_prompt: 최종 User Prompt
            raw_response: LLM 원본 응답
            parsed_json: JSON 파싱 결과
            validated_model: Pydantic 검증 결과
            processing_error: 처리 에러
        """
        try:
            # call_id 디렉토리 생성
            call_dir = self.debug_dir / "llm_calls" / call_id
            call_dir.mkdir(parents=True, exist_ok=True)
            
            # 01. 프롬프트 템플릿 정보
            if template_name:
                template_info = {
                    "template_name": template_name,
                    "agent_name": self.agent_name,
                    "call_id": call_id,
                }
                self._write_json(
                    call_dir / "01_prompt_template_info.json",
                    template_info
                )
            
            # 02. 프롬프트 변수
            if variables:
                self._write_json(
                    call_dir / "02_prompt_variables.json",
                    variables
                )
            
            # 03. System Prompt (TXT)
            if system_prompt:
                self._write_text(
                    call_dir / "03_system_prompt.txt",
                    system_prompt
                )
            
            # 04. User Prompt (TXT)
            if user_prompt:
                self._write_text(
                    call_dir / "04_user_prompt.txt",
                    user_prompt
                )
            
            # 05. LLM Request (JSON)
            request_data = {
                "call_id": call_id,
                "timestamp": metadata.timestamp,
                "agent_name": self.agent_name,
                "model_id": metadata.model_id,
                "messages": self._serialize_messages(messages),
            }
            self._write_json(
                call_dir / "05_llm_request.json",
                request_data
            )
            
            # 06. LLM Response Raw (TXT)
            response_content = raw_response
            if response_content is None:
                if hasattr(response, 'content'):
                    response_content = response.content
                elif isinstance(response, str):
                    response_content = response
                else:
                    response_content = str(response)
            
            self._write_text(
                call_dir / "06_llm_response_raw.txt",
                response_content
            )
            
            # 07. LLM Response Parsed (JSON)
            if parsed_json is not None:
                self._write_json(
                    call_dir / "07_llm_response_parsed.json",
                    parsed_json
                )
            elif response_content:
                # 자동 파싱 시도
                auto_parsed = self._try_parse_json(response_content)
                if auto_parsed:
                    self._write_json(
                        call_dir / "07_llm_response_parsed.json",
                        auto_parsed
                    )
            
            # 08. Pydantic Validated (JSON)
            if validated_model is not None:
                if hasattr(validated_model, 'model_dump'):
                    validated_data = validated_model.model_dump()
                elif hasattr(validated_model, 'dict'):
                    validated_data = validated_model.dict()
                elif isinstance(validated_model, dict):
                    validated_data = validated_model
                else:
                    validated_data = {"raw": str(validated_model)}
                
                self._write_json(
                    call_dir / "08_pydantic_validated.json",
                    validated_data
                )
            
            # 09. Metadata (JSON)
            metadata_dict = asdict(metadata)
            if processing_error:
                metadata_dict["processing_error"] = processing_error
            
            self._write_json(
                call_dir / "09_metadata.json",
                metadata_dict
            )
            
            # 10. Summary (Markdown)
            summary_md = self._generate_summary_md(
                call_id=call_id,
                metadata=metadata,
                template_name=template_name,
                variables=variables,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_content=response_content,
                parsed_json=parsed_json,
                validated_model=validated_model,
                processing_error=processing_error,
            )
            self._write_text(
                call_dir / "summary.md",
                summary_md
            )
            
            logger.debug(f"🔍 LLM 호출 로그 저장 완료: {call_id} → {call_dir}")
            
        except Exception as e:
            logger.warning(f"⚠️ LLM 호출 로깅 실패 ({self.agent_name}/{call_id}): {e}")
    
    def _generate_summary_md(
        self,
        call_id: str,
        metadata: LLMCallMetadata,
        template_name: Optional[str],
        variables: Optional[Dict[str, Any]],
        system_prompt: Optional[str],
        user_prompt: Optional[str],
        response_content: Optional[str],
        parsed_json: Optional[Dict[str, Any]],
        validated_model: Optional[Any],
        processing_error: Optional[str],
    ) -> str:
        """사람이 읽기 쉬운 요약 Markdown 생성"""
        
        lines = []
        lines.append(f"# LLM Call: {call_id}")
        lines.append("")
        
        # 기본 정보
        lines.append("## 기본 정보")
        lines.append(f"- **Agent**: `{self.agent_name}`")
        lines.append(f"- **Timestamp**: {metadata.timestamp}")
        lines.append(f"- **Model**: `{metadata.model_id or 'N/A'}`")
        lines.append(f"- **Execution Time**: {metadata.execution_time_ms:.2f}ms" if metadata.execution_time_ms else "- **Execution Time**: N/A")
        lines.append("")
        
        # 프롬프트 변수
        if variables:
            lines.append("## 프롬프트 변수")
            lines.append("```yaml")
            for key, value in variables.items():
                # 긴 값은 잘라서 표시
                if isinstance(value, str) and len(value) > 100:
                    value_str = value[:100] + "..."
                else:
                    value_str = str(value)
                lines.append(f"{key}: {value_str}")
            lines.append("```")
            lines.append("")
        
        # System Prompt
        if system_prompt:
            lines.append("## System Prompt")
            lines.append("```")
            # 첫 200자만 표시
            preview = system_prompt[:200] + "..." if len(system_prompt) > 200 else system_prompt
            lines.append(preview)
            lines.append("```")
            lines.append("*(전체: 03_system_prompt.txt 참조)*")
            lines.append("")
        
        # User Prompt
        if user_prompt:
            lines.append("## User Prompt")
            lines.append("```")
            # 첫 300자만 표시
            preview = user_prompt[:300] + "..." if len(user_prompt) > 300 else user_prompt
            lines.append(preview)
            lines.append("```")
            lines.append("*(전체: 04_user_prompt.txt 참조)*")
            lines.append("")
        
        # LLM 응답
        if parsed_json:
            lines.append("## LLM 응답 (파싱됨)")
            lines.append("```json")
            json_str = json.dumps(parsed_json, indent=2, ensure_ascii=False)
            # 첫 500자만 표시
            preview = json_str[:500] + "\n..." if len(json_str) > 500 else json_str
            lines.append(preview)
            lines.append("```")
            lines.append("*(전체: 07_llm_response_parsed.json 참조)*")
            lines.append("")
        elif response_content:
            lines.append("## LLM 응답 (원본)")
            lines.append("```")
            # 첫 300자만 표시
            preview = response_content[:300] + "..." if len(response_content) > 300 else response_content
            lines.append(preview)
            lines.append("```")
            lines.append("*(전체: 06_llm_response_raw.txt 참조)*")
            lines.append("")
        
        # 토큰 사용량
        lines.append("## 토큰 사용량")
        if metadata.input_tokens and metadata.output_tokens:
            total_tokens = metadata.input_tokens + metadata.output_tokens
            # 가격 계산 (예시: Sonnet 기준)
            input_cost = (metadata.input_tokens / 1_000_000) * 3.0
            output_cost = (metadata.output_tokens / 1_000_000) * 15.0
            total_cost = input_cost + output_cost
            
            lines.append(f"- **Input**: {metadata.input_tokens:,} tokens")
            lines.append(f"- **Output**: {metadata.output_tokens:,} tokens")
            lines.append(f"- **Total**: {total_tokens:,} tokens")
            lines.append(f"- **Est. Cost**: ${total_cost:.4f}")
        else:
            lines.append("- *토큰 정보 없음*")
        lines.append("")
        
        # 상태
        lines.append("## 상태")
        if metadata.error:
            lines.append(f"❌ **에러 발생**: {metadata.error}")
        elif processing_error:
            lines.append(f"⚠️ **처리 에러**: {processing_error}")
        elif validated_model:
            lines.append("✅ **성공**")
            lines.append("- JSON 파싱: 성공")
            lines.append("- Pydantic 검증: 성공")
        elif parsed_json:
            lines.append("⚠️ **부분 성공**")
            lines.append("- JSON 파싱: 성공")
            lines.append("- Pydantic 검증: 미수행 또는 실패")
        else:
            lines.append("⚠️ **파싱 필요**")
            lines.append("- JSON 파싱이 수행되지 않음")
        lines.append("")
        
        # 파일 참조
        lines.append("## 상세 파일")
        lines.append("- `01_prompt_template_info.json` - 템플릿 정보")
        lines.append("- `02_prompt_variables.json` - 변수 매핑")
        lines.append("- `03_system_prompt.txt` - System Prompt 전체")
        lines.append("- `04_user_prompt.txt` - User Prompt 전체")
        lines.append("- `05_llm_request.json` - LangChain 요청 구조")
        lines.append("- `06_llm_response_raw.txt` - LLM 원본 응답")
        lines.append("- `07_llm_response_parsed.json` - JSON 파싱 결과")
        lines.append("- `08_pydantic_validated.json` - Pydantic 검증 결과")
        lines.append("- `09_metadata.json` - 메타데이터 (토큰, 시간 등)")
        lines.append("")
        
        return "\n".join(lines)
    
    def _write_text(self, path: Path, content: str):
        """텍스트 파일 저장"""
        path.write_text(content, encoding="utf-8")
    
    def _write_json(self, path: Path, data: Any):
        """JSON 파일 저장"""
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8"
        )
    
    def _serialize_messages(self, messages: List[Any]) -> List[Dict[str, Any]]:
        """LangChain 메시지를 직렬화 가능한 형태로 변환"""
        result = []
        for msg in messages:
            if hasattr(msg, 'content'):
                result.append({
                    "type": type(msg).__name__,
                    "content": msg.content,
                })
            elif isinstance(msg, dict):
                result.append(msg)
            else:
                result.append({"raw": str(msg)})
        return result
    
    def _try_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """텍스트에서 JSON 파싱 시도"""
        import re
        
        # JSON 코드 블록 찾기
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except:
                pass
        
        # 직접 JSON 파싱 시도
        try:
            return json.loads(text)
        except:
            pass
        
        return None


class DummyDebugLogger:
    """디버깅 비활성화 시 사용하는 더미 로거"""
    
    def log_request(self, *args, **kwargs):
        pass
    
    def log_response(self, *args, **kwargs):
        pass
    
    def log_intermediate(self, *args, **kwargs):
        pass
    
    def get_subagent_logger(self, *args, **kwargs):
        return self
    
    def log_loaded_data(self, *args, **kwargs):
        pass
    
    def log_error(self, *args, **kwargs):
        """에러 로깅 (더미 - 아무것도 하지 않음)"""
        pass
    
    def log_exception(self, *args, **kwargs):
        """예외 로깅 (더미 - 아무것도 하지 않음)"""
        pass
    
    def track_llm_call(self):
        return self
    
    def track_execution(self):
        return self
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass
    
    def set_messages(self, *args):
        pass
    
    def set_response(self, *args):
        pass
    
    def log_prompts(self, *args, **kwargs):
        pass
    
    def log_response_stages(self, *args, **kwargs):
        pass

