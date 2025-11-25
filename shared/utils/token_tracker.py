"""
Token Usage Tracker for Deep Agents

에이전트별 토큰 사용량 및 요금 추적 유틸리티
"""

import logging
from typing import Dict, Optional, Any
from contextlib import contextmanager
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """토큰 사용량 정보"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    call_count: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    def add_usage(self, input_tokens: int, output_tokens: int, cost: float):
        """토큰 사용량 추가"""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens
        self.cost += cost
        self.call_count += 1

    def get_duration(self) -> Optional[float]:
        """실행 시간 (초)"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class TokenTracker:
    """
    에이전트별 토큰 사용량 및 요금 추적 클래스 (싱글톤)
    
    Usage:
        # Context Manager 사용 (권장)
        with TokenTracker.track("security_agent"):
            response = await llm.ainvoke(messages)
            TokenTracker.record_usage("security_agent", response)
        
        # 전체 집계 출력
        TokenTracker.print_summary()
    """

    # 모델별 가격 정보 (USD per 1M tokens)
    # AWS Bedrock Claude 3.5 Sonnet 가격 (2024 기준)
    MODEL_PRICING = {
        "us.anthropic.claude-3-5-sonnet-20241022-v2:0": {
            "input": 3.00,   # $3.00 per 1M input tokens
            "output": 15.00, # $15.00 per 1M output tokens
        },
        "anthropic.claude-3-5-sonnet-20241022-v2:0": {
            "input": 3.00,
            "output": 15.00,
        },
        "anthropic.claude-3-5-sonnet-20241022-v2": {
            "input": 3.00,
            "output": 15.00,
        },
        # 기본값 (Claude 3.5 Sonnet)
        "default": {
            "input": 3.00,
            "output": 15.00,
        }
    }

    _instance: Optional['TokenTracker'] = None
    _usage: Dict[str, TokenUsage] = field(default_factory=dict)
    _active_agents: Dict[str, datetime] = field(default_factory=dict)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._usage = {}
            cls._instance._active_agents = {}
        return cls._instance

    @classmethod
    def track(cls, agent_name: str):
        """
        Context Manager로 에이전트 실행 추적
        
        Args:
            agent_name: 에이전트 이름
            
        Example:
            with TokenTracker.track("security_agent"):
                response = await llm.ainvoke(messages)
                TokenTracker.record_usage("security_agent", response)
        """
        return cls._TrackContext(agent_name)

    class _TrackContext:
        """Context Manager 내부 클래스"""
        def __init__(self, agent_name: str):
            self.agent_name = agent_name
            self.tracker = TokenTracker()

        def __enter__(self):
            self.tracker.start_agent(self.agent_name)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.tracker.end_agent(self.agent_name)
            return False

    def start_agent(self, agent_name: str):
        """에이전트 실행 시작"""
        if agent_name not in self._usage:
            self._usage[agent_name] = TokenUsage()
        self._usage[agent_name].start_time = datetime.now()
        self._active_agents[agent_name] = datetime.now()
        logger.debug(f"🔍 TokenTracker: {agent_name} 시작")

    def end_agent(self, agent_name: str):
        """에이전트 실행 종료"""
        if agent_name in self._usage:
            self._usage[agent_name].end_time = datetime.now()
        if agent_name in self._active_agents:
            del self._active_agents[agent_name]
        logger.debug(f"🔍 TokenTracker: {agent_name} 종료")

    @classmethod
    def record_usage(
        cls,
        agent_name: str,
        response: Any,
        model_id: Optional[str] = None
    ):
        """
        LLM 응답에서 토큰 사용량 기록
        
        Args:
            agent_name: 에이전트 이름
            response: LangChain LLM 응답 객체
            model_id: 모델 ID (자동 감지 실패 시)
        """
        instance = cls()
        
        # 토큰 사용량 추출
        input_tokens, output_tokens = instance._extract_usage(response, model_id)
        
        # 요금 계산
        cost = instance._calculate_cost(input_tokens, output_tokens, model_id)
        
        # 기록
        if agent_name not in instance._usage:
            instance._usage[agent_name] = TokenUsage()
        
        instance._usage[agent_name].add_usage(input_tokens, output_tokens, cost)
        
        logger.debug(
            f"💰 {agent_name}: 입력={input_tokens}, 출력={output_tokens}, "
            f"총={input_tokens + output_tokens}, 비용=${cost:.6f}"
        )

    def _extract_usage(self, response: Any, model_id: Optional[str] = None) -> tuple[int, int]:
        """
        LLM 응답에서 토큰 사용량 추출
        
        Returns:
            (input_tokens, output_tokens)
        """
        input_tokens = 0
        output_tokens = 0

        try:
            # 방법 1: response_metadata에서 추출 (AWS Bedrock Converse API)
            if hasattr(response, 'response_metadata'):
                metadata = response.response_metadata
                if metadata:
                    # AWS Bedrock Converse API 응답 형식
                    usage = metadata.get('usage', {})
                    if usage:
                        input_tokens = usage.get('input_tokens', 0)
                        output_tokens = usage.get('output_tokens', 0)
                        if input_tokens > 0 or output_tokens > 0:
                            return input_tokens, output_tokens
                    
                    # 추가 확인: 다른 형식의 usage 정보
                    if 'input_tokens' in metadata:
                        input_tokens = metadata.get('input_tokens', 0)
                        output_tokens = metadata.get('output_tokens', 0)
                        if input_tokens > 0 or output_tokens > 0:
                            return input_tokens, output_tokens

            # 방법 2: usage_metadata에서 추출
            if hasattr(response, 'usage_metadata'):
                usage = response.usage_metadata
                if usage:
                    input_tokens = getattr(usage, 'input_tokens', 0) or 0
                    output_tokens = getattr(usage, 'output_tokens', 0) or 0
                    if input_tokens > 0 or output_tokens > 0:
                        return input_tokens, output_tokens

            # 방법 3: response 객체의 속성에서 직접 추출
            if hasattr(response, 'input_tokens') and hasattr(response, 'output_tokens'):
                input_tokens = response.input_tokens or 0
                output_tokens = response.output_tokens or 0
                if input_tokens > 0 or output_tokens > 0:
                    return input_tokens, output_tokens

            # 방법 4: 대략적 추정 (content 길이 기반)
            # Claude 모델: 대략 1 token ≈ 4 characters
            if hasattr(response, 'content'):
                content = response.content or ""
                # 입력은 추정 불가 (messages 필요), 출력만 추정
                output_tokens = len(content) // 4
                # 추정 사용은 정상적인 경우이므로 DEBUG 레벨로 변경
                logger.debug(
                    f"⚠️ TokenTracker: 정확한 토큰 정보 없음, 출력 토큰 추정 사용 "
                    f"(출력={output_tokens}, content_length={len(content)})"
                )
                return 0, output_tokens

        except Exception as e:
            logger.warning(f"⚠️ TokenTracker: 토큰 추출 실패 - {e}")

        return input_tokens, output_tokens

    def _calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model_id: Optional[str] = None
    ) -> float:
        """
        토큰 사용량 기반 요금 계산
        
        Args:
            input_tokens: 입력 토큰 수
            output_tokens: 출력 토큰 수
            model_id: 모델 ID
            
        Returns:
            계산된 요금 (USD)
        """
        # 모델별 가격 정보 가져오기
        pricing = self.MODEL_PRICING.get(model_id) or self.MODEL_PRICING.get("default")
        
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        
        return input_cost + output_cost

    @classmethod
    def get_usage(cls, agent_name: str) -> Optional[TokenUsage]:
        """에이전트별 토큰 사용량 조회"""
        instance = cls()
        return instance._usage.get(agent_name)

    @classmethod
    def print_summary(cls, agent_name: Optional[str] = None):
        """
        토큰 사용량 요약 출력
        
        Args:
            agent_name: 특정 에이전트만 출력 (None이면 전체)
        """
        instance = cls()
        
        if agent_name:
            # 특정 에이전트만 출력
            usage = instance._usage.get(agent_name)
            if usage:
                cls._print_agent_summary(agent_name, usage)
        else:
            # 전체 요약 출력
            if not instance._usage:
                logger.info("💰 TokenTracker: 기록된 토큰 사용량 없음")
                return

            # 에이전트별 요약
            for agent_name, usage in instance._usage.items():
                cls._print_agent_summary(agent_name, usage)

            # 전체 집계
            cls._print_total_summary(instance._usage)

    @staticmethod
    def _print_agent_summary(agent_name: str, usage: TokenUsage):
        """에이전트별 요약 출력"""
        duration = usage.get_duration()
        duration_str = f"{duration:.2f}초" if duration else "N/A"
        
        logger.info("=" * 80)
        logger.info(f"💰 Token Usage: {agent_name}")
        logger.info("-" * 80)
        logger.info(f"  호출 횟수:     {usage.call_count:,}회")
        logger.info(f"  입력 토큰:     {usage.input_tokens:,}")
        logger.info(f"  출력 토큰:     {usage.output_tokens:,}")
        logger.info(f"  총 토큰:       {usage.total_tokens:,}")
        logger.info(f"  예상 비용:     ${usage.cost:.6f}")
        logger.info(f"  실행 시간:     {duration_str}")
        logger.info("=" * 80)

    @staticmethod
    def _print_total_summary(usage_dict: Dict[str, TokenUsage]):
        """전체 집계 출력"""
        total_input = sum(u.input_tokens for u in usage_dict.values())
        total_output = sum(u.output_tokens for u in usage_dict.values())
        total_tokens = sum(u.total_tokens for u in usage_dict.values())
        total_cost = sum(u.cost for u in usage_dict.values())
        total_calls = sum(u.call_count for u in usage_dict.values())

        logger.info("")
        logger.info("=" * 80)
        logger.info("💰 Total Token Usage Summary")
        logger.info("=" * 80)
        logger.info(f"  총 호출 횟수:   {total_calls:,}회")
        logger.info(f"  총 입력 토큰:   {total_input:,}")
        logger.info(f"  총 출력 토큰:   {total_output:,}")
        logger.info(f"  총 토큰:       {total_tokens:,}")
        logger.info(f"  총 예상 비용:   ${total_cost:.6f}")
        logger.info("=" * 80)
        logger.info("")

    @classmethod
    def reset(cls):
        """모든 추적 데이터 초기화"""
        instance = cls()
        instance._usage.clear()
        instance._active_agents.clear()
        logger.debug("🔄 TokenTracker: 모든 데이터 초기화")

    @classmethod
    def get_total_cost(cls) -> float:
        """전체 예상 비용 반환"""
        instance = cls()
        return sum(u.cost for u in instance._usage.values())

    @classmethod
    def get_total_tokens(cls) -> int:
        """전체 토큰 수 반환"""
        instance = cls()
        return sum(u.total_tokens for u in instance._usage.values())

