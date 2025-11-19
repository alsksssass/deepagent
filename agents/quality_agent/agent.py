"""QualityAgent - 코드 품질 및 유지보수성 분석 에이전트"""

import logging
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import SystemMessage, HumanMessage

from .schemas import (
    QualityAgentContext,
    QualityAgentResponse,
    QualityAnalysis,
    CodeSmell,
)
from shared.utils.prompt_loader import PromptLoader
from shared.utils.token_tracker import TokenTracker
from shared.utils.agent_logging import log_agent_execution

logger = logging.getLogger(__name__)


class QualityAgent:
    """
    품질 전문 분석 에이전트

    분석 영역:
    - 코드 복잡도 상세 분석
    - 타입 안정성 평가
    - 주석/문서화 수준 평가
    - 코드 스멜 식별
    """

    def __init__(self, llm: Optional[ChatBedrockConverse] = None):
        # 하이브리드 방식: YAML 모델 우선, 외부 LLM 전달 시 오버라이드
        if llm is None:
            # YAML 설정 기반으로 LLM 인스턴스 생성
            self.llm = PromptLoader.get_llm("quality_agent")
            model_id = PromptLoader.get_model("quality_agent")
            logger.info(f"✅ QualityAgent: YAML 모델 사용 - {model_id}")
        else:
            # 외부 전달된 LLM 사용 (오버라이드)
            self.llm = llm
            logger.info(f"✅ QualityAgent: 외부 LLM 사용")
        
        # 하이브리드: 스키마 자동 주입
        self.prompts = PromptLoader.load_with_schema(
            "quality_agent",
            response_schema_class=QualityAnalysis
        )

    @log_agent_execution(agent_name="quality_agent")
    async def run(self, context: QualityAgentContext) -> QualityAgentResponse:
        """
        품질 분석 실행

        Args:
            context: QualityAgentContext (static_analysis, user_aggregate)

        Returns:
            QualityAgentResponse (status, quality_analysis, error)
        """
        logger.info("📊 QualityAgent: 품질 분석 시작")

        try:
            static_analysis = context.static_analysis
            user_aggregate = context.user_aggregate

            # 분석 데이터 추출
            loc_stats = static_analysis.get("loc_stats", {})
            code_lines = loc_stats.get("code_lines", 0)
            comment_lines = loc_stats.get("comment_lines", 0)
            total_lines = loc_stats.get("total_lines", 1)

            type_check = static_analysis.get("type_check", {})
            type_errors = type_check.get("total_errors", 0)
            type_warnings = type_check.get("total_warnings", 0)
            files_analyzed = type_check.get("files_analyzed", 0)

            complexity_data = static_analysis.get("complexity", {})
            avg_complexity = complexity_data.get("average_complexity", 0)

            agg_stats = user_aggregate.get("aggregate_stats", {})
            avg_quality_score = (
                agg_stats.get("quality_stats", {}).get("average_score", 0)
            )

            # 주석 비율 계산
            comment_ratio = (comment_lines / total_lines * 100) if total_lines > 0 else 0
            # 타입 에러 비율
            type_error_ratio = (type_errors / files_analyzed) if files_analyzed > 0 else 0

            # 프롬프트 변수 준비
            prompt_variables = {
                "total_lines": total_lines,
                "code_lines": code_lines,
                "comment_lines": comment_lines,
                "comment_ratio": f"{comment_ratio:.1f}",
                "files_analyzed": files_analyzed,
                "type_errors": type_errors,
                "type_warnings": type_warnings,
                "type_error_ratio": f"{type_error_ratio:.2f}",
                "avg_complexity": f"{avg_complexity:.2f}",
                "avg_quality_score": f"{avg_quality_score:.2f}",
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
            debug_logger = AgentDebugLogger.get_logger(context.task_uuid, base_path, "quality_agent")

            with TokenTracker.track("quality_agent"), debug_logger.track_llm_call() as llm_tracker:
                # 프롬프트 로깅
                llm_tracker.log_prompts(
                    template_name="quality_agent",
                    variables=prompt_variables,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
                
                # LLM 호출
                response = await self.llm.ainvoke(messages)
                TokenTracker.record_usage("quality_agent", response, model_id=PromptLoader.get_model("quality_agent"))
                llm_tracker.set_messages(messages)
                llm_tracker.set_response(response)
                
                # 응답 처리 단계별 로깅
                raw_response = response.content
                parsed_json = None
                quality_analysis = None
                processing_error = None
                
                try:
                    # JSON 파싱
                    parsed_json = self._parse_json_response(
                        raw_response, comment_ratio, avg_quality_score
                    )
                    
                    # Pydantic 검증
                    quality_analysis = QualityAnalysis(**parsed_json)
                    
                    # 성공 로깅
                    llm_tracker.log_response_stages(
                        raw=raw_response,
                        parsed=parsed_json,
                        validated=quality_analysis,
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
                f"✅ QualityAgent: 품질 분석 완료 - 점수 {quality_analysis.quality_score}/10"
            )

            response = QualityAgentResponse(
                status="success",
                quality_analysis=quality_analysis,
                error=None,
            )
            return response

        except Exception as e:
            logger.error(f"❌ QualityAgent: {e}", exc_info=True)
            error_response = QualityAgentResponse(
                status="failed",
                quality_analysis=QualityAnalysis(),
                error=str(e),
            )
            return error_response

    def _parse_json_response(
        self, text: str, comment_ratio: float, avg_quality_score: float
    ) -> Dict[str, Any]:
        """LLM 응답에서 JSON 파싱"""
        # 1. 코드 블록에서 추출 시도
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            logger.info("✅ QualityAgent: JSON 코드 블록에서 추출 성공")
            return json.loads(json_match.group(1))

        # 2. 첫 번째 완전한 JSON 객체만 추출 (기존 로직 유지)
        try:
            logger.info("⚠️  QualityAgent: JSON 코드 블록 없음, 첫 번째 JSON 객체 추출 시도")

            # 중괄호 매칭을 통해 첫 번째 완전한 JSON 객체 찾기
            start_idx = text.find("{")
            if start_idx == -1:
                raise ValueError("JSON 객체 시작을 찾을 수 없음")

            brace_count = 0
            end_idx = start_idx
            for i in range(start_idx, len(text)):
                if text[i] == "{":
                    brace_count += 1
                elif text[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break

            if brace_count != 0:
                raise ValueError("JSON 객체가 완전하지 않음")

            json_str = text[start_idx:end_idx]
            return json.loads(json_str)

        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"❌ QualityAgent: JSON 파싱 실패 - {e}")
            logger.warning("⚠️  QualityAgent: 기본 구조 사용")
            return {
                "maintainability_index": 50.0,
                "documentation_coverage": comment_ratio,
                "type_safety_level": "Fair",
                "code_smells": [],
                "quality_score": avg_quality_score if avg_quality_score > 0 else 5.0,
                "recommendations": ["품질 개선 필요"],
                "raw_analysis": text,
            }
