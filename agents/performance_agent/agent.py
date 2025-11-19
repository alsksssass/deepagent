"""PerformanceAgent - 성능 병목 및 최적화 포인트 분석 에이전트"""

import logging
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import SystemMessage, HumanMessage

from .schemas import (
    PerformanceAgentContext,
    PerformanceAgentResponse,
    PerformanceAnalysis,
    BottleneckRisk,
    OptimizationOpportunity,
)
from shared.utils.prompt_loader import PromptLoader
from shared.utils.token_tracker import TokenTracker
from shared.utils.agent_logging import log_agent_execution

logger = logging.getLogger(__name__)


class PerformanceAgent:
    """
    성능 전문 분석 에이전트

    분석 영역:
    - 높은 복잡도 함수 식별 (D, F 등급)
    - 비효율적 알고리즘 패턴 탐지
    - 성능 최적화 포인트 분석
    - 병목 위험 평가
    """

    def __init__(self, llm: Optional[ChatBedrockConverse] = None):
        # 하이브리드 방식: YAML 모델 우선, 외부 LLM 전달 시 오버라이드
        if llm is None:
            # YAML 설정 기반으로 LLM 인스턴스 생성
            self.llm = PromptLoader.get_llm("performance_agent")
            model_id = PromptLoader.get_model("performance_agent")
            logger.info(f"✅ PerformanceAgent: YAML 모델 사용 - {model_id}")
        else:
            # 외부 전달된 LLM 사용 (오버라이드)
            self.llm = llm
            logger.info(f"✅ PerformanceAgent: 외부 LLM 사용")
        
        # 하이브리드: 스키마 자동 주입
        self.prompts = PromptLoader.load_with_schema(
            "performance_agent",
            response_schema_class=PerformanceAnalysis
        )

    @log_agent_execution(agent_name="performance_agent")
    async def run(self, context: PerformanceAgentContext) -> PerformanceAgentResponse:
        """
        성능 분석 실행

        Args:
            context: PerformanceAgentContext (static_analysis, user_aggregate)

        Returns:
            PerformanceAgentResponse (status, performance_analysis, error)
        """
        logger.info("⚡ PerformanceAgent: 성능 분석 시작")

        try:
            static_analysis = context.static_analysis
            user_aggregate = context.user_aggregate

            # 분석 데이터 추출
            complexity_data = static_analysis.get("complexity", {})
            avg_complexity = complexity_data.get("average_complexity", 0)
            total_functions = complexity_data.get("total_functions", 0)
            complexity_summary = complexity_data.get("summary", {})

            loc_stats = static_analysis.get("loc_stats", {})
            total_loc = loc_stats.get("code_lines", 0)

            complexity_stats = user_aggregate.get("aggregate_stats", {}).get(
                "complexity_stats", {}
            )

            # 프롬프트 변수 준비
            prompt_variables = {
                "avg_complexity": f"{avg_complexity:.2f}",
                "total_functions": total_functions,
                "total_loc": total_loc,
                "complexity_a": complexity_summary.get("A", 0),
                "complexity_b": complexity_summary.get("B", 0),
                "complexity_c": complexity_summary.get("C", 0),
                "complexity_d": complexity_summary.get("D", 0),
                "complexity_f": complexity_summary.get("F", 0),
                "low_count": complexity_stats.get("low_count", 0),
                "medium_count": complexity_stats.get("medium_count", 0),
                "high_count": complexity_stats.get("high_count", 0),
            }

            # 프롬프트 생성 (json_schema 변수 자동 주입)
            system_prompt = PromptLoader.format(
                self.prompts["system_prompt"],
                json_schema=self.prompts.get("json_schema", "")
            )
            user_prompt = PromptLoader.format(
                self.prompts["user_template"],
                **prompt_variables
            )

            # LLM 호출 (토큰 추적)
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]

            # LLM 호출 로깅을 위해 logger 가져오기
            from shared.utils.agent_debug_logger import AgentDebugLogger
            from pathlib import Path
            base_path = Path(f"./data/analyze/{context.task_uuid}")
            debug_logger = AgentDebugLogger.get_logger(context.task_uuid, base_path, "performance_agent")

            with TokenTracker.track("performance_agent"), debug_logger.track_llm_call() as llm_tracker:
                # 프롬프트 로깅
                llm_tracker.log_prompts(
                    template_name="performance_agent",
                    variables=prompt_variables,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
                
                # LLM 호출
                response = await self.llm.ainvoke(messages)
                TokenTracker.record_usage("performance_agent", response, model_id=PromptLoader.get_model("performance_agent"))
                llm_tracker.set_messages(messages)
                llm_tracker.set_response(response)
                
                # 응답 처리 단계별 로깅
                raw_response = response.content
                parsed_json = None
                performance_analysis = None
                processing_error = None
                
                try:
                    # JSON 파싱
                    parsed_json = self._parse_json_response(raw_response)
                    
                    # Pydantic 검증
                    performance_analysis = PerformanceAnalysis(**parsed_json)
                    
                    # 성공 로깅
                    llm_tracker.log_response_stages(
                        raw=raw_response,
                        parsed=parsed_json,
                        validated=performance_analysis,
                    )
                except Exception as parse_error:
                    processing_error = str(parse_error)
                    # 에러 로깅
                    llm_tracker.log_response_stages(
                        raw=raw_response,
                        parsed=parsed_json,
                        validated=None,
                        error=processing_error,
                    )
                    raise

            logger.info(
                f"✅ PerformanceAgent: 성능 분석 완료 - 점수 {performance_analysis.performance_score}/10"
            )

            response = PerformanceAgentResponse(
                status="success",
                performance_analysis=performance_analysis,
                error=None,
            )
            return response

        except Exception as e:
            logger.error(f"❌ PerformanceAgent: {e}", exc_info=True)
            error_response = PerformanceAgentResponse(
                status="failed",
                performance_analysis=PerformanceAnalysis(),
                error=str(e),
            )
            return error_response

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """LLM 응답에서 JSON 파싱"""
        # 1. 코드 블록에서 추출 시도
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            logger.info("✅ PerformanceAgent: JSON 코드 블록에서 추출 성공")
            return json.loads(json_match.group(1))

        # 2. 직접 JSON 파싱 시도
        try:
            logger.info("⚠️  PerformanceAgent: JSON 코드 블록 없음, 직접 파싱 시도")
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"❌ PerformanceAgent: JSON 파싱 실패 - {e}")
            logger.warning("⚠️  PerformanceAgent: 기본 구조 사용")
            return {
                "high_complexity_functions": [],
                "bottleneck_risks": [],
                "optimization_opportunities": [],
                "performance_score": 7.0,
                "recommendations": ["복잡도 개선 권장"],
                "raw_analysis": text,
            }
