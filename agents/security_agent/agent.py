"""SecurityAgent - 보안 취약점 및 위험 요소 분석 에이전트"""

import logging
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import SystemMessage, HumanMessage

from .schemas import (
    SecurityAgentContext,
    SecurityAgentResponse,
    SecurityAnalysis,
    VulnerabilityRisk,
)
from shared.utils.prompt_loader import PromptLoader
from shared.utils.token_tracker import TokenTracker
from shared.utils.agent_debug_logger import AgentDebugLogger

logger = logging.getLogger(__name__)


class SecurityAgent:
    """
    보안 전문 분석 에이전트

    분석 영역:
    - 타입 안정성 관련 보안 이슈
    - 인증/인가 패턴 검사
    - 입력 검증 및 취약점 분석
    - 전반적인 보안 위험도 평가
    """

    def __init__(self, llm: Optional[ChatBedrockConverse] = None):
        # 하이브리드 방식: YAML 모델 우선, 외부 LLM 전달 시 오버라이드
        if llm is None:
            # YAML 설정 기반으로 LLM 인스턴스 생성
            self.llm = PromptLoader.get_llm("security_agent")
            model_id = PromptLoader.get_model("security_agent")
            logger.info(f"✅ SecurityAgent: YAML 모델 사용 - {model_id}")
        else:
            # 외부 전달된 LLM 사용 (오버라이드)
            self.llm = llm
            logger.info(f"✅ SecurityAgent: 외부 LLM 사용")
        
        # 하이브리드: 스키마 자동 주입
        self.prompts = PromptLoader.load_with_schema(
            "security_agent",
            response_schema_class=SecurityAnalysis
        )

    async def run(self, context: SecurityAgentContext) -> SecurityAgentResponse:
        """
        보안 분석 실행

        Args:
            context: SecurityAgentContext (static_analysis, user_aggregate, git_url)

        Returns:
            SecurityAgentResponse (status, security_analysis, error)
        """
        logger.info("🛡️  SecurityAgent: 보안 분석 시작")

        # 디버깅 로거 초기화
        base_path = Path(f"./data/analyze/{context.task_uuid}")
        debug_logger = AgentDebugLogger.get_logger(context.task_uuid, base_path, "security_agent")
        
        with debug_logger.track_execution():
            # 요청 로깅
            debug_logger.log_request(context)
            
            try:
                static_analysis = context.static_analysis
                user_aggregate = context.user_aggregate

                # 분석 데이터 추출
                type_check = static_analysis.get("type_check", {})
                type_errors = type_check.get("total_errors", 0)
                type_warnings = type_check.get("total_warnings", 0)

                complexity_data = static_analysis.get("complexity", {})
                complexity_summary = complexity_data.get("summary", {})

                tech_stack = (
                    user_aggregate.get("aggregate_stats", {})
                    .get("tech_stats", {})
                    .get("technology_frequency", {})
                )

                # 프롬프트 변수 준비
                prompt_variables = {
                    "type_errors": type_errors,
                    "type_warnings": type_warnings,
                    "complexity_a": complexity_summary.get("A", 0),
                    "complexity_b": complexity_summary.get("B", 0),
                    "complexity_c": complexity_summary.get("C", 0),
                    "complexity_d": complexity_summary.get("D", 0),
                    "complexity_f": complexity_summary.get("F", 0),
                    "tech_stack": self._format_tech_stack(tech_stack),
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

                # LLM 호출 (토큰 추적 + 개선된 디버깅 로깅)
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]

                with TokenTracker.track("security_agent"), debug_logger.track_llm_call() as llm_tracker:
                    # 프롬프트 로깅
                    llm_tracker.log_prompts(
                        template_name="security_agent",
                        variables=prompt_variables,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                    )
                    
                    # LLM 호출
                    response = await self.llm.ainvoke(messages)
                    TokenTracker.record_usage("security_agent", response, model_id=PromptLoader.get_model("security_agent"))
                    llm_tracker.set_messages(messages)
                    llm_tracker.set_response(response)
                    
                    # 응답 처리 단계별 로깅
                    raw_response = response.content
                    parsed_json = None
                    security_analysis = None
                    processing_error = None
                    
                    try:
                        # JSON 파싱
                        parsed_json = self._parse_json_response(raw_response)
                        
                        # Pydantic 검증
                        security_analysis = SecurityAnalysis(**parsed_json)
                        
                        # 성공 로깅
                        llm_tracker.log_response_stages(
                            raw=raw_response,
                            parsed=parsed_json,
                            validated=security_analysis,
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
                    f"✅ SecurityAgent: 보안 분석 완료 - 점수 {security_analysis.security_score}/10"
                )

                response = SecurityAgentResponse(
                    status="success",
                    security_analysis=security_analysis,
                    error=None,
                )
                
                # 최종 응답 로깅
                debug_logger.log_response(response)
                return response

            except Exception as e:
                logger.error(f"❌ SecurityAgent: {e}", exc_info=True)
                error_response = SecurityAgentResponse(
                    status="failed",
                    security_analysis=SecurityAnalysis(),
                    error=str(e),
                )
                debug_logger.log_response(error_response)
                return error_response

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """LLM 응답에서 JSON 파싱"""
        # 1. 코드 블록에서 추출 시도
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            logger.info("✅ SecurityAgent: JSON 코드 블록에서 추출 성공")
            return json.loads(json_match.group(1))

        # 2. 직접 JSON 파싱 시도
        try:
            logger.info("⚠️  SecurityAgent: JSON 코드 블록 없음, 직접 파싱 시도")
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"❌ SecurityAgent: JSON 파싱 실패 - {e}")
            logger.warning("⚠️  SecurityAgent: 기본 구조 사용")
            return {
                "type_safety_issues": ["JSON 파싱 실패"],
                "auth_patterns": [],
                "vulnerability_risks": [],
                "security_score": 5.0,
                "recommendations": ["수동 검토 필요"],
                "raw_analysis": text,
            }

    def _format_tech_stack(self, tech_stack: Dict[str, int]) -> str:
        """기술 스택 포맷팅"""
        if not tech_stack:
            return "N/A"

        items = []
        for tech, count in sorted(tech_stack.items(), key=lambda x: x[1], reverse=True):
            items.append(f"- {tech}: {count}회")

        return "\n".join(items) if items else "N/A"
