"""RepoSynthesizerAgent - 여러 레포지토리 결과를 종합하는 에이전트"""

import logging
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from langchain_core.messages import SystemMessage, HumanMessage

from shared.storage import ResultStore
from shared.utils.prompt_loader import PromptLoader
from shared.utils.token_tracker import TokenTracker
from .schemas import (
    RepoSynthesizerContext,
    RepoSynthesizerResponse,
    UserAnalysisResult,
    LanguageInfo,
    LLMAnalysisResult,
)

# Response 클래스 import (load_result에 필요)
from agents.static_analyzer.schemas import StaticAnalyzerResponse
from agents.user_aggregator.schemas import UserAggregatorResponse
from agents.user_skill_profiler.schemas import UserSkillProfilerResponse

logger = logging.getLogger(__name__)


class RepoSynthesizerAgent:
    """
    여러 레포지토리 분석 결과를 종합하는 에이전트

    주요 기능:
    1. 각 레포지토리 결과 로드 및 검증
    2. 통계 집계 (총 커밋 수, 총 파일 수 등)
    3. 레포지토리 간 비교 분석
    4. LLM을 이용한 종합 분석 및 개선 방향 제시
    5. 종합 리포트 생성
    """

    def __init__(self):
        """에이전트 초기화"""
        # PromptLoader로 LLM 로드
        self.llm = PromptLoader.get_llm("repo_synthesizer")
        model_id = PromptLoader.get_model("repo_synthesizer")
        
        # 하이브리드: 스키마 자동 주입
        self.prompts = PromptLoader.load_with_schema(
            "repo_synthesizer",
            response_schema_class=LLMAnalysisResult
        )
        
        logger.info(f"✅ RepoSynthesizer: LLM 초기화 완료 - {model_id}")

    async def run(self, context: RepoSynthesizerContext) -> RepoSynthesizerResponse:
        """
        여러 레포지토리 결과 종합

        Args:
            context: RepoSynthesizerContext

        Returns:
            RepoSynthesizerResponse
        """
        logger.info(f"🔬 RepoSynthesizer: {len(context.repo_results)}개 레포지토리 종합 시작")

        try:
            # 1. 각 레포 결과 요약 추출
            repo_summaries = await self._extract_repo_summaries(context.repo_results)

            # 2. 통계 집계
            total_commits = sum(s.get("total_commits", 0) for s in repo_summaries)
            total_files = sum(s.get("total_files", 0) for s in repo_summaries)
            successful = sum(1 for s in repo_summaries if s.get("status") == "success")
            failed = len(repo_summaries) - successful

            logger.info(f"   총 커밋: {total_commits}, 총 파일: {total_files}")
            logger.info(f"   성공: {successful}개, 실패: {failed}개")

            # 3. target_user가 지정된 경우 UserAnalysisResult 생성
            user_analysis_result = None
            if context.target_user:
                user_analysis_result = await self._generate_user_analysis_result(
                    context.repo_results,
                    context.target_user,
                    context.main_task_uuid,
                    context.main_base_path,
                )

            # 4. LLM 종합 분석 및 개선 방향 제시
            llm_analysis = await self._generate_llm_analysis(
                repo_summaries=repo_summaries,
                total_commits=total_commits,
                total_files=total_files,
                successful=successful,
                failed=failed,
                target_user=context.target_user,
                user_analysis_result=user_analysis_result,
            )

            # 5. 종합 리포트 생성
            report_content = self._generate_synthesis_report(
                repo_summaries=repo_summaries,
                total_commits=total_commits,
                total_files=total_files,
                successful=successful,
                failed=failed,
                target_user=context.target_user,
                user_analysis_result=user_analysis_result,
                llm_analysis=llm_analysis,
            )

            # 6. UserAnalysisResult의 markdown, level, tech_stack, 언어별 정보 업데이트
            if user_analysis_result:
                user_analysis_result.markdown = report_content
                
                # LLM이 생성한 level 정보를 UserAnalysisResult에도 삽입
                if llm_analysis and llm_analysis.level:
                    user_analysis_result.level = llm_analysis.level
                    logger.info(f"   UserAnalysisResult.level 업데이트 완료: level={llm_analysis.level.get('level', 0)}")
                
                # LLM이 생성한 tech_stack을 UserAnalysisResult에도 삽입
                if llm_analysis and llm_analysis.tech_stack:
                    user_analysis_result.tech_stack = llm_analysis.tech_stack
                    logger.info(f"   UserAnalysisResult.tech_stack 업데이트 완료: {len(llm_analysis.tech_stack)}개 기술")
                
                # LLM이 생성한 언어별 정보를 UserAnalysisResult에 동적 필드로 삽입
                if llm_analysis:
                    for attr_name in dir(llm_analysis):
                        if not attr_name.startswith('_') and attr_name not in [
                            'overall_assessment', 'strengths', 'improvement_recommendations',
                            'role_suitability', 'level', 'tech_stack', 'model_config',
                            'model_fields', 'model_computed_fields', 'model_dump', 'model_dump_json',
                            'model_validate', 'model_validate_json', 'model_copy', 'model_post_init',
                            'model_json_schema', 'model_parametrized_name', 'model_rebuild', 'model_fields_set'
                        ]:
                            attr_value = getattr(llm_analysis, attr_name, None)
                            # LanguageInfo 타입인지 확인 (dict with stack, level, exp)
                            if isinstance(attr_value, dict) and all(k in attr_value for k in ['stack', 'level', 'exp']):
                                lang_info = LanguageInfo(**attr_value)
                                setattr(user_analysis_result, attr_name, lang_info)
                                logger.info(f"   UserAnalysisResult.{attr_name} 업데이트 완료")
                            elif isinstance(attr_value, LanguageInfo):
                                setattr(user_analysis_result, attr_name, attr_value)
                                logger.info(f"   UserAnalysisResult.{attr_name} 업데이트 완료")
                
                logger.info("   UserAnalysisResult.markdown에 전체 리포트 내용 업데이트 완료")

            # 7. 리포트 저장
            main_store = ResultStore(context.main_task_uuid, Path(context.main_base_path))
            report_path = main_store.save_report("synthesis_report.md", report_content)

            logger.info(f"✅ RepoSynthesizer: 종합 완료")
            logger.info(f"   리포트: {report_path}")

            return RepoSynthesizerResponse(
                status="success",
                total_repos=len(repo_summaries),
                successful_repos=successful,
                failed_repos=failed,
                total_commits=total_commits,
                total_files=total_files,
                synthesis_report_path=str(report_path),
                synthesis_report_markdown=report_content,
                repo_summaries=repo_summaries,
                user_analysis_result=user_analysis_result,
                llm_analysis=llm_analysis,
            )

        except Exception as e:
            logger.error(f"❌ RepoSynthesizer 실패: {e}", exc_info=True)
            return RepoSynthesizerResponse(
                status="failed",
                error=str(e),
            )

    async def _extract_repo_summaries(
        self, repo_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """각 레포지토리 결과 요약 추출"""
        summaries = []

        for result in repo_results:
            try:
                # 에러 발생한 레포 처리
                if result.get("error_message"):
                    summaries.append({
                        "git_url": result.get("git_url", "unknown"),
                        "task_uuid": result.get("task_uuid", ""),
                        "status": "failed",
                        "error": result.get("error_message"),
                        "total_commits": 0,
                        "total_files": 0,
                    })
                    continue

                # 성공한 레포 요약
                task_uuid = result.get("task_uuid", "")
                base_path = result.get("base_path", "")

                # ResultStore에서 추가 정보 로드 시도
                try:
                    if task_uuid and base_path:
                        store = ResultStore(task_uuid, Path(base_path))
                        
                        # UserAggregator 결과 로드 (품질 점수 등)
                        user_agg_response = store.load_result("user_aggregator", UserAggregatorResponse)
                        user_agg = user_agg_response.model_dump() if user_agg_response else None
                        quality_score = None
                        if user_agg and user_agg.get("aggregate_stats"):
                            quality_stats = user_agg["aggregate_stats"].get("quality_stats", {})
                            quality_score = quality_stats.get("mean_score")

                        summaries.append({
                            "git_url": result.get("git_url", ""),
                            "task_uuid": task_uuid,
                            "base_path": base_path,
                            "status": "success",
                            "total_commits": result.get("total_commits", 0),
                            "total_files": result.get("total_files", 0),
                            "final_report_path": result.get("final_report_path"),
                            "quality_score": quality_score,
                        })
                    else:
                        summaries.append({
                            "git_url": result.get("git_url", ""),
                            "task_uuid": task_uuid,
                            "base_path": base_path,
                            "status": "success",
                            "total_commits": result.get("total_commits", 0),
                            "total_files": result.get("total_files", 0),
                        })
                except Exception as e:
                    logger.warning(f"⚠️ ResultStore 로드 실패: {e}")
                    summaries.append({
                        "git_url": result.get("git_url", ""),
                        "task_uuid": task_uuid,
                        "base_path": base_path,
                        "status": "success",
                        "total_commits": result.get("total_commits", 0),
                        "total_files": result.get("total_files", 0),
                    })

            except Exception as e:
                logger.warning(f"⚠️ 레포 요약 추출 실패: {e}")
                summaries.append({
                    "git_url": result.get("git_url", "unknown"),
                    "status": "failed",
                    "error": str(e),
                })

        return summaries


    async def _generate_llm_analysis(
        self,
        repo_summaries: List[Dict[str, Any]],
        total_commits: int,
        total_files: int,
        successful: int,
        failed: int,
        target_user: str | None,
        user_analysis_result: Optional[UserAnalysisResult],
    ) -> Optional[LLMAnalysisResult]:
        """
        LLM을 이용한 종합 분석 및 개선 방향 제시
        
        Returns:
            LLMAnalysisResult 또는 None
        """
        try:
            # 레포지토리 요약 포맷팅
            repo_summaries_text = self._format_repo_summaries(repo_summaries)
            
            # 각 repo의 상세 JSON 데이터 수집
            repo_json_data = await self._collect_repo_json_data(repo_summaries)
            
            # 유저 분석 결과 포맷팅
            user_analysis_text = ""
            if user_analysis_result:
                user_analysis_text = self._format_user_analysis_result(user_analysis_result)
            
            # 프롬프트 변수 준비
            prompt_variables = {
                "total_repos": len(repo_summaries),
                "successful_repos": successful,
                "failed_repos": failed,
                "total_commits": total_commits,
                "total_files": total_files,
                "target_user": target_user if target_user else "전체 유저",
                "repo_summaries": repo_summaries_text,
                "repo_json_data": repo_json_data,
                "user_analysis_result": user_analysis_text if user_analysis_text else "없음",
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
            
            # LLM 호출
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            
            logger.info("🤖 LLM 종합 분석 시작...")
            response = await self.llm.ainvoke(messages)
            TokenTracker.record_usage(
                "repo_synthesizer",
                response,
                model_id=PromptLoader.get_model("repo_synthesizer")
            )
            
            # JSON 파싱
            content = response.content
            try:
                if "```json" in content:
                    json_str = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    json_str = content.split("```")[1].split("```")[0].strip()
                else:
                    json_str = content.strip()
                
                analysis_data = json.loads(json_str)
                
                # 누락된 필드 보완 (category 필드가 없는 경우)
                if "improvement_recommendations" in analysis_data:
                    for rec in analysis_data["improvement_recommendations"]:
                        if "category" not in rec or not rec.get("category"):
                            # title에서 카테고리를 추론하거나 기본값 사용
                            rec["category"] = "일반"
                
                # Pydantic 모델로 변환
                try:
                    llm_result = LLMAnalysisResult(**analysis_data)
                    logger.info("✅ LLM 종합 분석 완료")
                    return llm_result
                except Exception as validation_error:
                    # Pydantic 검증 실패 시 더 자세한 로깅
                    logger.warning(f"⚠️ LLM 응답 검증 실패: {validation_error}")
                    logger.debug(f"응답 데이터: {json.dumps(analysis_data, indent=2, ensure_ascii=False)[:1000]}")
                    # 기본값으로 재시도
                    try:
                        # 필수 필드가 없는 경우 기본값으로 채우기
                        if "overall_assessment" not in analysis_data:
                            analysis_data["overall_assessment"] = "분석 결과를 생성할 수 없습니다."
                        if "strengths" not in analysis_data:
                            analysis_data["strengths"] = []
                        if "improvement_recommendations" not in analysis_data:
                            analysis_data["improvement_recommendations"] = []
                        
                        llm_result = LLMAnalysisResult(**analysis_data)
                        logger.info("✅ LLM 종합 분석 완료 (기본값 보완)")
                        return llm_result
                    except Exception as e2:
                        logger.warning(f"⚠️ LLM 응답 복구 실패: {e2}")
                        return None
                
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ LLM 응답 JSON 파싱 실패: {e}")
                logger.debug(f"응답 내용: {content[:500]}")
                return None
            except Exception as e:
                logger.warning(f"⚠️ LLM 응답 파싱 실패: {e}")
                logger.debug(f"응답 내용: {content[:500]}")
                return None
                
        except Exception as e:
            logger.error(f"❌ LLM 분석 실패: {e}", exc_info=True)
            return None

    async def _collect_repo_json_data(self, repo_summaries: List[Dict[str, Any]]) -> str:
        """
        각 레포지토리의 상세 JSON 데이터 수집
        
        Returns:
            JSON 형식으로 포맷팅된 문자열
        """
        repo_json_list = []
        
        for summary in repo_summaries:
            if summary.get("status") != "success":
                continue
            
            task_uuid = summary.get("task_uuid", "")
            base_path = summary.get("base_path")
            git_url = summary.get("git_url", "")
            
            if not task_uuid or not base_path:
                continue
            
            try:
                store = ResultStore(task_uuid, Path(base_path))
                
                # 주요 분석 결과 로드
                repo_data = {
                    "git_url": git_url,
                    "task_uuid": task_uuid,
                }
                
                # StaticAnalyzer 결과 (핵심 정보만)
                try:
                    static_response = store.load_result("static_analyzer", StaticAnalyzerResponse)
                    if static_response:
                        static_dict = static_response.model_dump()
                        # 핵심 정보만 추출 (실제 존재하는 필드)
                        repo_data["static_analysis"] = {
                            "loc_stats": static_dict.get("loc_stats", {}),
                            "complexity": static_dict.get("complexity", {}),
                            "type_check": static_dict.get("type_check", {}),
                        }
                except Exception as e:
                    logger.debug(f"Static analyzer 로드 실패: {e}")
                
                # UserAggregator 결과 (전체 통계)
                try:
                    user_agg_response = store.load_result("user_aggregator", UserAggregatorResponse)
                    if user_agg_response:
                        agg_dict = user_agg_response.model_dump()
                        # aggregate_stats 전체 포함 (품질, 기술, 복잡도 통계)
                        repo_data["user_aggregator"] = {
                            "aggregate_stats": agg_dict.get("aggregate_stats", {})
                        }
                except Exception as e:
                    logger.debug(f"User aggregator 로드 실패: {e}")
                
                # UserSkillProfiler 결과 (분석에 핵심적인 필드만)
                try:
                    skill_profile_response = store.load_result("user_skill_profiler", UserSkillProfilerResponse)
                    if skill_profile_response:
                        skill_dict = skill_profile_response.model_dump()
                        skill_profile_data = skill_dict.get("skill_profile", {})
                        
                        # 핵심 정보만 추출 (실제 존재하는 필드)
                        repo_data["skill_profile"] = {
                            "total_skills": skill_profile_data.get("total_skills", 0),
                            "skills_by_level": skill_profile_data.get("skills_by_level", {}),
                            "skills_by_category": skill_profile_data.get("skills_by_category", {}),
                            "top_skills": skill_profile_data.get("top_skills", [])[:10],  # 상위 10개만
                            "total_experience": skill_profile_data.get("total_experience", 0),
                            "level": skill_profile_data.get("level", {}),
                            "developer_type_coverage": skill_profile_data.get("developer_type_coverage", {}),
                            "developer_type_levels": skill_profile_data.get("developer_type_levels", {}),
                            "category_coverage": skill_profile_data.get("category_coverage", {}),
                            "total_coverage": skill_profile_data.get("total_coverage", 0),
                        }
                except Exception as e:
                    logger.debug(f"Skill profiler 로드 실패: {e}")
                
                repo_json_list.append(repo_data)
                
            except Exception as e:
                logger.warning(f"⚠️ 레포지토리 {git_url} JSON 데이터 수집 실패: {e}")
                continue
        
        if not repo_json_list:
            logger.warning("   레포지토리 JSON 데이터 수집 실패")
            return "레포지토리 JSON 데이터 없음"
        
        logger.info(f"   수집된 JSON 데이터: {len(repo_json_list)}개 레포지토리")
        
        # JSON 포맷팅 (가독성을 위해 들여쓰기)
        json_str = json.dumps(repo_json_list, indent=2, ensure_ascii=False)
        logger.info(f"   JSON 데이터 크기: {len(json_str):,} 문자")
        
        return json_str

    def _format_repo_summaries(self, repo_summaries: List[Dict[str, Any]]) -> str:
        """레포지토리 요약 포맷팅"""
        formatted = []
        for i, summary in enumerate(repo_summaries, 1):
            status_emoji = "✅" if summary.get("status") == "success" else "❌"
            git_url = summary.get("git_url", "unknown")
            
            repo_text = f"\n{i}. {status_emoji} {git_url}\n"
            if summary.get("status") == "success":
                repo_text += f"   - 커밋 수: {summary.get('total_commits', 0):,}개\n"
                repo_text += f"   - 파일 수: {summary.get('total_files', 0):,}개\n"
                if summary.get("quality_score") is not None:
                    repo_text += f"   - 품질 점수: {summary.get('quality_score'):.2f}/10\n"
            else:
                repo_text += f"   - 에러: {summary.get('error', 'Unknown error')}\n"
            
            formatted.append(repo_text)
        
        return "\n".join(formatted)

    def _format_user_analysis_result(self, user_analysis_result: UserAnalysisResult) -> str:
        """유저 분석 결과 포맷팅"""
        formatted = []
        
        formatted.append(f"코드 품질 점수: {user_analysis_result.clean_code:.2f}/10")
        
        if user_analysis_result.role:
            formatted.append(f"\n역할별 기술스택 보유율:")
            for role, percentage in sorted(user_analysis_result.role.items(), key=lambda x: x[1], reverse=True):
                formatted.append(f"  - {role}: {percentage}%")
        
        if hasattr(user_analysis_result, 'python') and user_analysis_result.python:
            python = user_analysis_result.python
            formatted.append(f"\nPython 분석:")
            formatted.append(f"  - 숙련도 레벨: {python.level}")
            formatted.append(f"  - 경험치: {python.exp:,}")
            if python.stack:
                formatted.append(f"  - 기술 스택: {', '.join(python.stack)}")
        
        return "\n".join(formatted)

    async def _generate_user_analysis_result(
        self,
        repo_results: List[Dict[str, Any]],
        target_user: str,
        main_task_uuid: str,
        main_base_path: str,
    ) -> Optional[UserAnalysisResult]:
        """
        target_user의 종합 분석 결과 생성
        
        Returns:
            UserAnalysisResult 또는 None
        """
        try:
            # 모든 레포지토리에서 데이터 수집
            all_quality_scores = []  # 품질 점수 리스트
            all_developer_type_coverage = {}  # 역할별 커버리지
            
            for result in repo_results:
                if result.get("error_message"):
                    continue
                    
                task_uuid = result.get("task_uuid", "")
                base_path = result.get("base_path", "")
                
                if not task_uuid or not base_path:
                    continue
                
                try:
                    store = ResultStore(task_uuid, Path(base_path))
                    
                    # 1. UserAggregator 결과에서 품질 점수 수집
                    user_agg_response = store.load_result("user_aggregator", UserAggregatorResponse)
                    user_agg = user_agg_response.model_dump() if user_agg_response else None
                    if user_agg and user_agg.get("aggregate_stats"):
                        quality_stats = user_agg["aggregate_stats"].get("quality_stats", {})
                        avg_score = quality_stats.get("average_score")
                        if avg_score is not None:
                            all_quality_scores.append(avg_score)
                    
                    # 2. UserSkillProfiler 결과에서 역할별 커버리지 수집
                    skill_profile_response = store.load_result("user_skill_profiler", UserSkillProfilerResponse)
                    skill_profile = skill_profile_response.model_dump() if skill_profile_response else None
                    
                    if skill_profile and skill_profile.get("skill_profile"):
                        dev_type_coverage = skill_profile["skill_profile"].get("developer_type_coverage", {})
                        for role, coverage_data in dev_type_coverage.items():
                            if role not in all_developer_type_coverage:
                                all_developer_type_coverage[role] = []
                            percentage = coverage_data.get("percentage", 0)
                            if percentage is not None:
                                all_developer_type_coverage[role].append(percentage)
                
                except Exception as e:
                    logger.warning(f"⚠️ 레포지토리 {task_uuid} 데이터 수집 실패: {e}")
                    continue
            
            # 데이터 집계
            logger.info(f"   품질 점수: {len(all_quality_scores)}개")
            logger.info(f"   역할 커버리지: {list(all_developer_type_coverage.keys())}")
            
            # 1. clean_code 점수 계산 (평균)
            clean_code_score = 0.0
            if all_quality_scores:
                clean_code_score = sum(all_quality_scores) / len(all_quality_scores)
            
            # 2. role 퍼센트 계산 (각 역할별 평균)
            role_percentages = {}
            for role, percentages in all_developer_type_coverage.items():
                if percentages:
                    role_percentages[role] = int(sum(percentages) / len(percentages))
            
            # UserAnalysisResult 생성 (기본 정보만, 언어별 정보는 LLM이 생성하여 나중에 삽입)
            result = UserAnalysisResult(
                python=LanguageInfo(),  # 빈 초기값, LLM이 채움
                clean_code=round(clean_code_score, 2),
                role=role_percentages,
                markdown="",  # 나중에 전체 리포트로 채움
            )
            
            logger.info(f"✅ UserAnalysisResult 기본 생성 완료 (언어별 정보는 LLM이 생성 예정)")
            return result
            
        except Exception as e:
            logger.error(f"❌ UserAnalysisResult 생성 실패: {e}", exc_info=True)
            return None


    def _generate_synthesis_report(
        self,
        repo_summaries: List[Dict[str, Any]],
        total_commits: int,
        total_files: int,
        successful: int,
        failed: int,
        target_user: str | None,
        user_analysis_result: Optional[UserAnalysisResult] = None,
        llm_analysis: Optional[LLMAnalysisResult] = None,
    ) -> str:
        """종합 리포트 마크다운 생성"""
        
        is_single = len(repo_summaries) == 1
        title = "Repository Analysis - Synthesis Report" if is_single else "Multi-Repository Analysis - Synthesis Report"
        
        report = f"""# {title}

**생성 시간**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**분석 대상 유저**: {target_user if target_user else "전체 유저"}

---

## 📊 Executive Summary

- **총 레포지토리 수**: {len(repo_summaries)}개
- **성공**: {successful}개
- **실패**: {failed}개
- **총 분석 커밋 수**: {total_commits:,}개
- **총 분석 파일 수**: {total_files:,}개

---

"""

        # target_user가 있고 user_analysis_result가 있으면 추가
        if target_user and user_analysis_result:
            report += user_analysis_result.markdown
            report += "\n---\n\n"

        # LLM 분석 결과 추가
        if llm_analysis:
            report += "## 🤖 LLM 종합 분석 및 개선 방향\n\n"
            
            # 레벨 정보 (최상단 표시)
            if llm_analysis.level:
                level_info = llm_analysis.level
                report += "### 🎯 개발자 레벨\n\n"
                report += f"**레벨**: {level_info.get('level', 0)}\n"
                report += f"**총 경험치**: {level_info.get('experience', 0):,}\n"
                report += f"**현재 레벨 경험치**: {level_info.get('current_level_exp', 0):,} / {level_info.get('next_level_exp', 0):,}\n"
                report += f"**진행률**: {level_info.get('progress_percentage', 0):.1f}%\n\n"
            
            # 기술 스택 (레벨 다음 표시)
            if llm_analysis.tech_stack:
                report += "### 🛠️ 기술 스택\n\n"
                # 5개씩 줄바꿈하여 표시
                for i in range(0, len(llm_analysis.tech_stack), 5):
                    chunk = llm_analysis.tech_stack[i:i+5]
                    report += f"`{'` · `'.join(chunk)}`\n"
                report += "\n"
            
            report += f"### 종합 평가\n\n{llm_analysis.overall_assessment}\n\n"
            
            if llm_analysis.strengths:
                report += "### 강점 분석\n\n"
                for strength in llm_analysis.strengths:
                    report += f"- {strength}\n"
                report += "\n"
            
            if llm_analysis.improvement_recommendations:
                report += "### 개선 방향\n\n"
                for rec in llm_analysis.improvement_recommendations:
                    report += f"#### {rec.priority} - {rec.title}\n\n"
                    report += f"**카테고리**: {rec.category}\n\n"
                    report += f"{rec.description}\n\n"
                    if rec.action_items:
                        report += "**실행 가능한 액션**:\n"
                        for action in rec.action_items:
                            report += f"- {action}\n"
                    report += "\n"
            
            if llm_analysis.role_suitability:
                report += "### 역할 적합성 평가\n\n"
                for role, assessment in llm_analysis.role_suitability.items():
                    report += f"- **{role}**: {assessment}\n"
                report += "\n"

        # LLM 분석이 없는 경우 안내 메시지
        if not llm_analysis:
            report += "## 📝 Notes\n\n"
            report += "LLM 분석이 실패하여 상세 평가와 개선 방향을 제공할 수 없습니다.\n"

        return report

