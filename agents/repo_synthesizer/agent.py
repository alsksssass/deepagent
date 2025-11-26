"""RepoSynthesizerAgent - 여러 레포지토리 결과를 종합하는 에이전트"""

import logging
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from langchain_core.messages import SystemMessage, HumanMessage

from shared.storage import ResultStore
from shared.utils.prompt_loader import PromptLoader
from shared.utils.token_tracker import TokenTracker
from shared.utils.skill_level_calculator import SkillLevelCalculator
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
from agents.reporter.schemas import ReporterResponse

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

            # 3. UserAnalysisResult 생성
            user_analysis_result = await self._generate_user_analysis_result(
                context.repo_results,
                context.main_task_uuid,
                context.main_base_path,
            )
            context.user_analysis_result = user_analysis_result

            # 4. LLM 종합 분석 및 개선 방향 제시
            llm_analysis = await self._generate_llm_analysis(
                repo_summaries=repo_summaries,
                total_commits=total_commits,
                total_files=total_files,
                successful=successful,
                failed=failed,
                target_user=context.target_user,
                user_analysis_result=user_analysis_result,
                context=context,  # 디버깅용 context 전달
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

            # 6. UserAnalysisResult의 markdown, 언어별 정보 업데이트
            if user_analysis_result:
                user_analysis_result.markdown = report_content
                
                # LLM이 생성한 언어별 정보를 UserAnalysisResult에 동적 필드로 삽입
                if llm_analysis:
                    for attr_name in dir(llm_analysis):
                        if not attr_name.startswith('_') and attr_name not in [
                            'overall_assessment',
                            'strengths',
                            'improvement_recommendations',
                            'role_suitability',
                            'model_config',
                            'model_fields',
                            'model_computed_fields',
                            'model_dump',
                            'model_dump_json',
                            'model_validate',
                            'model_validate_json',
                            'model_copy',
                            'model_post_init',
                            'model_json_schema',
                            'model_parametrized_name',
                            'model_rebuild',
                            'model_fields_set'
                        ]:
                            attr_value = getattr(llm_analysis, attr_name, None)
                            # LanguageInfo 타입인지 확인
                            if isinstance(attr_value, dict) and all(
                                k in attr_value
                                for k in ['stack', 'level', 'exp']
                            ):
                                lang_info = LanguageInfo(**attr_value)
                                setattr(
                                    user_analysis_result,
                                    attr_name,
                                    lang_info
                                )
                                logger.info(
                                    f"   UserAnalysisResult.{attr_name} "
                                    f"업데이트 완료"
                                )
                            elif isinstance(attr_value, LanguageInfo):
                                setattr(
                                    user_analysis_result,
                                    attr_name,
                                    attr_value
                                )
                                logger.info(
                                    f"   UserAnalysisResult.{attr_name} "
                                    f"업데이트 완료"
                                )
                
                logger.info(
                    "   UserAnalysisResult.markdown에 "
                    "전체 리포트 내용 업데이트 완료"
                )

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
            import traceback
            logger.error(f"상세 Traceback:\n{traceback.format_exc()}")
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
                        logger.info(f"🔍 ResultStore 초기화 (요약 추출): task_uuid={task_uuid}, base_path={base_path}")
                        store = ResultStore(task_uuid, Path(base_path))
                        
                        # Reporter 결과 로드 (메타데이터)
                        reporter_response = None
                        try:
                            reporter_response = store.load_result("reporter", ReporterResponse)
                        except Exception:
                            pass
                        
                        # UserAggregator 결과 로드 (품질 점수 등)
                        user_agg_response = store.load_result("user_aggregator", UserAggregatorResponse)
                        user_agg = user_agg_response.model_dump() if user_agg_response else None
                        quality_score = None
                        if user_agg and user_agg.get("aggregate_stats"):
                            quality_stats = user_agg["aggregate_stats"].get("quality_stats", {})
                            quality_score = quality_stats.get("mean_score")
                        
                        # Reporter 메타데이터 추가
                        reporter_meta = None
                        if reporter_response:
                            reporter_dict = reporter_response.model_dump()
                            reporter_meta = {
                                "total_commits": reporter_dict.get("total_commits", 0),
                                "total_files": reporter_dict.get("total_files", 0),
                                "report_path": reporter_dict.get("report_path", ""),
                                "status": reporter_dict.get("status", ""),
                            }

                        summaries.append({
                            "git_url": result.get("git_url", ""),
                            "task_uuid": task_uuid,
                            "base_path": base_path,
                            "status": "success",
                            "total_commits": result.get("total_commits", 0),
                            "total_files": result.get("total_files", 0),
                            "final_report_path": result.get("final_report_path"),
                            "quality_score": quality_score,
                            "reporter_meta": reporter_meta,  # Reporter 메타데이터 추가
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
                    logger.warning(f"⚠️ ResultStore 로드 실패: {e} (task_uuid={task_uuid}, base_path={base_path})")
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
        context: Optional[Any] = None,  # RepoSynthesizerContext 전달용
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
            
            # 디버깅: LLM 응답 저장을 위한 경로 준비
            debug_store = None
            if context:
                from pathlib import Path
                from shared.storage import ResultStore
                try:
                    debug_store = ResultStore(context.main_task_uuid, Path(context.main_base_path))
                except Exception as e:
                    logger.debug(f"디버깅 저장소 초기화 실패: {e}")
            
            # LLM 호출 및 재시도 로직
            max_retries = 2
            analysis_data = None
            last_error = None
            llm_response_content = None
            
            for attempt in range(max_retries + 1):
                try:
                    response = await self.llm.ainvoke(messages)
                    TokenTracker.record_usage(
                        "repo_synthesizer",
                        response,
                        model_id=PromptLoader.get_model("repo_synthesizer")
                    )
                    
                    # 응답 검증
                    content = response.content if hasattr(response, 'content') else str(response)
                    llm_response_content = content  # 디버깅용 저장
                    
                    if not content or not content.strip():
                        if attempt < max_retries:
                            logger.warning(f"⚠️ LLM 응답이 비어있음 (시도 {attempt + 1}/{max_retries + 1}), 재시도...")
                            import asyncio
                            await asyncio.sleep(1)
                            continue
                        else:
                            logger.error("❌ LLM 응답이 비어있음 (최종 실패)")
                            # 디버깅: 빈 응답 저장
                            if debug_store:
                                try:
                                    debug_store.backend.save_debug_file("repo_synthesizer_llm_response_empty.txt", "")
                                except:
                                    pass
                            return None
                    
                    # JSON 추출 및 파싱 (섹션별 파싱 지원)
                    analysis_data = self._parse_llm_response(content)
                    if not analysis_data:
                        if attempt < max_retries:
                            logger.warning(f"⚠️ LLM 응답 파싱 실패 (시도 {attempt + 1}/{max_retries + 1}), 재시도...")
                            logger.info(f"   LLM 응답 내용 (처음 500자): {content[:500]}")
                            import asyncio
                            await asyncio.sleep(1)
                            continue
                        else:
                            logger.error("❌ LLM 응답 파싱 실패 (최종 실패)")
                            logger.error(f"   LLM 응답 내용 (처음 1000자): {content[:1000]}")
                            # 디버깅: JSON 추출 실패 응답 저장
                            if debug_store:
                                try:
                                    debug_store.backend.save_debug_file("repo_synthesizer_llm_response_no_json.txt", content)
                                except:
                                    pass
                            return None
                    
                    # 디버깅: 성공한 JSON 저장
                    if debug_store:
                        try:
                            debug_store.backend.save_debug_file("repo_synthesizer_llm_response_raw.txt", content)
                            debug_store.backend.save_debug_file("repo_synthesizer_llm_response_parsed.json", json.dumps(analysis_data, indent=2, ensure_ascii=False))
                        except:
                            pass
                    
                    break  # 성공 시 루프 종료
                    
                except json.JSONDecodeError as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warning(f"⚠️ LLM 응답 JSON 파싱 실패 (시도 {attempt + 1}/{max_retries + 1}): {e}")
                        import asyncio
                        await asyncio.sleep(1)
                    else:
                        logger.warning(f"⚠️ LLM 응답 JSON 파싱 최종 실패: {e}")
                        logger.error(f"   응답 내용 (처음 1000자): {content[:1000] if 'content' in locals() else 'N/A'}")
                        return None
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warning(f"⚠️ LLM 호출 실패 (시도 {attempt + 1}/{max_retries + 1}): {e}")
                        import asyncio
                        await asyncio.sleep(1)
                    else:
                        logger.error(f"❌ LLM 호출 최종 실패: {e}")
                        return None
            
            # analysis_data가 None이면 실패
            if analysis_data is None:
                logger.warning("⚠️ LLM 분석: analysis_data가 None입니다")
                return None
            
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
                    from pydantic import ValidationError
                    if isinstance(validation_error, ValidationError):
                        error_count = len(validation_error.errors())
                        logger.warning(f"⚠️ LLM 응답 검증 실패: {error_count} validation errors for LLMAnalysisResult")
                        for err in validation_error.errors():
                            logger.warning(f"  - Field: {'.'.join(str(loc) for loc in err['loc'])}, Type: {err['type']}, Msg: {err['msg']}")
                    else:
                        logger.warning(f"⚠️ LLM 응답 검증 실패: {validation_error}")
                    
                    # 디버깅: 검증 실패한 데이터 저장
                    if debug_store:
                        try:
                            debug_store.backend.save_debug_file("repo_synthesizer_llm_response_validation_failed.json", json.dumps(analysis_data, indent=2, ensure_ascii=False))
                            if llm_response_content:
                                debug_store.backend.save_debug_file("repo_synthesizer_llm_response_raw_validation_failed.txt", llm_response_content)
                        except:
                            pass
                    
                    logger.info(f"   검증 실패한 데이터 키: {list(analysis_data.keys()) if analysis_data else 'None'}")
                    logger.info(f"   응답 데이터 (처음 2000자): {json.dumps(analysis_data, indent=2, ensure_ascii=False)[:2000]}")
                    # 기본값으로 재시도
                    try:
                        # 필수 필드가 없는 경우 기본값으로 채우기
                        if "overall_assessment" not in analysis_data:
                            analysis_data["overall_assessment"] = "분석 결과를 생성할 수 없습니다."
                        if "strengths" not in analysis_data:
                            analysis_data["strengths"] = []
                        if "improvement_recommendations" not in analysis_data:
                            analysis_data["improvement_recommendations"] = []

                        # role_suitability 필수 5개 역할 확인
                        if "role_suitability" not in analysis_data:
                            analysis_data["role_suitability"] = {}
                        required_roles = ["Backend", "Frontend", "DevOps", "Data Science", "Fullstack"]
                        for role in required_roles:
                            if role not in analysis_data["role_suitability"]:
                                analysis_data["role_suitability"][role] = f"{role} (평가 불가): 데이터 부족"

                        # hiring_decision 필수 필드 확인
                        if "hiring_decision" not in analysis_data:
                            analysis_data["hiring_decision"] = {}
                        hiring = analysis_data["hiring_decision"]

                        if "immediate_readiness" not in hiring:
                            hiring["immediate_readiness"] = "평가 불가"
                        if "onboarding_period" not in hiring:
                            hiring["onboarding_period"] = "미정"
                        if "hiring_recommendation" not in hiring:
                            hiring["hiring_recommendation"] = "신중 검토"
                        if "hiring_decision_reason" not in hiring:
                            hiring["hiring_decision_reason"] = "분석 데이터가 충분하지 않아 정확한 평가가 어렵습니다."
                        if "salary_recommendation" not in hiring:
                            hiring["salary_recommendation"] = "데이터 부족으로 평가 불가"
                        if "estimated_salary_range" not in hiring:
                            hiring["estimated_salary_range"] = "평가 불가"
                        if "technical_risks" not in hiring:
                            hiring["technical_risks"] = []
                        if "expected_contributions" not in hiring:
                            hiring["expected_contributions"] = []

                        llm_result = LLMAnalysisResult(**analysis_data)
                        logger.info("✅ LLM 종합 분석 완료 (기본값 보완)")
                        return llm_result
                    except Exception as e2:
                        logger.warning(f"⚠️ LLM 응답 복구 실패: {e2}")
                        return None
                
                
        except Exception as e:
            logger.error(f"❌ LLM 분석 실패: {e}", exc_info=True)
            return None

    def _extract_json_from_response(self, content: str) -> Optional[str]:
        """
        LLM 응답에서 JSON 문자열 추출 (JSONExtractor 사용)
        
        Args:
            content: LLM 응답 내용
            
        Returns:
            추출된 JSON 문자열 또는 None
        """
        from shared.utils.json_extractor import JSONExtractor
        return JSONExtractor.extract(content)
    
    def _parse_llm_response(self, content: str) -> Optional[Dict[str, Any]]:
        """
        LLM 응답을 파싱하여 LLMAnalysisResult 형식의 딕셔너리로 변환
        
        LLM이 마크다운 형식으로 섹션별로 나누어 반환하는 경우를 처리:
        - ### 1️⃣ overall_assessment: 코드 블록 안의 문자열
        - ### 2️⃣ strengths: JSON 배열
        - ### 3️⃣ improvement_recommendations: JSON 배열
        - ### 4️⃣ role_suitability: JSON 객체
        - ### 5️⃣ hiring_decision: JSON 객체
        - ### 6️⃣ 언어별 정보: JSON 객체
        
        Args:
            content: LLM 응답 내용
            
        Returns:
            파싱된 딕셔너리 또는 None
        """
        import re
        import json
        
        result = {}
        
        try:
            # 1. overall_assessment 추출 (코드 블록 안의 문자열)
            # 패턴: ### 1️⃣ overall_assessment 다음에 ```로 시작하는 코드 블록 (언어 식별자 허용)
            overall_match = re.search(r"###\s*1[️⃣1]\s*overall_assessment\s*\n```(?:markdown)?\s*\n(.*?)\n```", content, re.DOTALL | re.IGNORECASE)
            if overall_match:
                result["overall_assessment"] = overall_match.group(1).strip()
            else:
                # 대체 패턴: ``` 없이 직접 텍스트 또는 ```가 포함된 텍스트
                overall_match = re.search(r"###\s*1[️⃣1]\s*overall_assessment\s*\n(.*?)(?=###|\Z)", content, re.DOTALL)
                if overall_match:
                    text = overall_match.group(1).strip()
                    # 만약 텍스트가 ```로 감싸져 있다면 제거
                    if text.startswith("```") and text.endswith("```"):
                        # 첫 줄(```markdown 등)과 마지막 줄(```) 제거
                        lines = text.split('\n')
                        if len(lines) >= 2:
                            result["overall_assessment"] = '\n'.join(lines[1:-1]).strip()
                        else:
                            result["overall_assessment"] = text.strip('`').strip()
                    else:
                        result["overall_assessment"] = text
            
            # 2. strengths 추출 (JSON 배열)
            # 패턴: ### 2️⃣ strengths 다음에 ```json으로 시작하는 코드 블록
            strengths_match = re.search(r"###\s*2[️⃣2]\s*strengths\s*\n```json\s*\n(\[.*?\])\s*\n```", content, re.DOTALL)
            if strengths_match:
                try:
                    strengths_json = json.loads(strengths_match.group(1))
                    # strengths는 List[str]이므로 각 항목을 문자열로 변환
                    result["strengths"] = [
                        f"✅ {item.get('title', '')}: {item.get('description', '')}" 
                        if isinstance(item, dict) else str(item)
                        for item in strengths_json
                    ]
                except json.JSONDecodeError:
                    logger.warning("⚠️ strengths JSON 파싱 실패")
            
            # 3. improvement_recommendations 추출 (JSON 배열)
            improvements_match = re.search(r"###\s*3[️⃣3]\s*improvement_recommendations\s*\n```json\s*\n(\[.*?\])\s*\n```", content, re.DOTALL)
            if improvements_match:
                try:
                    result["improvement_recommendations"] = json.loads(improvements_match.group(1))
                except json.JSONDecodeError:
                    logger.warning("⚠️ improvement_recommendations JSON 파싱 실패")
            
            # 4. role_suitability 추출 (JSON 객체)
            # 중괄호 매칭으로 완전한 JSON 객체 추출
            role_section = re.search(r"###\s*4[️⃣4]\s*role_suitability\s*\n```json\s*\n(\{.*)", content, re.DOTALL)
            if role_section:
                brace_start = content.find("{", role_section.start())
                if brace_start != -1:
                    brace_count = 0
                    for i in range(brace_start, len(content)):
                        if content[i] == "{":
                            brace_count += 1
                        elif content[i] == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                json_str = content[brace_start:i+1]
                                try:
                                    result["role_suitability"] = json.loads(json_str)
                                except json.JSONDecodeError:
                                    logger.warning("⚠️ role_suitability JSON 파싱 실패")
                                break
            
            # 5. hiring_decision 추출 (JSON 객체)
            # 중괄호 매칭으로 완전한 JSON 객체 추출
            hiring_section = re.search(r"###\s*5[️⃣5]\s*hiring_decision\s*\n```json\s*\n(\{.*)", content, re.DOTALL)
            if hiring_section:
                brace_start = content.find("{", hiring_section.start())
                if brace_start != -1:
                    brace_count = 0
                    for i in range(brace_start, len(content)):
                        if content[i] == "{":
                            brace_count += 1
                        elif content[i] == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                json_str = content[brace_start:i+1]
                                try:
                                    result["hiring_decision"] = json.loads(json_str)
                                except json.JSONDecodeError:
                                    logger.warning("⚠️ hiring_decision JSON 파싱 실패")
                                break
            
            # 6. 언어별 정보 추출 (JSON 객체)
            lang_section = re.search(r"###\s*6[️⃣6]\s*언어별\s*상세\s*정보\s*\n```json\s*\n(\{.*)", content, re.DOTALL)
            if lang_section:
                brace_start = content.find("{", lang_section.start())
                if brace_start != -1:
                    brace_count = 0
                    for i in range(brace_start, len(content)):
                        if content[i] == "{":
                            brace_count += 1
                        elif content[i] == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                json_str = content[brace_start:i+1]
                                try:
                                    lang_data = json.loads(json_str)
                                    # 동적 필드로 추가
                                    for lang, info in lang_data.items():
                                        result[lang] = info
                                except json.JSONDecodeError:
                                    logger.warning("⚠️ 언어별 정보 JSON 파싱 실패")
                                break
            
            # 전체 JSON 객체가 있는 경우 (섹션별 파싱 실패 시 대체)
            if not result:
                json_str = self._extract_json_from_response(content)
                if json_str:
                    try:
                        result = json.loads(json_str)
                    except json.JSONDecodeError:
                        pass
            
            # 필수 필드가 모두 있는지 확인
            if "overall_assessment" in result and "role_suitability" in result and "hiring_decision" in result:
                logger.debug("✅ LLM 응답 섹션별 파싱 성공")
                return result
            else:
                logger.warning(f"⚠️ LLM 응답 파싱: 필수 필드 누락. 파싱된 키: {list(result.keys())}")
                return result if result else None
                
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ LLM 응답 JSON 파싱 오류: {e}")
            return None
        except Exception as e:
            logger.warning(f"⚠️ LLM 응답 파싱 중 오류: {e}", exc_info=True)
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
                logger.info(f"🔍 ResultStore 초기화 (JSON 수집): task_uuid={task_uuid}, base_path={base_path}")
                store = ResultStore(task_uuid, Path(base_path))
                
                # 주요 분석 결과 로드
                repo_data = {
                    "git_url": git_url,
                    "task_uuid": task_uuid,
                }
                
                # Reporter 결과 (메타데이터)
                try:
                    reporter_response = store.load_result("reporter", ReporterResponse)
                    if reporter_response:
                        reporter_dict = reporter_response.model_dump()
                        # 리포트 메타데이터 포함
                        repo_data["reporter"] = {
                            "total_commits": reporter_dict.get("total_commits", 0),
                            "total_files": reporter_dict.get("total_files", 0),
                            "report_path": reporter_dict.get("report_path", ""),
                            "status": reporter_dict.get("status", ""),
                        }
                except Exception as e:
                    logger.debug(f"Reporter 로드 실패: {e}")
                
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
            formatted.append(f"\n🚨 역할별 기술스택 보유율 (정확한 수치 - role_suitability에서 반드시 이 값을 사용):")
            for role, percentage in sorted(user_analysis_result.role.items(), key=lambda x: x[1], reverse=True):
                formatted.append(f"  - {role}: {percentage:.1f}% ← role_suitability에서 이 정확한 퍼센트를 사용하세요!")

            formatted.append(f"\n⚠️ 중요: role_suitability 작성 시 위의 퍼센트 값을 정확히 복사하여 사용하세요.")
            formatted.append(f"예시: \"Backend ({user_analysis_result.role.get('Backend', 0.0):.1f}%): [평가 내용]\"")

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
            all_skills = []  # 모든 레포의 스킬 데이터 (중복 포함)
            all_tech_stack = set()  # 전체 기술 스택 (중복 제거용)
            
            for result in repo_results:
                if result.get("error_message"):
                    continue
                    
                task_uuid = result.get("task_uuid", "")
                base_path = result.get("base_path", "")
                
                if not task_uuid or not base_path:
                    continue
                
                try:
                    store = ResultStore(task_uuid, Path(base_path))
                    logger.info(f"📂 RepoSynthesizer 데이터 로드 시작: task_uuid={task_uuid}")
                    logger.info(f"   base_path: {base_path}")
                    logger.info(f"   ResultStore results_dir: {store.results_dir}")
                    
                    # total_skill.json 로드 (일반 JSON 파일)
                    try:
                        import json
                        logger.info(f"   📥 total_skill.json 로드 시도: {base_path}/total_skill.json")
                        total_skill_content = store.load_debug_file("total_skill.json")
                        total_skill_data = json.loads(total_skill_content)
                        if isinstance(total_skill_data, list):
                            all_skills += total_skill_data
                            logger.info(f"   ✅ total_skill.json 로드 성공: {len(total_skill_data)}개 스킬")
                        else:
                            logger.debug(f"total_skill.json이 리스트 형식이 아님: {type(total_skill_data)}")
                    except FileNotFoundError:
                        logger.warning(f"   ⚠️ total_skill.json 파일 없음: task_uuid={task_uuid}, base_path={base_path}")
                    except Exception as e:
                        logger.warning(f"   ⚠️ total_skill.json 로드 실패: {e}, base_path={base_path}")
                    
                    
                    # 1. UserAggregator 결과에서 품질 점수 수집
                    try:
                        logger.info(f"   📥 user_aggregator.json 로드 시도: {store.results_dir}/user_aggregator.json")
                        user_agg_response = store.load_result("user_aggregator", UserAggregatorResponse)
                        user_agg = user_agg_response.model_dump() if user_agg_response else None
                        if user_agg and user_agg.get("aggregate_stats"):
                            quality_stats = user_agg["aggregate_stats"].get("quality_stats", {})
                            avg_score = quality_stats.get("average_score")
                            if avg_score is not None:
                                all_quality_scores.append(avg_score)
                                logger.info(f"   ✅ user_aggregator.json 로드 성공: 품질 점수={avg_score}")
                        else:
                            logger.warning(f"   ⚠️ user_aggregator 결과에 aggregate_stats 없음")
                    except Exception as e:
                        logger.warning(f"   ⚠️ user_aggregator.json 로드 실패: {e}")
                    
                    # 2. UserSkillProfiler 결과에서 스킬 데이터 수집
                    try:
                        logger.info(f"   📥 user_skill_profiler.json 로드 시도: {store.results_dir}/user_skill_profiler.json")
                        skill_profile_response = store.load_result("user_skill_profiler", UserSkillProfilerResponse)
                        skill_profile = skill_profile_response.model_dump() if skill_profile_response else None
                        if skill_profile:
                            logger.info(f"   ✅ user_skill_profiler.json 로드 성공")
                        else:
                            logger.warning(f"   ⚠️ user_skill_profiler 결과가 None")
                    except Exception as e:
                        logger.warning(f"   ⚠️ user_skill_profiler.json 로드 실패: {e}")
                        skill_profile = None
                    
                    if skill_profile and skill_profile.get("skill_profile"):
                        # top_skills에서 스킬 정보 추출
                        top_skills = skill_profile["skill_profile"].get("top_skills", [])
                        logger.info(f"   📊 top_skills 수집: {len(top_skills)}개")
                        for skill in top_skills:
                            # all_skills에 추가 (레벨 계산용)
                            # top_skills는 이미 base_score를 포함한 스킬 객체
                            all_skills.append(skill)
                            
                            # 기술 스택 추가 (중복 제거)
                            skill_category = skill.get("category", "")
                            if skill_category:
                                all_tech_stack.add(skill_category)
                        logger.info(f"   ✅ top_skills를 all_skills에 추가 완료: {len(top_skills)}개")
                
                except Exception as e:
                    logger.warning(f"⚠️ 레포지토리 {task_uuid} 데이터 수집 실패: {e}")
                    continue
            
            # 데이터 집계
            logger.info(f"   품질 점수: {len(all_quality_scores)}개")
            logger.info(f"   수집된 스킬: {len(all_skills)}개 (중복 포함)")
            logger.info(f"   고유 기술 스택: {len(all_tech_stack)}개")
            
            # 1. clean_code 점수 계산 (평균)
            clean_code_score = 0.0
            if all_quality_scores:
                clean_code_score = sum(all_quality_scores) / len(all_quality_scores)
            
            # 2. SkillLevelCalculator로 정확한 레벨 계산
            total_experience = SkillLevelCalculator.calculate_total_experience(all_skills)
            logger.info(f"   모든 스킬: {all_skills}")
            level_info = SkillLevelCalculator.calculate_level(total_experience)
            
            logger.info(f"   총 경험치: {total_experience:,} EXP")
            logger.info(f"   레벨: {level_info['level']} ({level_info['level_name']})")
            
            # 3. 개발자 타입별 커버리지 및 레벨 계산
            chromadb_persist_dir = os.getenv(
                "CHROMADB_PERSIST_DIR", str(Path(main_base_path).parent.parent / "chroma_db_skill_charts")
            )
            developer_type_coverage = await SkillLevelCalculator.calculate_developer_type_coverage(
                all_skills, chromadb_persist_dir
            )
            
            # developer_type_coverage가 None이거나 비어있을 경우 처리
            if developer_type_coverage is None:
                developer_type_coverage = {}
                logger.warning("⚠️ 개발자 타입별 커버리지 계산 실패, 빈 dict 사용")
            
            # 4. role 퍼센트 계산
            role_percentages = {}
            for role, coverage_data in developer_type_coverage.items():
                percentage = coverage_data.get("percentage", 0)
                role_percentages[role] = float(percentage)
            
            logger.info(f"   역할별 커버리지: {list(role_percentages.keys())}")
            
            # UserAnalysisResult 생성
            result = UserAnalysisResult(
                python=LanguageInfo(),  # 빈 초기값 (언어별 정보는 LLM이 채움)
                clean_code=round(clean_code_score, 2),
                role=role_percentages,
                markdown="",  # 나중에 전체 리포트로 채움
                level=level_info,  # 정확한 레벨 정보
                tech_stack=sorted(list(all_tech_stack)) if all_tech_stack else [],  # 전체 기술 스택
            )
            
            logger.info(f"✅ UserAnalysisResult 생성 완료 (정확한 레벨 계산)")
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
        if user_analysis_result:
            # 레벨 정보 먼저 표시 (UserAnalysisResult에서 가져옴)
            if user_analysis_result.level:
                level_info = user_analysis_result.level
                report += "## 🎯 개발자 레벨\n\n"
                report += f"**레벨**: {level_info.get('level', 0)}\n"
                report += (
                    f"**총 경험치**: "
                    f"{level_info.get('experience', 0):,}\n"
                )
                report += (
                    f"**현재 레벨 경험치**: "
                    f"{level_info.get('current_level_exp', 0):,} / "
                    f"{level_info.get('next_level_exp', 0):,}\n"
                )
                report += (
                    f"**진행률**: "
                    f"{level_info.get('progress_percentage', 0):.1f}%\n\n"
                )
            
            # 기술 스택 표시 (UserAnalysisResult에서 가져옴)
            if user_analysis_result.tech_stack and len(user_analysis_result.tech_stack) > 0:
                report += "기술 스택\n\n"
                # 5개씩 줄바꾸어 표시
                for i in range(0, len(user_analysis_result.tech_stack), 5):
                    chunk = user_analysis_result.tech_stack[i:i+5]
                    report += f"`{'` · `'.join(chunk)}`\n"
                report += "\n"
            
            report += user_analysis_result.markdown
            report += "\n---\n\n"

        # LLM 분석 결과 추가
        if llm_analysis:
            report += "## 🤖 LLM 종합 분석 및 개선 방향\n\n"
            
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
            
            # hiring_decision 섹션 추가 (프롬프트에서 가장 중요하다고 강조)
            if llm_analysis.hiring_decision:
                report += "### 💼 채용 의견 및 투입 가능성 평가\n\n"
                hiring = llm_analysis.hiring_decision
                
                report += f"**즉시 투입 가능성**: {hiring.immediate_readiness}\n"
                report += f"**예상 온보딩 기간**: {hiring.onboarding_period}\n"
                report += f"**채용 추천 의견**: {hiring.hiring_recommendation}\n\n"
                
                report += f"**채용 의견 근거**:\n{hiring.hiring_decision_reason}\n\n"
                
                if hiring.technical_risks:
                    report += "**예상 기술적 리스크**:\n"
                    for risk in hiring.technical_risks:
                        report += f"- {risk}\n"
                    report += "\n"
                
                if hiring.expected_contributions:
                    report += "**기대 기여**:\n"
                    for contribution in hiring.expected_contributions:
                        report += f"- {contribution}\n"
                    report += "\n"
                
                report += f"**급여 레벨 추천**: {hiring.salary_recommendation}\n"
                report += f"**예상 적정 연봉**: {hiring.estimated_salary_range}\n\n"
            
            # 언어별 상세 정보 추가 (동적 필드)
            language_fields = {}
            if llm_analysis:
                # LLMAnalysisResult의 동적 필드에서 언어별 정보 추출
                for field_name in llm_analysis.model_fields_set:
                    if field_name not in [
                        'overall_assessment', 'strengths', 'improvement_recommendations',
                        'role_suitability', 'hiring_decision'
                    ]:
                        field_value = getattr(llm_analysis, field_name, None)
                        if isinstance(field_value, dict) and all(
                            k in field_value for k in ['stack', 'level', 'exp', 'usage_frequency']
                        ):
                            language_fields[field_name] = field_value
            
            # UserAnalysisResult에서도 언어별 정보 확인
            if user_analysis_result:
                for field_name in dir(user_analysis_result):
                    if not field_name.startswith('_') and field_name not in [
                        'python', 'clean_code', 'role', 'markdown', 'level', 'tech_stack',
                        'model_config', 'model_fields', 'model_computed_fields',
                        'model_dump', 'model_dump_json', 'model_validate', 'model_validate_json',
                        'model_copy', 'model_post_init', 'model_json_schema',
                        'model_parametrized_name', 'model_rebuild', 'model_fields_set'
                    ]:
                        field_value = getattr(user_analysis_result, field_name, None)
                        if isinstance(field_value, LanguageInfo):
                            language_fields[field_name] = {
                                'stack': field_value.stack,
                                'level': field_value.level,
                                'exp': field_value.exp,
                                'usage_frequency': field_value.usage_frequency
                            }
                # python 필드도 확인
                if user_analysis_result.python and user_analysis_result.python.level > 0:
                    language_fields['python'] = {
                        'stack': user_analysis_result.python.stack,
                        'level': user_analysis_result.python.level,
                        'exp': user_analysis_result.python.exp,
                        'usage_frequency': user_analysis_result.python.usage_frequency
                    }
            
            # 언어별 상세 정보 표시
            if language_fields:
                report += "### 📊 언어별 상세 정보\n\n"
                report += "| 언어 | 숙련도 | 경험치 | 사용 빈도 | 기술 스택 |\n"
                report += "|------|--------|--------|-----------|----------|\n"
                for lang, info in language_fields.items():
                    level_stars = "⭐" * min(5, (info.get('level', 0) // 20))
                    stack_str = ", ".join(info.get('stack', [])[:3])  # 최대 3개만 표시
                    if len(info.get('stack', [])) > 3:
                        stack_str += f" 외 {len(info.get('stack', [])) - 3}개"
                    report += f"| {lang.capitalize()} | {level_stars} ({info.get('level', 0)}/100) | {info.get('exp', 0):,} | {info.get('usage_frequency', 0)}% | {stack_str} |\n"
                report += "\n"
            
            # 시각화 요소 추가 (프롬프트에서 요구)
            if user_analysis_result and user_analysis_result.role:
                report += "### 📈 분야별 역량 차트\n\n"
                # 역할별 보유율을 차트로 표시
                for role, percentage in sorted(user_analysis_result.role.items(), key=lambda x: x[1], reverse=True):
                    if percentage > 0:
                        bar_length = int(percentage / 5)  # 5%당 1칸
                        filled = "█" * bar_length
                        empty = "░" * (20 - bar_length)
                        report += f"{role:<15} {filled}{empty} {percentage:.1f}%\n"
                report += "\n"

        # LLM 분석이 없는 경우 안내 메시지
        if not llm_analysis:
            report += "## 📝 Notes\n\n"
            report += "LLM 분석이 실패하여 상세 평가와 개선 방향을 제공할 수 없습니다.\n"

        return report

