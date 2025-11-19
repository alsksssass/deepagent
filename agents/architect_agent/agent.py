"""ArchitectAgent - 아키텍처 패턴 및 설계 원칙 분석 에이전트"""

import logging
import json
import re
import os
from typing import Dict, Any, List, Optional
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import SystemMessage, HumanMessage

from .schemas import ArchitectAgentContext, ArchitectAgentResponse, ArchitectureAnalysis
from shared.utils.prompt_loader import PromptLoader
from shared.utils.token_tracker import TokenTracker
from shared.utils.agent_logging import log_agent_execution
from pathlib import Path

logger = logging.getLogger(__name__)


class ArchitectAgent:
    """아키텍처 전문 분석 에이전트"""

    def __init__(self, llm: Optional[ChatBedrockConverse] = None):
        # 하이브리드 방식: YAML 모델 우선, 외부 LLM 전달 시 오버라이드
        if llm is None:
            # YAML 설정 기반으로 LLM 인스턴스 생성
            self.llm = PromptLoader.get_llm("architect_agent")
            model_id = PromptLoader.get_model("architect_agent")
            logger.info(f"✅ ArchitectAgent: YAML 모델 사용 - {model_id}")
        else:
            # 외부 전달된 LLM 사용 (오버라이드)
            self.llm = llm
            logger.info(f"✅ ArchitectAgent: 외부 LLM 사용")
        
        # 하이브리드: 스키마 자동 주입
        self.prompts = PromptLoader.load_with_schema(
            "architect_agent",
            response_schema_class=ArchitectureAnalysis
        )

    @log_agent_execution(agent_name="architect_agent")
    async def run(self, context: ArchitectAgentContext) -> ArchitectAgentResponse:
        logger.info("🏗️  ArchitectAgent: 아키텍처 분석 시작")

        try:
            static_analysis = context.static_analysis
            user_aggregate = context.user_aggregate
            repo_path = context.repo_path

            # 데이터 추출
            loc_stats = static_analysis.get("loc_stats", {})
            code_lines = loc_stats.get("code_lines", 0)
            by_language = loc_stats.get("by_language", {})
            total_files = sum(
                lang_stats.get("files", 0) for lang_stats in by_language.values()
            )

            complexity_data = static_analysis.get("complexity", {})
            total_functions = complexity_data.get("total_functions", 0)

            agg_stats = user_aggregate.get("aggregate_stats", {})
            tech_stack = (
                agg_stats.get("tech_stats", {}).get("technology_frequency", {})
            )

            # 디렉토리 구조 분석
            directory_structure = self._analyze_directory_structure(repo_path)

            # 프롬프트 변수 준비
            prompt_variables = {
                "total_files": total_files,
                "code_lines": code_lines,
                "total_functions": total_functions,
                "directory_structure": "\n".join(directory_structure[:30]),
                "tech_stack": self._format_tech_stack(tech_stack),
                "avg_lines_per_file": f"{code_lines / total_files if total_files > 0 else 0:.1f}",
                "avg_lines_per_function": f"{code_lines / total_functions if total_functions > 0 else 0:.1f}",
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
            debug_logger = AgentDebugLogger.get_logger(context.task_uuid, base_path, "architect_agent")

            with TokenTracker.track("architect_agent"), debug_logger.track_llm_call() as llm_tracker:
                # 프롬프트 로깅
                llm_tracker.log_prompts(
                    template_name="architect_agent",
                    variables=prompt_variables,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
                
                # LLM 호출
                response = await self.llm.ainvoke(messages)
                TokenTracker.record_usage("architect_agent", response, model_id=PromptLoader.get_model("architect_agent"))
                llm_tracker.set_messages(messages)
                llm_tracker.set_response(response)
                
                # 응답 처리 단계별 로깅
                raw_response = response.content
                parsed_json = None
                architecture_analysis = None
                processing_error = None
                
                try:
                    # JSON 파싱
                    parsed_json = self._parse_json_response(raw_response)
                    
                    # Pydantic 검증
                    architecture_analysis = ArchitectureAnalysis(**parsed_json)
                    
                    # 성공 로깅
                    llm_tracker.log_response_stages(
                        raw=raw_response,
                        parsed=parsed_json,
                        validated=architecture_analysis,
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
                f"✅ ArchitectAgent: 아키텍처 분석 완료 - 점수 {architecture_analysis.architecture_score}/10"
            )

            response = ArchitectAgentResponse(
                status="success",
                architecture_analysis=architecture_analysis,
                error=None,
            )
            return response

        except Exception as e:
            logger.error(f"❌ ArchitectAgent: {e}", exc_info=True)
            error_response = ArchitectAgentResponse(
                status="failed",
                architecture_analysis=ArchitectureAnalysis(),
                error=str(e),
            )
            return error_response

    def _analyze_directory_structure(self, repo_path: str) -> List[str]:
        """디렉토리 구조 분석 (3레벨까지)"""
        directory_structure = []

        if not os.path.exists(repo_path):
            return ["레포지토리 경로 없음"]

        try:
            for root, dirs, files in os.walk(repo_path):
                # .git 등 제외
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                level = root.replace(repo_path, "").count(os.sep)
                if level < 3:  # 3레벨까지만
                    indent = " " * 2 * level
                    directory_structure.append(f"{indent}{os.path.basename(root)}/")
        except Exception as e:
            logger.warning(f"디렉토리 구조 분석 실패: {e}")
            return ["디렉토리 구조 분석 실패"]

        return directory_structure

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """LLM 응답에서 JSON 파싱 (중괄호 매칭 로직)"""
        # 1. 코드 블록에서 추출 시도
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            logger.info("✅ ArchitectAgent: JSON 코드 블록에서 추출 성공")
            return json.loads(json_match.group(1))

        # 2. 중괄호 매칭을 통해 첫 번째 완전한 JSON 객체 찾기
        try:
            logger.info("⚠️  ArchitectAgent: JSON 코드 블록 없음, 첫 번째 JSON 객체 추출 시도")

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
            logger.warning(f"❌ ArchitectAgent: JSON 파싱 실패 - {e}")
            logger.warning("⚠️  ArchitectAgent: 기본 구조 사용")
            return {
                "structure_patterns": [],
                "design_principles": {},
                "modularity_score": 6.0,
                "scalability_assessment": "보통 수준",
                "architecture_score": 6.0,
                "recommendations": ["아키텍처 개선 권장"],
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
