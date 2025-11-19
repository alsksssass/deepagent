"""UserSkillProfiler Agent - 개발자 스킬 프로파일링"""

import logging
import asyncio
import json
from typing import Any, Tuple, List
from collections import defaultdict
import chromadb

from pathlib import Path
from shared.tools.skill_tools import search_skills_by_code, calculate_category_coverage
from shared.tools.chromadb_tools import get_chroma_client
from shared.utils.prompt_loader import PromptLoader
from shared.utils.agent_logging import log_agent_execution
from shared.utils.agent_debug_logger import AgentDebugLogger
from shared.utils.skill_level_calculator import SkillLevelCalculator
from shared.storage import ResultStore

from .schemas import (
    UserSkillProfilerContext,
    UserSkillProfilerResponse,
    SkillProfileData,
    HybridConfig,
    SkillMatch,
    MissingSkillInfo,
    SkillAnalysisOutput,
)

logger = logging.getLogger(__name__)


class UserSkillProfilerAgent:
    """
    사용자의 커밋 코드를 분석하여 Skill Profile을 생성하는 에이전트

    Level 2 병렬 처리:
    - 코드 임베딩 검색 (ChromaDB code collection)
    - 스킬 매칭 (ChromaDB skill_charts collection)
    - 카테고리별 통계 집계

    Dynamic 2-Tier 아키텍처:
    - Level 0 (Coordinator): UserSkillProfiler - 배치 생성 및 결과 집계
    - Level 1 (Worker): CodeBatchProcessorAgent - 10개 코드 배치 병렬 처리
    - SmartBatcher: 균등 부하 분산 (최대 차이 ≤ 1)
    - 계층적 재시도: Level 1 (3회) + Level 0 (실패 배치 재처리)
    """

    def __init__(self, task_uuid: str = None):
        # Task UUID 저장 (CodeBatchProcessor에게 전달)
        self.task_uuid = task_uuid

        # PromptLoader로 LLM 로드
        self.llm = PromptLoader.get_llm("user_skill_profiler")
        model_id = PromptLoader.get_model("user_skill_profiler")

        # 하이브리드: 스키마 자동 주입
        self.prompts = PromptLoader.load_with_schema(
            "user_skill_profiler",
            response_schema_class=SkillAnalysisOutput
        )

        # Tool binding
        from shared.tools.skill_tools import (
            search_skills_by_code,
            get_skill_by_name,
            get_skills_by_category,
        )

        self.llm_with_tools = self.llm.bind_tools(
            [
                search_skills_by_code,
                get_skill_by_name,
                get_skills_by_category,
            ]
        )

        # Structured Output: Force Pydantic schema compliance for 95% success rate
        self.llm_structured = self.llm_with_tools.with_structured_output(
            SkillAnalysisOutput, method="function_calling"
        )

        logger.info(f"✅ UserSkillProfiler: LLM with structured output 초기화 완료 - {model_id}")

    @log_agent_execution(agent_name="user_skill_profiler")
    async def run(self, context: UserSkillProfilerContext) -> UserSkillProfilerResponse:
        """
        사용자 스킬 프로파일 생성

        Args:
            context: UserSkillProfilerContext

        Returns:
            UserSkillProfilerResponse
        """
        user = context.user
        task_uuid = context.task_uuid
        persist_dir = context.persist_dir  # 스킬 차트용
        code_persist_dir = context.code_persist_dir or persist_dir  # 코드 컬렉션용

        # task_uuid를 인스턴스 변수에 저장 (CodeBatchProcessor에게 전달용)
        if not self.task_uuid:
            self.task_uuid = task_uuid

        logger.info(f"🎯 UserSkillProfiler: {user} 스킬 프로파일 생성 시작")

        # ResultStore 초기화 (배치 결과 저장용)
        base_path = Path(context.result_store_path).parent if context.result_store_path else Path(f"./data/analyze/{task_uuid}")
        result_store = ResultStore(task_uuid, base_path)
        
        # 중간 단계 로깅을 위해 logger 가져오기
        debug_logger = AgentDebugLogger.get_logger(task_uuid, base_path, "user_skill_profiler")

        # 환경변수에서 하이브리드 설정 로드
        if context.enable_hybrid and context.hybrid_config is None:
            context.hybrid_config = HybridConfig.from_env()
            logger.info(
                f"⚙️ 하이브리드 설정 로드: "
                f"concurrent={context.hybrid_config.llm_max_concurrent}, "
                f"batch={context.hybrid_config.llm_batch_size}, "
                f"candidates={context.hybrid_config.skill_candidate_count}"
            )

        try:
            # Level 2-1: 유저 코드 수집 (ChromaDB code collection)
            user_code_samples = await self._collect_user_code(task_uuid, code_persist_dir)
            
            # 중간 단계 로깅
            debug_logger.log_intermediate("code_collection", {
                "sample_count": len(user_code_samples) if user_code_samples else 0,
                "samples_preview": user_code_samples[:3] if user_code_samples else []  # 샘플만
            })

            if not user_code_samples:
                logger.warning(f"⚠️ {user}: 코드 샘플 없음")
                response = UserSkillProfilerResponse(
                    status="failed",
                    user=user,
                    skill_profile=SkillProfileData(),
                    error="No code samples found",
                )
                debug_logger.log_response(response)
                return response

            # Level 2-2: 코드 → 스킬 매칭
            detected_skills = []
            missing_skills = []

            if context.enable_hybrid:
                # 하이브리드 매칭: 임베딩 후보 + LLM 판단
                detected_skills, missing_skills = await self._hybrid_match_parallel(
                    user_code_samples,
                    persist_dir,  # 스킬 차트용
                    context.hybrid_config,
                    result_store=result_store,
                )
            else:
                # 기존 임베딩 매칭
                detected_skills = await self._match_skills_parallel(user_code_samples, persist_dir)  # 스킬 차트용

            # Level 2-2.5: 미등록 스킬 로깅
            missing_log_path = None
            if missing_skills and context.result_store_path:
                from .missing_skills_logger import MissingSkillsLogger

                logger_instance = MissingSkillsLogger(context.result_store_path)
                missing_log_path = logger_instance.save_missing_skills(
                    missing_skills,
                    task_uuid,
                )
                logger.info(f"📝 미등록 스킬 {len(missing_skills)}개 로그 저장: {missing_log_path}")

            # Level 2-3: 스킬 통계 집계
            skill_profile_data = await self._aggregate_skill_profile(detected_skills, persist_dir)
            
            # 중간 단계 로깅
            debug_logger.log_intermediate("skill_matching", {
                "detected_skills_count": len(detected_skills),
                "missing_skills_count": len(missing_skills),
            })
            debug_logger.log_intermediate("aggregation", {
                "total_skills": skill_profile_data.get("total_skills", 0),
                "total_coverage": skill_profile_data.get("total_coverage", 0),
            })

            # Pydantic 모델로 변환
            skill_profile = SkillProfileData(**skill_profile_data)

            logger.info(
                f"✅ UserSkillProfiler: {user} - "
                f"{skill_profile.total_skills}개 스킬 프로파일 완료 "
                f"(미등록: {len(missing_skills)}개)"
            )

            response = UserSkillProfilerResponse(
                status="success",
                user=user,
                skill_profile=skill_profile,
                missing_skills_log_path=missing_log_path,
                hybrid_stats=(
                    {
                        "total_analyzed": len(user_code_samples),
                        "skills_found": len(detected_skills),
                        "missing_skills": len(missing_skills),
                        "hybrid_enabled": context.enable_hybrid,
                    }
                    if context.enable_hybrid
                    else None
                ),
            )
            
            # 최종 응답 로깅 (데코레이터가 자동으로 처리하지만, 중간 단계 로깅을 위해 유지)
            debug_logger.log_response(response)
            return response

        except Exception as e:
            logger.error(f"❌ UserSkillProfiler: {e}", exc_info=True)
            error_response = UserSkillProfilerResponse(
                status="failed",
                user=user,
                skill_profile=SkillProfileData(),
                error=str(e),
            )
            debug_logger.log_response(error_response)
            return error_response

    async def _collect_user_code(self, task_uuid: str, persist_dir: str) -> list[dict[str, Any]]:
        """
        ChromaDB code collection에서 유저 코드 샘플 수집

        Returns:
            코드 샘플 리스트 (각 샘플은 {"code": str, "file": str, "line_start": int, "line_end": int})
        """
        try:
            # ChromaDB 클라이언트 (싱글톤 사용)
            client = get_chroma_client(persist_dir)

            collection_name = f"code_{task_uuid}"
            collection = client.get_collection(name=collection_name)

            # 전체 코드와 메타데이터 가져오기
            results = collection.get(include=["documents", "metadatas"])
            documents = results["documents"]
            metadatas = results["metadatas"]

            # 코드 + 메타데이터 결합
            code_samples = []
            for i, doc in enumerate(documents):
                metadata = metadatas[i] if i < len(metadatas) else {}
                code_samples.append(
                    {
                        "code": doc,
                        "file": metadata.get("file", "unknown"),
                        "line_start": metadata.get("line_start", 0),
                        "line_end": metadata.get("line_end", 0),
                    }
                )

            logger.info(f"📂 {len(code_samples)}개 코드 샘플 수집 (파일 경로/라인 번호 포함)")
            return code_samples

        except Exception as e:
            logger.error(f"❌ 코드 수집 실패: {e}")
            return []

    async def _match_skills_parallel(
        self, code_samples: list[dict[str, Any]], persist_dir: str
    ) -> list[dict[str, Any]]:
        """
        코드 샘플들을 병렬로 스킬 매칭

        Returns:
            매칭된 스킬 리스트
        """
        # 배치 크기 (너무 많으면 병렬 처리 부담)
        batch_size = 10
        all_skills = []

        for i in range(0, len(code_samples), batch_size):
            batch = code_samples[i : i + batch_size]

            # 병렬 스킬 검색
            batch_results = await asyncio.gather(
                *[
                    search_skills_by_code.ainvoke(
                        {
                            "code_snippet": sample["code"],
                            "n_results": 5,  # 각 코드당 상위 5개 스킬
                            "persist_dir": persist_dir,
                        }
                    )
                    for sample in batch
                ]
            )

            # 결과 병합
            for skills in batch_results:
                all_skills.extend(skills)

            logger.info(f"🔍 {i + len(batch)}/{len(code_samples)} 코드 스킬 매칭 완료")

        # 중복 제거 및 신뢰도 필터링
        unique_skills = self._deduplicate_skills(all_skills)

        logger.info(f"✅ 총 {len(unique_skills)}개 고유 스킬 발견")
        return unique_skills

    async def _hybrid_match_parallel(
        self,
        code_samples: List[dict[str, Any]],
        persist_dir: str,
        config: HybridConfig,
        result_store: ResultStore = None,
    ) -> Tuple[List[dict[str, Any]], List[MissingSkillInfo]]:
        """
        Dynamic 2-Tier 하이브리드 매칭

        Level 0 (Coordinator): 배치 생성 및 결과 집계
        Level 1 (Worker): CodeBatchProcessorAgent로 배치 병렬 처리

        Args:
            code_samples: 코드 샘플 리스트 (각 샘플은 {"code": str, "file": str, "line_start": int, "line_end": int})
            persist_dir: ChromaDB 저장 디렉토리
            config: 하이브리드 설정

        Returns:
            (매칭된 스킬 리스트, 미등록 스킬 리스트)

        Performance:
            - 기존: 95초 (88개 코드, 순차적 배치 처리)
            - 개선: ~10초 (88개 코드, 9개 배치 병렬 처리)
            - 향상: 90% (9.5배 빠름)
        """
        total_codes = len(code_samples)
        logger.info(f"🚀 Dynamic 2-Tier 병렬 처리 시작: {total_codes}개 코드")

        # Lazy import to avoid circular dependency
        from .sub_agents.code_batch_processor import (
            CodeBatchProcessorAgent,
            CodeBatchContext,
            CodeBatchResponse,
            SmartBatcher,
        )

        # 1. SmartBatcher로 균등 배치 생성
        batches = SmartBatcher.create_balanced_batches(
            code_samples=code_samples,
            max_agents=config.llm_max_concurrent,
            target_batch_size=config.llm_batch_size,
        )

        num_batches = len(batches)
        logger.info(
            f"📦 {num_batches}개 배치 생성 완료 "
            f"(크기: {[len(b) for b in batches]})"
        )

        # 2. 배치별 CodeBatchProcessorAgent 생성 및 병렬 실행
        async def process_batch(batch_id: int, batch_codes: List):
            """단일 배치 처리 (Level 1 Worker 호출)"""
            try:
                # CodeBatchProcessorAgent 생성
                processor = CodeBatchProcessorAgent(task_uuid=self.task_uuid)

                # Context 생성
                batch_context = CodeBatchContext(
                    batch_id=batch_id,
                    codes=batch_codes,
                    persist_dir=persist_dir,
                    hybrid_config=config,
                    task_uuid=self.task_uuid,
                )

                # Level 1 Worker 실행
                response = await processor.run(batch_context)

                logger.info(
                    f"  배치 {batch_id}: {response.status} "
                    f"(성공률 {response.success_rate:.1%}, "
                    f"{response.processing_time:.2f}s)"
                )

                # 배치 결과 저장 (ResultStore 사용)
                if result_store:
                    try:
                        result_store.save_batched_result(
                            agent_name="code_batch_processor",
                            batch_id=batch_id,
                            result=response,
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ 배치 {batch_id} 결과 저장 실패: {e}")

                return response

            except Exception as e:
                logger.error(f"❌ 배치 {batch_id} 처리 실패: {e}")
                # 실패 시 빈 응답 반환 (Level 0 재시도 대상)
                return CodeBatchResponse(
                    batch_id=batch_id,
                    matched_skills=[],
                    missing_skills=[],
                    success_rate=0.0,
                    failed_codes=batch_codes,
                    processing_time=0.0,
                    retry_count=0,
                    status="failed",
                    message=f"배치 처리 실패: {e}",
                )

        # 3. 모든 배치 병렬 실행
        logger.info(f"⚡ {num_batches}개 배치 병렬 실행 시작...")
        batch_responses = await asyncio.gather(
            *[process_batch(i, batch) for i, batch in enumerate(batches)]
        )

        # 4. Level 0 재시도: 성공률 < 80%인 배치만 재처리
        retry_batches = []
        for response in batch_responses:
            if response.success_rate < 0.8 and response.failed_codes:
                retry_batches.append(response)

        if retry_batches:
            logger.warning(
                f"⚠️ {len(retry_batches)}개 배치 재시도 필요 "
                f"(성공률 < 80%)"
            )

            retry_responses = await asyncio.gather(
                *[
                    process_batch(
                        resp.batch_id,
                        resp.failed_codes,
                    )
                    for resp in retry_batches
                ]
            )

            # 재시도 결과로 원본 응답 교체 및 저장
            for i, orig_resp in enumerate(batch_responses):
                for retry_resp in retry_responses:
                    if orig_resp.batch_id == retry_resp.batch_id:
                        batch_responses[i] = retry_resp
                        # 재시도 결과도 저장
                        if result_store:
                            try:
                                result_store.save_batched_result(
                                    agent_name="code_batch_processor",
                                    batch_id=retry_resp.batch_id,
                                    result=retry_resp,
                                )
                            except Exception as e:
                                logger.warning(f"⚠️ 재시도 배치 {retry_resp.batch_id} 결과 저장 실패: {e}")
                        break

        # 5. 결과 집계
        all_matched_skills = []
        all_missing_skills = []
        total_failed = 0

        for response in batch_responses:
            # SkillMatch를 dict로 변환 (base_score 포함)
            for skill in response.matched_skills:
                all_matched_skills.append(
                    {
                        "skill_name": skill.skill_name,
                        "level": skill.level,
                        "category": skill.category,
                        "subcategory": skill.subcategory,
                        "relevance_score": skill.relevance_score,
                        "reasoning": skill.reasoning,
                        "base_score": skill.base_score,  # ✅ base_score 추가
                    }
                )

            # MissingSkillInfo는 그대로 추가
            all_missing_skills.extend(response.missing_skills)

            # 실패 코드 카운트
            total_failed += len(response.failed_codes)

        # 6. 중복 제거
        unique_matched = self._deduplicate_skills(all_matched_skills)

        # 7. 최종 통계
        final_success_rate = (total_codes - total_failed) / total_codes
        logger.info(
            f"✅ Dynamic 2-Tier 매칭 완료: "
            f"{len(unique_matched)}개 스킬, {len(all_missing_skills)}개 미등록, "
            f"성공률 {final_success_rate:.1%}"
        )

        return unique_matched, all_missing_skills

    def _deduplicate_skills(self, skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        중복 스킬 제거 및 신뢰도 집계

        동일 스킬이 여러 번 매칭되면 평균 relevance_score 사용
        """
        skill_dict = defaultdict(list)

        for skill in skills:
            key = f"{skill['skill_name']}_{skill['level']}"
            skill_dict[key].append(skill)

        unique_skills = []
        for key, skill_list in skill_dict.items():
            # 평균 relevance_score
            avg_score = sum(s["relevance_score"] for s in skill_list) / len(skill_list)

            # 신뢰도 필터링 (0.3 이상만)
            if avg_score >= 0.3:
                skill = skill_list[0].copy()
                skill["relevance_score"] = round(avg_score, 3)
                skill["occurrence_count"] = len(skill_list)
                # base_score는 첫 번째 값 사용 (중복 제거 시 동일 스킬이므로 같음)
                skill["base_score"] = skill.get("base_score", 0)
                unique_skills.append(skill)

        # relevance_score 내림차순 정렬
        unique_skills.sort(key=lambda x: x["relevance_score"], reverse=True)

        return unique_skills

    async def _aggregate_skill_profile(
        self, skills: list[dict[str, Any]], persist_dir: str
    ) -> dict[str, Any]:
        """
        스킬 프로파일 집계

        Returns:
            {
                "total_skills": int,
                "skills_by_category": {...},
                "skills_by_level": {...},
                "category_coverage": {...},
                "top_skills": [...],
            }
        """
        # 카테고리별 분류
        skills_by_category = defaultdict(list)
        for skill in skills:
            skills_by_category[skill["category"]].append(skill)

        # 레벨별 분류
        skills_by_level = defaultdict(list)
        for skill in skills:
            skills_by_level[skill["level"]].append(skill)

        # 카테고리별 커버리지 계산
        coverage = await calculate_category_coverage.ainvoke(
            {"user_skills": skills, "persist_dir": persist_dir}
        )

        # 상위 스킬 (relevance_score 기준 Top 10)
        top_skills = skills[:10]

        # 카테고리별 통계
        category_stats = {}
        for cat, cat_skills in skills_by_category.items():
            category_stats[cat] = {
                "count": len(cat_skills),
                "levels": {
                    "Basic": len([s for s in cat_skills if s["level"] == "Basic"]),
                    "Intermediate": len([s for s in cat_skills if s["level"] == "Intermediate"]),
                    "Advanced": len([s for s in cat_skills if s["level"] == "Advanced"]),
                },
                "avg_score": round(
                    sum(s["relevance_score"] for s in cat_skills) / len(cat_skills), 2
                ),
            }

        # category_coverage 내부의 percentage를 int로 변환 (0.0-100.0 → 0-100)
        category_coverage_converted = {}
        for cat, cat_data in coverage["category_coverage"].items():
            category_coverage_converted[cat] = {
                "count": cat_data["count"],
                "total": cat_data["total"],
                "percentage": int(cat_data["percentage"]),  # float → int 변환
            }

        # 레벨링 시스템 계산
        total_experience = SkillLevelCalculator.calculate_total_experience(skills)
        level_info = SkillLevelCalculator.calculate_level(total_experience)

        # 개발자 타입별 보유율 계산
        developer_type_coverage = await SkillLevelCalculator.calculate_developer_type_coverage(
            skills, persist_dir
        )
        developer_type_levels = SkillLevelCalculator.get_developer_type_levels(
            developer_type_coverage
        )

        logger.info(
            f"📊 레벨링 계산 완료: {total_experience} EXP → {level_info['level_name']} (Lv.{level_info['level']})"
        )
        logger.info(
            f"📊 개발자 타입별 보유율: {len(developer_type_coverage)}개 타입"
        )

        return {
            "total_skills": len(skills),
            "skills_by_category": category_stats,
            "skills_by_level": {
                "Basic": len(skills_by_level["Basic"]),
                "Intermediate": len(skills_by_level["Intermediate"]),
                "Advanced": len(skills_by_level["Advanced"]),
            },
            "category_coverage": category_coverage_converted,
            "total_coverage": int(
                coverage["total_coverage"]
            ),  # calculate_category_coverage()가 이미 백분율로 반환 (6.5% → 6)
            "top_skills": [
                {
                    "skill_name": s["skill_name"],
                    "level": s["level"],
                    "category": s["category"],
                    "relevance_score": s["relevance_score"],
                    "occurrence_count": s.get("occurrence_count", 1),
                }
                for s in top_skills
            ],
            # 레벨링 시스템 필드 추가
            "total_experience": total_experience,
            "level": level_info,
            # 개발자 타입별 통계 필드 추가
            "developer_type_coverage": developer_type_coverage,
            "developer_type_levels": developer_type_levels,
        }
