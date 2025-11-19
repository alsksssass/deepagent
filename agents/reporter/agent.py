"""ReporterAgent - 최종 분석 리포트 생성 에이전트"""

import logging
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import SystemMessage, HumanMessage

from agents.security_agent import SecurityAgent, SecurityAgentContext
from agents.performance_agent import PerformanceAgent, PerformanceAgentContext
from agents.quality_agent import QualityAgent, QualityAgentContext
from agents.architect_agent import ArchitectAgent, ArchitectAgentContext
from agents.static_analyzer.schemas import StaticAnalyzerResponse
from agents.user_aggregator.schemas import UserAggregatorResponse
from agents.user_skill_profiler.schemas import UserSkillProfilerResponse
from shared.storage import ResultStore
from shared.utils.prompt_loader import PromptLoader
from shared.utils.token_tracker import TokenTracker
from shared.utils.agent_debug_logger import AgentDebugLogger

from .schemas import ReporterContext, ReporterResponse

logger = logging.getLogger(__name__)


class ReporterAgent:
    """
    분석 결과를 종합하여 최종 리포트를 생성하는 에이전트

    병렬 처리:
    - 4개 도메인 에이전트 병렬 실행
    - 6개 리포트 섹션 병렬 생성 (LLM 호출)
    """

    def __init__(self, llm: Optional[ChatBedrockConverse] = None):
        # 하이브리드 방식: YAML 모델 우선, 외부 LLM 전달 시 오버라이드
        if llm is None:
            # YAML 설정 기반으로 LLM 인스턴스 생성
            self.llm = PromptLoader.get_llm("reporter")
            model_id = PromptLoader.get_model("reporter")
            logger.info(f"✅ ReporterAgent: YAML 모델 사용 - {model_id}")
        else:
            # 외부 전달된 LLM 사용 (오버라이드)
            self.llm = llm
            logger.info(f"✅ ReporterAgent: 외부 LLM 사용")
        
        # 프롬프트 컴포지션 패턴: YAML에서 프롬프트 로드
        self.prompts = PromptLoader.load("reporter")

    async def run(self, context: ReporterContext) -> ReporterResponse:
        """
        최종 리포트 생성

        Args:
            context: ReporterContext

        Returns:
            ReporterResponse
        """
        logger.info(f"📝 Reporter: 리포트 생성 시작")
        
        # 디버깅 로거 초기화
        base_path = Path(context.base_path)
        debug_logger = AgentDebugLogger.get_logger(context.task_uuid, base_path, "reporter")
        
        with TokenTracker.track("reporter"), debug_logger.track_execution():
            # 요청 로깅
            debug_logger.log_request(context)
            
            try:
                # ResultStore에서 결과 로드 (메모리 효율성 향상)
                static_analysis_dict = context.static_analysis
                user_aggregate_dict = context.user_aggregate
                skill_profile_dict = {}

                if context.result_store_path:
                    try:
                        store = ResultStore(context.task_uuid, base_path)
                        
                        # StaticAnalyzer 결과 로드
                        # S3 사용 시 get_result_path()는 문자열을 반환하므로 list_available_results()로 확인
                        available_results = store.list_available_results()
                        if "static_analyzer" in available_results:
                            static_response = store.load_result("static_analyzer", StaticAnalyzerResponse)
                            static_analysis_dict = static_response.model_dump()
                            debug_logger.log_loaded_data("static_analyzer", static_analysis_dict)
                            logger.info("✅ ResultStore에서 StaticAnalyzer 결과 로드")
                        else:
                            debug_logger.log_loaded_data("static_analyzer", None, error=f"File not found: static_analyzer")
                        
                        # UserAggregator 결과 로드
                        if "user_aggregator" in available_results:
                            user_agg_response = store.load_result("user_aggregator", UserAggregatorResponse)
                            user_aggregate_dict = user_agg_response.model_dump()
                            debug_logger.log_loaded_data("user_aggregator", user_aggregate_dict)
                            logger.info("✅ ResultStore에서 UserAggregator 결과 로드")
                        else:
                            debug_logger.log_loaded_data("user_aggregator", None, error=f"File not found: user_aggregator")
                        
                        # UserSkillProfiler 결과 로드
                        if "user_skill_profiler" in available_results:
                            skill_profile_response = store.load_result("user_skill_profiler", UserSkillProfilerResponse)
                            skill_profile_dict = skill_profile_response.model_dump()
                            debug_logger.log_loaded_data("user_skill_profiler", skill_profile_dict)
                            
                            # 스킬 프로파일 상태 확인 로깅
                            debug_logger.log_intermediate("skill_profile_check", {
                                "exists": True,
                                "status": skill_profile_dict.get("status"),
                                "has_data": bool(skill_profile_dict.get("skill_profile")),
                                "total_skills": skill_profile_dict.get("skill_profile", {}).get("total_skills", 0),
                                "user": skill_profile_dict.get("user"),
                            })
                            
                            logger.info("✅ ResultStore에서 UserSkillProfiler 결과 로드")
                        else:
                            debug_logger.log_loaded_data("user_skill_profiler", None, error=f"File not found: user_skill_profiler")
                            debug_logger.log_intermediate("skill_profile_check", {
                                "exists": False,
                                "error": "File not found",
                            })
                            logger.warning(f"⚠️ UserSkillProfiler 결과 파일 없음: user_skill_profiler")
                    except Exception as e:
                        logger.warning(f"⚠️ ResultStore에서 결과 로드 실패, Context 데이터 사용: {e}")
                        debug_logger.log_loaded_data("static_analyzer", None, error=str(e))
                        debug_logger.log_loaded_data("user_aggregator", None, error=str(e))
                        debug_logger.log_loaded_data("user_skill_profiler", None, error=str(e))

                # Step 1: 도메인 전문 에이전트 병렬 실행
                logger.info("🔬 도메인 전문 에이전트 분석 시작")

                # 도메인 에이전트는 각자의 YAML 모델 사용 (llm=None)
                security_agent = SecurityAgent(llm=None)
                performance_agent = PerformanceAgent(llm=None)
                quality_agent = QualityAgent(llm=None)
                architect_agent = ArchitectAgent(llm=None)

                # 각 에이전트에 맞는 Context 생성 (ResultStore에서 로드한 데이터 사용)
                security_ctx = SecurityAgentContext(
                    task_uuid=context.task_uuid,  # ✅ 필수 필드 추가
                    static_analysis=static_analysis_dict,
                    user_aggregate=user_aggregate_dict,
                )
                performance_ctx = PerformanceAgentContext(
                    task_uuid=context.task_uuid,  # ✅ 필수 필드 추가
                    static_analysis=static_analysis_dict,
                    user_aggregate=user_aggregate_dict,
                )
                quality_ctx = QualityAgentContext(
                    task_uuid=context.task_uuid,  # ✅ 필수 필드 추가
                    static_analysis=static_analysis_dict,
                    user_aggregate=user_aggregate_dict,
                )
                architect_ctx = ArchitectAgentContext(
                    task_uuid=context.task_uuid,  # ✅ 필수 필드 추가
                    static_analysis=static_analysis_dict,
                    user_aggregate=user_aggregate_dict,
                    repo_path=context.base_path,
                )

                (
                    security_result,
                    performance_result,
                    quality_result,
                    architecture_result,
                ) = await asyncio.gather(
                    security_agent.run(security_ctx),
                    performance_agent.run(performance_ctx),
                    quality_agent.run(quality_ctx),
                    architect_agent.run(architect_ctx),
                )

                # 도메인 분석 결과 저장
                domain_analysis = {
                    "security": security_result.model_dump() if hasattr(security_result, "model_dump") else security_result,
                    "performance": performance_result.model_dump() if hasattr(performance_result, "model_dump") else performance_result,
                    "quality": quality_result.model_dump() if hasattr(quality_result, "model_dump") else quality_result,
                    "architecture": architecture_result.model_dump() if hasattr(architecture_result, "model_dump") else architecture_result,
                }

                # Step 2: 병렬 리포트 섹션 생성
                (
                    executive_summary,
                    static_analysis_section,
                    user_analysis_section,
                    skill_profile_section,
                    domain_analysis_section,
                    recommendations_section,
                ) = await asyncio.gather(
                    self._generate_executive_summary(context, static_analysis_dict, user_aggregate_dict),
                    self._generate_static_analysis_section(static_analysis_dict),
                    self._generate_user_analysis_section(user_aggregate_dict),
                    self._generate_skill_profile_section(skill_profile_dict),
                    self._generate_domain_analysis_section(domain_analysis),
                    self._generate_recommendations(static_analysis_dict, user_aggregate_dict, domain_analysis, skill_profile_dict),
                )

                # 리포트 조합
                report_content = self._compose_report(
                    git_url=context.git_url,
                    executive_summary=executive_summary,
                    static_analysis_section=static_analysis_section,
                    user_analysis_section=user_analysis_section,
                    skill_profile_section=skill_profile_section,
                    domain_analysis_section=domain_analysis_section,
                    recommendations_section=recommendations_section,
                )

                # 리포트 파일명 생성
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                report_name = f"report_{timestamp}.md"

                # ResultStore를 통해 리포트 저장 (S3 또는 로컬)
                if context.result_store_path:
                    try:
                        store = ResultStore(context.task_uuid, base_path)
                        saved_path = store.save_report(report_name, report_content)
                        logger.info(f"✅ Reporter: 리포트 저장 완료 - {saved_path}")
                        report_path = saved_path
                    except Exception as e:
                        logger.warning(f"⚠️ ResultStore 저장 실패, 로컬에 저장: {e}")
                        # Fallback: 로컬에 저장
                        report_dir = base_path / "reports"
                        report_dir.mkdir(parents=True, exist_ok=True)
                        report_path = report_dir / report_name
                        report_path.write_text(report_content, encoding="utf-8")
                        logger.info(f"✅ Reporter: 리포트 저장 완료 (로컬) - {report_path}")
                else:
                    # Fallback: 로컬에 저장
                    report_dir = base_path / "reports"
                    report_dir.mkdir(parents=True, exist_ok=True)
                    report_path = report_dir / report_name
                    report_path.write_text(report_content, encoding="utf-8")
                    logger.info(f"✅ Reporter: 리포트 저장 완료 (로컬) - {report_path}")

                response = ReporterResponse(
                    status="success",
                    report_path=str(report_path),
                )
                
                # 최종 응답 로깅
                debug_logger.log_response(response)
                return response

            except Exception as e:
                logger.error(f"❌ Reporter: {e}", exc_info=True)
                error_response = ReporterResponse(
                    status="failed",
                    report_path="",
                    error=str(e),
                )
                debug_logger.log_response(error_response)
                return error_response

    async def _generate_executive_summary(
        self, 
        context: ReporterContext,
        static_analysis: Dict[str, Any],
        user_aggregate: Dict[str, Any]
    ) -> str:
        """Executive Summary 생성 (LLM) - 프롬프트 컴포지션 패턴"""
        # System 프롬프트는 YAML에서 로드
        system_prompt = self.prompts["executive_summary_system"]
        
        # User 프롬프트는 섹션 템플릿을 조합하여 생성
        section_templates = self.prompts.get("section_templates", {})
        
        sections = [
            PromptLoader.format(
                section_templates.get("git_repo", "**Git Repository**: {git_url}\n"),
                git_url=context.git_url or 'N/A'
            ),
            PromptLoader.format(
                section_templates.get("static_analysis_section", "**정적 분석 결과**:\n{content}\n"),
                content=self._format_static_analysis(static_analysis)
            ),
            PromptLoader.format(
                section_templates.get("user_aggregate_section", "**유저 집계 결과**:\n{content}\n"),
                content=self._format_user_aggregate(user_aggregate)
            ),
        ]
        
        user_prompt = "다음 분석 결과를 요약하세요:\n\n" + "\n".join(sections)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        # 토큰 추적
        response = await self.llm.ainvoke(messages)
        TokenTracker.record_usage("reporter", response, model_id=PromptLoader.get_model("reporter"))
        return response.content

    async def _generate_static_analysis_section(self, static: Dict[str, Any]) -> str:
        """정적 분석 섹션 생성"""

        if not static:
            return "정적 분석 결과가 없습니다."

        content = "## 📊 정적 분석 결과\n\n"

        # 복잡도
        if "complexity" in static:
            complexity = static["complexity"]
            content += "### 코드 복잡도\n\n"
            content += f"- **평균 복잡도**: {complexity.get('average_complexity', 'N/A')}\n"
            content += f"- **총 함수 수**: {complexity.get('total_functions', 'N/A')}\n\n"

            summary = complexity.get("summary", {})
            if summary:
                content += "**복잡도 등급 분포**:\n"
                for rank, count in summary.items():
                    content += f"- {rank}: {count}개\n"
                content += "\n"

        # 타입 체크
        if "type_check" in static:
            type_check = static["type_check"]
            content += "### 타입 체크\n\n"
            content += f"- **에러**: {type_check.get('total_errors', 'N/A')}\n"
            content += f"- **경고**: {type_check.get('total_warnings', 'N/A')}\n"
            content += f"- **분석 파일 수**: {type_check.get('files_analyzed', 'N/A')}\n\n"

        # LOC
        if "loc_stats" in static:
            loc = static["loc_stats"]
            content += "### 코드 라인 수\n\n"
            content += f"- **총 라인**: {loc.get('total_lines', 'N/A'):,}\n"
            content += f"- **코드 라인**: {loc.get('code_lines', 'N/A'):,}\n"
            content += f"- **주석 라인**: {loc.get('comment_lines', 'N/A'):,}\n\n"

        return content

    async def _generate_user_analysis_section(self, user_agg: Dict[str, Any]) -> str:
        """유저 분석 섹션 생성"""

        if not user_agg:
            return "유저 분석 결과가 없습니다."

        content = "## 👤 유저 분석 결과\n\n"

        aggregate = user_agg.get("aggregate_stats", {})

        content += f"### 커밋 통계\n\n"
        content += f"- **총 커밋 수**: {aggregate.get('total_commits', 'N/A')}\n"
        content += f"- **성공 평가**: {aggregate.get('successful_evaluations', 'N/A')}\n"
        content += f"- **실패 평가**: {aggregate.get('failed_evaluations', 'N/A')}\n\n"

        # 품질 점수
        quality = aggregate.get("quality_stats", {})
        if quality:
            content += "### 코드 품질 점수\n\n"
            content += f"- **평균 점수**: {quality.get('average_score', 'N/A')}/10\n"
            content += f"- **중앙값**: {quality.get('median_score', 'N/A')}/10\n"
            content += f"- **최소/최대**: {quality.get('min_score', 'N/A')} / {quality.get('max_score', 'N/A')}\n\n"

        # 기술 스택
        tech = aggregate.get("tech_stats", {})
        if tech:
            top_techs = tech.get("top_technologies", [])
            content += "### 주요 기술 스택\n\n"
            for tech_name, count in top_techs[:5]:
                content += f"- **{tech_name}**: {count}회\n"
            content += "\n"

        # 복잡도 분포
        complexity = aggregate.get("complexity_stats", {})
        if complexity:
            content += "### 복잡도 분포\n\n"
            content += f"- **Low**: {complexity.get('low_count', 0)}\n"
            content += f"- **Medium**: {complexity.get('medium_count', 0)}\n"
            content += f"- **High**: {complexity.get('high_count', 0)}\n\n"

        return content

    async def _generate_skill_profile_section(self, skill_profile: Dict[str, Any]) -> str:
        """스킬 프로파일 섹션 생성"""
        
        if not skill_profile or skill_profile.get("status") != "success":
            return "스킬 프로파일 정보가 없습니다."
        
        profile_data = skill_profile.get("skill_profile", {})
        if not profile_data or profile_data.get("total_skills", 0) == 0:
            return "스킬 프로파일 정보가 없습니다."
        
        content = "## 🎯 개발자 스킬 프로파일\n\n"
        
        user = skill_profile.get("user", "N/A")
        content += f"**분석 대상**: {user}\n\n"
        
        # 전체 스킬 통계
        total_skills = profile_data.get("total_skills", 0)
        total_coverage = profile_data.get("total_coverage", 0)
        skills_by_level = profile_data.get("skills_by_level", {})
        
        # 레벨링 시스템 정보
        total_experience = profile_data.get("total_experience", 0)
        level_info = profile_data.get("level", {})
        level = level_info.get("level", 1)
        level_name = level_info.get("level_name", "초보")
        progress = level_info.get("progress_percentage", 0.0)
        next_level_exp = level_info.get("next_level_exp", 0)
        current_level_exp = level_info.get("current_level_exp", 0)

        content += "### 전체 스킬 통계\n\n"
        content += f"- **총 보유 스킬**: {total_skills}개\n"
        content += f"- **전체 커버리지**: {total_coverage}%\n"
        content += f"- **레벨 분포**: "
        level_parts = []
        if skills_by_level.get("Basic", 0) > 0:
            level_parts.append(f"Basic({skills_by_level['Basic']})")
        if skills_by_level.get("Intermediate", 0) > 0:
            level_parts.append(f"Intermediate({skills_by_level['Intermediate']})")
        if skills_by_level.get("Advanced", 0) > 0:
            level_parts.append(f"Advanced({skills_by_level['Advanced']})")
        content += ", ".join(level_parts) if level_parts else "N/A"
        content += "\n\n"

        # 레벨링 시스템 섹션 추가
        if total_experience > 0:
            content += "### 🎮 기술력 레벨\n\n"
            content += f"- **현재 레벨**: {level_name} (Lv.{level})\n"
            content += f"- **총 경험치**: {total_experience:,} EXP\n"
            content += f"- **레벨 진행률**: {progress:.1f}%\n"
            if next_level_exp > current_level_exp:
                exp_needed = next_level_exp - total_experience
                content += f"- **다음 레벨까지**: {exp_needed:,} EXP 필요\n"
            content += "\n"
        
        # 카테고리별 스킬 분포
        skills_by_category = profile_data.get("skills_by_category", {})
        category_coverage = profile_data.get("category_coverage", {})
        
        if skills_by_category:
            content += "### 카테고리별 스킬 분포\n\n"
            # 스킬 수 기준으로 정렬
            sorted_categories = sorted(
                skills_by_category.items(),
                key=lambda x: x[1].get("count", 0),
                reverse=True
            )
            
            for cat, stats in sorted_categories[:10]:  # Top 10 카테고리만 표시
                count = stats.get("count", 0)
                coverage_info = category_coverage.get(cat, {})
                coverage_pct = coverage_info.get("percentage", 0)
                total_in_cat = coverage_info.get("total", 0)
                
                content += f"- **{cat}**: {count}개 스킬 (커버리지: {coverage_pct:.1f}%, 전체: {total_in_cat}개)\n"
                # 레벨 분포
                levels = stats.get("levels", {})
                level_info = []
                if levels.get("Basic", 0) > 0:
                    level_info.append(f"Basic:{levels['Basic']}")
                if levels.get("Intermediate", 0) > 0:
                    level_info.append(f"Intermediate:{levels['Intermediate']}")
                if levels.get("Advanced", 0) > 0:
                    level_info.append(f"Advanced:{levels['Advanced']}")
                if level_info:
                    content += f"  - 레벨 분포: {', '.join(level_info)}\n"
            content += "\n"
        
        # 개발자 타입별 기술 보유율 섹션 추가
        developer_type_coverage = profile_data.get("developer_type_coverage", {})
        if developer_type_coverage:
            content += "### 👨‍💻 개발자 타입별 기술 보유율\n\n"
            for dev_type, coverage_data in list(developer_type_coverage.items())[:10]:  # Top 10
                percentage = coverage_data.get("percentage", 0.0)
                owned_count = coverage_data.get("owned_count", 0)
                total_count = coverage_data.get("total_count", 0)
                type_exp = coverage_data.get("experience", 0)
                type_level_info = coverage_data.get("level", {})
                type_level = type_level_info.get("level", 1)
                type_level_name = type_level_info.get("level_name", "초보")
                
                content += f"- **{dev_type}**: {percentage:.1f}% ({owned_count}/{total_count} 스킬) - {type_level_name} (Lv.{type_level}, {type_exp:,} EXP)\n"
            content += "\n"

        # 상위 스킬 (Top 10)
        top_skills = profile_data.get("top_skills", [])
        if top_skills:
            content += "### 상위 스킬 (Top 10)\n\n"
            for idx, skill in enumerate(top_skills[:10], 1):
                skill_name = skill.get("skill_name", "N/A")
                level = skill.get("level", "N/A")
                category = skill.get("category", "N/A")
                relevance = skill.get("relevance_score", 0)
                occurrence = skill.get("occurrence_count", 1)
                
                content += f"{idx}. **{skill_name}** ({level})\n"
                content += f"   - 카테고리: {category}\n"
                content += f"   - 신뢰도: {relevance:.2f}\n"
                content += f"   - 발견 횟수: {occurrence}회\n"
            content += "\n"
        
        return content

    async def _generate_domain_analysis_section(self, domain_analysis: Dict[str, Any]) -> str:
        """도메인 전문 에이전트 분석 섹션 생성"""
        if not domain_analysis:
            return "## 🔬 도메인 전문 분석\n\n도메인 분석 결과가 없습니다.\n"

        content = "## 🔬 도메인 전문 분석\n\n"

        # Security Agent 결과
        security = domain_analysis.get("security", {})
        if security.get("status") == "success":
            sec_analysis = security.get("security_analysis", {})
            content += "### 🛡️ 보안 분석 (Security Agent)\n\n"
            content += f"**보안 점수**: {sec_analysis.get('security_score', 'N/A')}/10\n\n"

            # 타입 안정성 이슈
            type_issues = sec_analysis.get("type_safety_issues", [])
            if type_issues:
                content += "**타입 안정성 이슈**:\n"
                for issue in type_issues[:5]:
                    content += f"- {issue}\n"
                content += "\n"

            # 취약점 위험
            vuln_risks = sec_analysis.get("vulnerability_risks", [])
            if vuln_risks:
                content += "**취약점 위험**:\n"
                for risk in vuln_risks[:5]:
                    severity = risk.get("severity", "Medium")
                    category = risk.get("category", "Unknown")
                    desc = risk.get("description", "")
                    content += f"- [{severity}] {category}: {desc}\n"
                content += "\n"

            # 권장사항
            recommendations = sec_analysis.get("recommendations", [])
            if recommendations:
                content += "**권장사항**:\n"
                for rec in recommendations[:3]:
                    content += f"- {rec}\n"
                content += "\n"

        # Performance Agent 결과
        performance = domain_analysis.get("performance", {})
        if performance.get("status") == "success":
            perf_analysis = performance.get("performance_analysis", {})
            content += "### ⚡ 성능 분석 (Performance Agent)\n\n"
            content += f"**성능 점수**: {perf_analysis.get('performance_score', 'N/A')}/10\n\n"

            # 고복잡도 함수
            high_comp = perf_analysis.get("high_complexity_functions", [])
            if high_comp:
                content += "**고복잡도 함수**:\n"
                for func in high_comp[:5]:
                    grade = func.get("grade", "N/A")
                    count = func.get("count", 0)
                    impact = func.get("impact", "")
                    content += f"- 등급 {grade}: {count}개 - {impact}\n"
                content += "\n"

            # 최적화 기회
            opt_ops = perf_analysis.get("optimization_opportunities", [])
            if opt_ops:
                content += "**최적화 기회**:\n"
                for opp in opt_ops[:3]:
                    category = opp.get("category", "Unknown")
                    desc = opp.get("description", "")
                    content += f"- {category}: {desc}\n"
                content += "\n"

        # Quality Agent 결과
        quality = domain_analysis.get("quality", {})
        if quality.get("status") == "success":
            qual_analysis = quality.get("quality_analysis", {})
            content += "### 📊 품질 분석 (Quality Agent)\n\n"
            content += f"**품질 점수**: {qual_analysis.get('quality_score', 'N/A')}/10\n\n"

            # 유지보수성 지수
            maintainability = qual_analysis.get("maintainability_index", 0)
            content += f"**유지보수성 지수**: {maintainability:.1f}/100\n\n"

            # 문서화 수준
            doc_coverage = qual_analysis.get("documentation_coverage", 0)
            content += f"**문서화 커버리지**: {doc_coverage:.1f}%\n\n"

            # 타입 안정성 수준
            type_safety = qual_analysis.get("type_safety_level", "N/A")
            content += f"**타입 안정성 수준**: {type_safety}\n\n"

            # 코드 스멜
            code_smells = qual_analysis.get("code_smells", [])
            if code_smells:
                content += "**코드 스멜**:\n"
                for smell in code_smells[:5]:
                    severity = smell.get("severity", "Medium")
                    category = smell.get("category", "Unknown")
                    desc = smell.get("description", "")
                    instances = smell.get("instances", 0)
                    content += f"- [{severity}] {category}: {desc} ({instances}개)\n"
                content += "\n"

        # Architecture Agent 결과
        architecture = domain_analysis.get("architecture", {})
        if architecture.get("status") == "success":
            arch_analysis = architecture.get("architecture_analysis", {})
            content += "### 🏗️ 아키텍처 분석 (Architecture Agent)\n\n"
            content += f"**아키텍처 점수**: {arch_analysis.get('architecture_score', 'N/A')}/10\n\n"

            # 모듈화 점수
            modularity = arch_analysis.get("modularity_score", 0)
            content += f"**모듈화 점수**: {modularity:.1f}/10\n\n"

            # 구조 패턴
            patterns = arch_analysis.get("structure_patterns", [])
            if patterns:
                content += "**식별된 아키텍처 패턴**:\n"
                for pattern in patterns[:3]:
                    pattern_name = pattern.get("pattern", "Unknown")
                    desc = pattern.get("description", "")
                    content += f"- **{pattern_name}**: {desc}\n"
                content += "\n"

            # 확장성 평가
            scalability = arch_analysis.get("scalability_assessment", "")
            if scalability:
                content += f"**확장성 평가**: {scalability}\n\n"

        # 메인 LLM 종합 분석
        content += "### 🧠 종합 분석 (Main LLM)\n\n"
        content += await self._generate_domain_synthesis(domain_analysis)

        return content

    async def _generate_domain_synthesis(self, domain_analysis: Dict[str, Any]) -> str:
        """메인 LLM의 도메인 분석 결과 종합 - 프롬프트 컴포지션 패턴"""
        # System 프롬프트는 YAML에서 로드
        system_prompt = self.prompts["domain_synthesis_system"]
        
        # 각 도메인 데이터 추출
        security_data = domain_analysis.get("security", {}).get("security_analysis", {})
        performance_data = domain_analysis.get("performance", {}).get("performance_analysis", {})
        quality_data = domain_analysis.get("quality", {}).get("quality_analysis", {})
        architecture_data = domain_analysis.get("architecture", {}).get("architecture_analysis", {})
        
        # 섹션 템플릿 조합
        section_templates = self.prompts.get("section_templates", {})
        
        sections = [
            section_templates.get("domain_analysis_intro", "다음 4개 도메인 전문 에이전트의 분석 결과를 종합하세요:\n\n"),
            PromptLoader.format(
                section_templates.get("security_domain", "**보안 (Security Agent)**: 점수 {score}/10\n- 타입 안정성 이슈: {type_safety_issues}개\n- 취약점 위험: {vulnerability_risks}개"),
                score=security_data.get("security_score", "N/A"),
                type_safety_issues=len(security_data.get("type_safety_issues", [])),
                vulnerability_risks=len(security_data.get("vulnerability_risks", []))
            ),
            PromptLoader.format(
                section_templates.get("performance_domain", "**성능 (Performance Agent)**: 점수 {score}/10\n- 고복잡도 함수: {high_complexity_functions}개 카테고리\n- 최적화 기회: {optimization_opportunities}개"),
                score=performance_data.get("performance_score", "N/A"),
                high_complexity_functions=len(performance_data.get("high_complexity_functions", [])),
                optimization_opportunities=len(performance_data.get("optimization_opportunities", []))
            ),
            PromptLoader.format(
                section_templates.get("quality_domain", "**품질 (Quality Agent)**: 점수 {score}/10\n- 유지보수성: {maintainability_index}/100\n- 타입 안정성: {type_safety_level}"),
                score=quality_data.get("quality_score", "N/A"),
                maintainability_index=quality_data.get("maintainability_index", "N/A"),
                type_safety_level=quality_data.get("type_safety_level", "N/A")
            ),
            PromptLoader.format(
                section_templates.get("architecture_domain", "**아키텍처 (Architecture Agent)**: 점수 {score}/10\n- 모듈화: {modularity_score}/10\n- 식별된 패턴: {structure_patterns}개"),
                score=architecture_data.get("architecture_score", "N/A"),
                modularity_score=architecture_data.get("modularity_score", "N/A"),
                structure_patterns=len(architecture_data.get("structure_patterns", []))
            ),
            section_templates.get("domain_synthesis_outro", "\n종합 분석을 제공하세요."),
        ]
        
        user_prompt = "\n\n".join(sections)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        # 토큰 추적
        response = await self.llm.ainvoke(messages)
        TokenTracker.record_usage("reporter", response, model_id=PromptLoader.get_model("reporter"))
        return response.content

    async def _generate_recommendations(
        self,
        static_analysis: Dict[str, Any],
        user_aggregate: Dict[str, Any],
        domain_analysis: Dict[str, Any],
        skill_profile: Dict[str, Any] = None
    ) -> str:
        """개선 권장사항 생성 (LLM) - 프롬프트 컴포지션 패턴"""
        # System 프롬프트는 YAML에서 로드
        system_prompt = self.prompts["recommendations_system"]
        
        # 도메인 점수 추출 및 포맷팅
        domain_scores = [
            PromptLoader.format(
                self.prompts.get("section_templates", {}).get("domain_score_item", "- {domain}: {score}/10\n"),
                domain="보안",
                score=domain_analysis.get('security', {}).get('security_analysis', {}).get('security_score', 'N/A')
            ),
            PromptLoader.format(
                self.prompts.get("section_templates", {}).get("domain_score_item", "- {domain}: {score}/10\n"),
                domain="성능",
                score=domain_analysis.get('performance', {}).get('performance_analysis', {}).get('performance_score', 'N/A')
            ),
            PromptLoader.format(
                self.prompts.get("section_templates", {}).get("domain_score_item", "- {domain}: {score}/10\n"),
                domain="품질",
                score=domain_analysis.get('quality', {}).get('quality_analysis', {}).get('quality_score', 'N/A')
            ),
            PromptLoader.format(
                self.prompts.get("section_templates", {}).get("domain_score_item", "- {domain}: {score}/10\n"),
                domain="아키텍처",
                score=domain_analysis.get('architecture', {}).get('architecture_analysis', {}).get('architecture_score', 'N/A')
            ),
        ]
        
        # 섹션 템플릿 조합
        section_templates = self.prompts.get("section_templates", {})
        
        sections = [
            section_templates.get("recommendations_intro", "다음 분석 결과를 바탕으로 개선 권장사항을 제시하세요:\n\n"),
            PromptLoader.format(
                section_templates.get("static_analysis_label", "**정적 분석**:\n{content}\n"),
                content=self._format_static_analysis(static_analysis)
            ),
            PromptLoader.format(
                section_templates.get("user_aggregate_label", "**유저 집계**:\n{content}\n"),
                content=self._format_user_aggregate(user_aggregate)
            ),
            PromptLoader.format(
                section_templates.get("domain_scores_label", "**도메인 분석 점수**:\n{content}\n"),
                content="".join(domain_scores)
            ),
            PromptLoader.format(
                section_templates.get("skill_profile_label", "**스킬 프로파일 정보**:\n{content}\n"),
                content=self._format_skill_profile_for_recommendations(skill_profile)
            ),
        ]
        
        user_prompt = "".join(sections)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        # 토큰 추적
        response = await self.llm.ainvoke(messages)
        TokenTracker.record_usage("reporter", response, model_id=PromptLoader.get_model("reporter"))
        return response.content

    def _compose_report(
        self,
        git_url: str,
        executive_summary: str,
        static_analysis_section: str,
        user_analysis_section: str,
        skill_profile_section: str,
        domain_analysis_section: str,
        recommendations_section: str,
    ) -> str:
        """최종 리포트 조합"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        report = f"""# 📊 Deep Agents Code Analysis Report

**Generated**: {timestamp}
**Repository**: {git_url}

---

## 📋 Executive Summary

{executive_summary}

---

{static_analysis_section}

---

{user_analysis_section}

---

{skill_profile_section}

---

{domain_analysis_section}

---

## 💡 개선 권장사항

{recommendations_section}

---

**End of Report**
"""
        return report

    def _format_static_analysis(self, static: Dict[str, Any]) -> str:
        """정적 분석 결과 포맷팅"""
        if not static:
            return "정적 분석 결과 없음"

        lines = []
        if "complexity" in static:
            lines.append(
                f"- 평균 복잡도: {static['complexity'].get('average_complexity', 'N/A')}"
            )
        if "type_check" in static:
            lines.append(
                f"- 타입 에러: {static['type_check'].get('total_errors', 'N/A')}"
            )
        if "loc_stats" in static:
            lines.append(
                f"- 코드 라인 수: {static['loc_stats'].get('code_lines', 'N/A'):,}"
            )

        return "\n".join(lines) if lines else "정적 분석 결과 없음"

    def _format_user_aggregate(self, user_agg: Dict[str, Any]) -> str:
        """유저 집계 결과 포맷팅"""
        if not user_agg:
            return "유저 집계 결과 없음"

        aggregate = user_agg.get("aggregate_stats", {})
        lines = [
            f"- 총 커밋: {aggregate.get('total_commits', 'N/A')}",
            f"- 평균 품질 점수: {aggregate.get('quality_stats', {}).get('average_score', 'N/A')}/10",
        ]

        return "\n".join(lines)

    def _format_skill_profile_for_recommendations(self, skill_profile: Dict[str, Any]) -> str:
        """권장사항 생성을 위한 스킬 프로파일 포맷팅"""
        if not skill_profile or skill_profile.get("status") != "success":
            return "스킬 프로파일 정보 없음"
        
        profile_data = skill_profile.get("skill_profile", {})
        if not profile_data:
            return "스킬 프로파일 정보 없음"
        
        lines = []
        total_skills = profile_data.get("total_skills", 0)
        total_coverage = profile_data.get("total_coverage", 0)
        category_coverage = profile_data.get("category_coverage", {})
        
        lines.append(f"- 총 보유 스킬: {total_skills}개")
        lines.append(f"- 전체 커버리지: {total_coverage}%")
        
        # 커버리지가 낮은 카테고리 (20% 미만)
        low_coverage_categories = []
        for cat, coverage_info in category_coverage.items():
            pct = coverage_info.get("percentage", 0)
            if pct < 20:
                low_coverage_categories.append(f"{cat} ({pct:.1f}%)")
        
        if low_coverage_categories:
            lines.append(f"- 부족한 스킬 영역: {', '.join(low_coverage_categories[:5])}")
        
        return "\n".join(lines) if lines else "스킬 프로파일 정보 없음"
