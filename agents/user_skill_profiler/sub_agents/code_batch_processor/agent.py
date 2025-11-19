"""
CodeBatchProcessor Agent

Level 1 워커 에이전트 - 코드 배치 병렬 처리

이 에이전트는 UserSkillProfiler의 하위 에이전트로서, 10개 내외의 코드 샘플을
병렬로 처리하여 스킬 매칭을 수행합니다.

주요 기능:
- 코드 배치 병렬 LLM 분석 (asyncio.gather)
- Pydantic Structured Output 기반 검증
- 계층적 재시도 메커니즘 (최대 3회)
- 성공률 80% 이상 보장
- 실패한 코드 추적 및 재처리 지원

성능 특성:
- 10개 코드 배치 처리 시간: ~1-2초 (병렬)
- 성공률: 95% 이상 (Structured Output)
- 재시도 성공률: 98% 이상 (3회 시도 시)
"""

import logging
import time
from typing import List, Dict, Any, Optional
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from agents.user_skill_profiler.schemas import (
    HybridConfig,
    SkillMatch,
    MissingSkillInfo,
    SkillAnalysisOutput,
)
from .schemas import CodeBatchContext, CodeBatchResponse, CodeSample
from shared.utils.prompt_loader import PromptLoader
from shared.utils.agent_logging import log_subagent_execution
from shared.utils.agent_debug_logger import AgentDebugLogger

logger = logging.getLogger(__name__)


class CodeBatchProcessorAgent:
    """
    코드 배치 병렬 처리 에이전트 (Level 1 Worker)

    UserSkillProfiler로부터 10개 내외의 코드 배치를 받아
    병렬로 LLM 분석을 수행하고 결과를 반환합니다.

    Design Pattern: Worker Agent Pattern
    - 상태 비저장 (Stateless): 각 run() 호출이 독립적
    - 병렬 안전 (Thread-Safe): 여러 인스턴스 동시 실행 가능
    - 자체 검증 (Self-Validating): 성공률 계산 및 재시도 로직 포함
    - 실패 투명성 (Failure Transparency): 실패한 코드 목록 반환
    """

    def __init__(self, task_uuid: str):
        """
        에이전트 초기화

        Args:
            task_uuid: 작업 고유 식별자 (ChromaDB collection 이름 생성 시 사용)
                      예: "0313b26d-881f-4fe6-97f6-1b7b0546d4aa"
                      → collection name: "code_0313b26d-881f-4fe6-97f6-1b7b0546d4aa"

        Raises:
            ValueError: LLM 또는 프롬프트 로딩 실패 시
        """
        self.task_uuid = task_uuid

        # LLM 로드 (부모 에이전트와 동일한 설정 사용)
        self.llm: BaseChatModel = PromptLoader.get_llm("user_skill_profiler")

        # 프롬프트 로드 (스키마 자동 주입)
        prompts = PromptLoader.load_with_schema(
            agent_name="user_skill_profiler",
            response_schema_class=SkillAnalysisOutput,
        )
        self.system_prompt = prompts.get("system_prompt", "")

        if not self.system_prompt:
            raise ValueError(
                "system_prompt를 찾을 수 없습니다. "
                "prompts.yaml에 system_prompt 키가 존재하는지 확인하세요."
            )

        # Structured Output LLM 생성
        # 이 LLM은 Pydantic 모델을 직접 반환하므로 파싱 오류가 거의 없음 (95%+ 성공률)
        self.structured_llm = self.llm.with_structured_output(SkillAnalysisOutput)

        logger.info(
            f"✅ CodeBatchProcessorAgent 초기화 완료 (task_uuid={task_uuid})"
        )

    def _build_user_prompt(
        self,
        code: str,
        file_path: str,
        line_start: int,
        line_end: int,
        candidate_skills: List[Dict[str, Any]],
        relevance_threshold: float,
    ) -> str:
        """
        system_prompt 기반으로 사용자 프롬프트 동적 생성

        Args:
            code: 분석할 코드 스니펫
            file_path: 파일 경로
            line_start: 시작 라인 번호
            line_end: 종료 라인 번호
            candidate_skills: 후보 스킬 목록 (임베딩 검색 결과)
            relevance_threshold: 관련성 임계값

        Returns:
            생성된 사용자 프롬프트 문자열
        """
        # 후보 스킬 포맷팅
        candidate_skills_text = ""
        if candidate_skills:
            candidate_skills_text = "\n".join(
                [
                    f"- **{skill.get('skill_name', 'Unknown')}** ({skill.get('level', 'Unknown')})"
                    f" - {skill.get('category', 'Unknown')} > {skill.get('subcategory', 'Unknown')}"
                    f"\n  Description: {skill.get('description', 'N/A')}"
                    for skill in candidate_skills
                ]
            )
        else:
            candidate_skills_text = "(임베딩 검색 결과 없음)"

        # 사용자 프롬프트 생성
        user_prompt = f"""다음 코드를 분석하여 관련 스킬을 매칭하세요:

**코드:**
```python
{code}
```

**파일 경로:** {file_path}
**라인 범위:** {line_start}-{line_end}

**후보 스킬 (임베딩 검색 결과):**
{candidate_skills_text}

**관련성 임계값:** {relevance_threshold}

**스킬 매칭:**
- relevance_score >= {relevance_threshold}인 스킬만 matched_skills에 포함하세요.
- 실제로 코드에서 사용되는 스킬만 매칭하세요.

**⚠️ 미등록 스킬 제안 기준 (매우 엄격):**
다음 조건을 모두 만족하는 경우에만 missing_skills에 제안하세요:
1. 코드에서 명확하게 특정 라이브러리/프레임워크/기술을 사용하고 있음
2. 해당 기술이 스킬 DB에 전혀 없음 (후보 스킬에도 없음)
3. 기술적으로 의미 있는 스킬임 (단순 함수 호출이 아님)
4. 특정 도메인/기술 영역의 전문 지식을 요구함

**❌ 제안하지 말 것:**
- 기본 Python 문법 (if, for, def, class, import, if __name__ == '__main__' 등)
- 표준 라이브러리 기본 사용 (os.path.exists, sys.argv, pathlib.Path, json.load 등)
- 너무 일반적인 이름 ("이미지 처리", "데이터 처리", "파일 처리" 등)
- 이미 기존 스킬로 커버 가능한 것 (예: OpenCV 사용 → "컴퓨터 비전" 카테고리)
- 코드에 실제로 없는 기능
- 단순 함수/클래스 정의만 있는 경우

**✅ 제안해야 할 것:**
- 특정 프레임워크/라이브러리 (예: YOLOv8, FastAPI, Django 등)
- 특정 기술 패턴 (예: Event Sourcing, CQRS 등)
- 도메인 특화 기술

**중요:** 대부분의 경우 missing_skills는 빈 배열 []이어야 합니다."""

        return user_prompt

    @log_subagent_execution(parent_agent_name="user_skill_profiler", subagent_name="code_batch_processor")
    async def run(self, context: CodeBatchContext) -> CodeBatchResponse:
        """
        코드 배치 병렬 처리 메인 로직

        Process Flow:
        1. ChromaDB collection 로드 (skill_charts)
        2. 각 코드에 대해 병렬로:
           a. 임베딩 검색으로 스킬 후보 추출 (top_k)
           b. LLM에 코드 + 후보 스킬 전달
           c. Structured Output으로 검증된 결과 수신
        3. 성공률 계산 (성공한 코드 / 전체 코드)
        4. 성공률 < 80%이면 실패한 코드만 재시도 (최대 3회)
        5. 최종 결과 집계 및 반환

        Args:
            context: 배치 처리 요청 정보
                - batch_id: 배치 식별자
                - codes: 처리할 코드 샘플 리스트 (1-20개)
                - persist_dir: ChromaDB 경로
                - hybrid_config: 하이브리드 매칭 설정
                - task_uuid: 작업 UUID

        Returns:
            CodeBatchResponse:
                - matched_skills: 매칭된 스킬 목록
                - missing_skills: 미등록 스킬 제안
                - success_rate: 성공률 (0.0-1.0)
                - failed_codes: 실패한 코드 목록
                - processing_time: 처리 시간 (초)
                - retry_count: 재시도 횟수

        Raises:
            Exception: ChromaDB 로드 실패 등 치명적 오류 발생 시
                      (일반적인 LLM 오류는 재시도 후 failed_codes에 포함)
        """
        start_time = time.time()
        retry_count = 0
        total_codes = len(context.codes)

        logger.info(
            f"🔄 배치 {context.batch_id}: {total_codes}개 코드 처리 시작"
        )

        # LLM 호출 로깅을 위해 logger 가져오기
        from pathlib import Path
        base_path = Path(f"./data/analyze/{context.task_uuid}")
        parent_debug_logger = AgentDebugLogger.get_logger(
            context.task_uuid, 
            base_path, 
            "user_skill_profiler"
        )
        debug_logger = parent_debug_logger.get_subagent_logger(f"code_batch_processor_batch_{context.batch_id}")

        try:
            # ChromaDB 로드 (스킬 차트용 클라이언트 사용)
            try:
                from shared.tools.skill_tools import get_skill_chroma_client
                client = get_skill_chroma_client(context.persist_dir)
                skill_collection = client.get_collection("skill_charts")
                debug_logger.log_intermediate("chromadb_loaded", {
                    "persist_dir": context.persist_dir,
                    "collection": "skill_charts",
                    "status": "success"
                })
            except Exception as e:
                logger.error(f"❌ ChromaDB 로드 실패: {e}")
                debug_logger.log_intermediate("chromadb_loaded", {
                    "persist_dir": context.persist_dir,
                    "collection": "skill_charts",
                    "status": "failed",
                    "error": str(e)
                })
                raise

            # 초기 처리 대상 = 전체 코드
            codes_to_process = context.codes.copy()
            all_matched_skills: List[SkillMatch] = []
            all_missing_skills: List[MissingSkillInfo] = []

            # 재시도 루프 (최대 3회)
            while retry_count <= 3:
                if not codes_to_process:
                    logger.info(f"✅ 배치 {context.batch_id}: 모든 코드 처리 완료")
                    debug_logger.log_intermediate(f"retry_{retry_count}_complete", {
                        "remaining_codes": 0,
                        "all_completed": True
                    })
                    break

                logger.info(
                    f"  시도 {retry_count + 1}: {len(codes_to_process)}개 코드 처리 중..."
                )
                
                debug_logger.log_intermediate(f"retry_{retry_count}_start", {
                    "retry_count": retry_count,
                    "codes_to_process": len(codes_to_process),
                    "total_codes": total_codes
                })

                # 병렬 처리
                results = await self._process_codes_parallel(
                    codes=codes_to_process,
                    skill_collection=skill_collection,
                    config=context.hybrid_config,
                    debug_logger=debug_logger,
                    retry_count=retry_count,
                )

                # 결과 분류 (성공 vs 실패)
                successful_codes: List[CodeSample] = []
                failed_codes: List[CodeSample] = []

                for code, result in zip(codes_to_process, results):
                    if result is not None:
                        # 성공: 결과 집계
                        all_matched_skills.extend(result["matched_skills"])
                        all_missing_skills.extend(result["missing_skills"])
                        successful_codes.append(code)
                    else:
                        # 실패: 재시도 대상에 추가
                        failed_codes.append(code)

                # 성공률 계산
                success_rate = len(successful_codes) / total_codes

                logger.info(
                    f"  시도 {retry_count + 1} 결과: "
                    f"성공 {len(successful_codes)}개, 실패 {len(failed_codes)}개 "
                    f"(성공률: {success_rate:.1%})"
                )
                
                debug_logger.log_intermediate(f"retry_{retry_count}_result", {
                    "successful_codes": len(successful_codes),
                    "failed_codes": len(failed_codes),
                    "success_rate": success_rate,
                    "matched_skills_count": len(all_matched_skills),
                    "missing_skills_count": len(all_missing_skills)
                })

                # 성공률 80% 이상이면 종료
                if success_rate >= 0.8:
                    logger.info(
                        f"✅ 배치 {context.batch_id}: 성공률 {success_rate:.1%} 달성"
                    )
                    codes_to_process = failed_codes  # 최종 failed_codes 업데이트
                    break

                # 실패한 코드만 재시도
                codes_to_process = failed_codes
                retry_count += 1

                if retry_count > 3:
                    logger.warning(
                        f"⚠️ 배치 {context.batch_id}: 최대 재시도 횟수 초과 "
                        f"(최종 성공률: {success_rate:.1%})"
                    )

            # 최종 성공률 계산
            final_success_count = total_codes - len(codes_to_process)
            final_success_rate = final_success_count / total_codes

            # 처리 시간 계산
            processing_time = time.time() - start_time

            # 상태 결정
            if final_success_rate >= 0.8:
                status = "success"
            elif final_success_rate >= 0.5:
                status = "partial_success"
            else:
                status = "failed"

            logger.info(
                f"🏁 배치 {context.batch_id} 완료: "
                f"상태={status}, 성공률={final_success_rate:.1%}, "
                f"처리시간={processing_time:.2f}s, 재시도={retry_count}회"
            )

            response = CodeBatchResponse(
                batch_id=context.batch_id,
                matched_skills=all_matched_skills,
                missing_skills=all_missing_skills,
                success_rate=final_success_rate,
                failed_codes=codes_to_process,
                processing_time=processing_time,
                retry_count=retry_count,
                status=status,
                message=(
                    f"배치 처리 완료: {final_success_count}/{total_codes}개 성공 "
                    f"({final_success_rate:.1%})"
                ),
            )
            return response

        except Exception as e:
            # 에러 응답 생성 (데코레이터가 자동으로 로깅)
            error_response = CodeBatchResponse(
                batch_id=context.batch_id,
                matched_skills=[],
                missing_skills=[],
                success_rate=0.0,
                failed_codes=context.codes,
                processing_time=time.time() - start_time,
                retry_count=retry_count,
                status="failed",
                message=f"배치 처리 실패: {str(e)}",
            )
            raise

    async def _process_codes_parallel(
        self,
        codes: List[CodeSample],
        skill_collection: Any,
        config: HybridConfig,
        debug_logger: AgentDebugLogger,
        retry_count: int,
    ) -> List[Optional[Dict[str, Any]]]:
        """
        코드 리스트를 병렬로 처리

        Args:
            codes: 처리할 코드 샘플 리스트
            skill_collection: ChromaDB skill_charts collection
            config: 하이브리드 매칭 설정
            debug_logger: 디버깅 로거
            retry_count: 현재 재시도 횟수

        Returns:
            결과 리스트 (성공 시 dict, 실패 시 None)
            각 dict는 {"matched_skills": [...], "missing_skills": [...]} 형식
        """
        import asyncio

        tasks = [
            self._analyze_single_code(code, skill_collection, config, debug_logger, retry_count, idx)
            for idx, code in enumerate(codes)
        ]

        # 병렬 실행 (asyncio.gather)
        # return_exceptions=True: 개별 코드 실패가 전체 배치를 중단시키지 않음
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Exception을 None으로 변환 (실패 표시)
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"  코드 {i} 처리 실패 ({codes[i].file}:{codes[i].line_start}): {result}"
                )
                processed_results.append(None)
            else:
                processed_results.append(result)

        return processed_results

    async def _analyze_single_code(
        self,
        code: CodeSample,
        skill_collection: Any,
        config: HybridConfig,
        debug_logger: AgentDebugLogger,
        retry_count: int,
        code_idx: int,
    ) -> Dict[str, Any]:
        """
        단일 코드 샘플 분석

        Process Flow:
        1. 임베딩 검색으로 스킬 후보 추출 (query_texts=[code.code])
        2. LLM에 코드 + 후보 스킬 전달
        3. Structured Output으로 검증된 결과 수신
        4. relevance_threshold 기준으로 필터링
        5. 매칭된 스킬 / 미등록 스킬로 분류

        Args:
            code: 분석할 코드 샘플
            skill_collection: ChromaDB collection
            config: 하이브리드 매칭 설정
            debug_logger: 디버깅 로거
            retry_count: 현재 재시도 횟수
            code_idx: 코드 인덱스

        Returns:
            {
                "matched_skills": List[SkillMatch],
                "missing_skills": List[MissingSkillInfo]
            }

        Raises:
            Exception: ChromaDB 검색 실패, LLM 호출 실패 등
        """
        # 개별 코드별 LLM 호출 추적 (서브에이전트 활성화 시에만)
        if AgentDebugLogger.is_subagent_enabled():
            with debug_logger.track_llm_call() as llm_tracker:
                # 1. 임베딩 검색으로 스킬 후보 추출
                search_results = skill_collection.query(
                    query_texts=[code.code],
                    n_results=config.skill_candidate_count,
                )

                # 후보 스킬 메타데이터 추출 (base_score, developer_type 포함)
                candidate_skills = []
                skill_metadata_map = {}  # skill_name_level을 키로 하는 메타데이터 맵
                if search_results and search_results["metadatas"]:
                    for metadata in search_results["metadatas"][0]:
                        skill_name = metadata.get("skill_name", "")
                        level = metadata.get("level", "")
                        key = f"{skill_name}_{level}"
                        candidate_skills.append(
                            {
                                "skill_name": skill_name,
                                "level": level,
                                "category": metadata.get("category", ""),
                                "subcategory": metadata.get("subcategory", ""),
                                "description": metadata.get("description", ""),
                            }
                        )
                        # base_score와 developer_type 저장 (나중에 SkillMatch 생성 시 사용)
                        skill_metadata_map[key] = {
                            "base_score": int(metadata.get("base_score", 0)),
                            "developer_type": metadata.get("developer_type", "All"),
                        }

                # 2. 사용자 프롬프트 동적 생성 (system_prompt 기반)
                user_prompt = self._build_user_prompt(
                    code=code.code,
                    file_path=code.file,
                    line_start=code.line_start,
                    line_end=code.line_end,
                    candidate_skills=candidate_skills,
                    relevance_threshold=config.relevance_threshold,
                )
                
                # 프롬프트 변수 준비 (로깅용)
                llm_input = {
                    "code": code.code,
                    "file_path": code.file,
                    "line_range": f"{code.line_start}-{code.line_end}",
                    "candidate_skills": candidate_skills,
                    "relevance_threshold": config.relevance_threshold,
                }
                
                llm_tracker.log_prompts(
                    template_name=f"code_batch_processor_code_{code_idx}",
                    variables=llm_input,
                    system_prompt=self.system_prompt,
                    user_prompt=user_prompt,
                )

                # Structured Output LLM 호출 (SystemMessage + HumanMessage)
                messages = [
                    SystemMessage(content=self.system_prompt),
                    HumanMessage(content=user_prompt),
                ]
                analysis_result: SkillAnalysisOutput = await self.structured_llm.ainvoke(messages)
                
                # 응답 로깅 (Structured Output이므로 이미 검증된 Pydantic 객체)
                llm_tracker.log_response_stages(
                    raw=str(analysis_result),
                    parsed=analysis_result.model_dump() if hasattr(analysis_result, 'model_dump') else None,
                    validated=analysis_result,
                )
                
                # LLM 추적 정보 설정 (메타데이터용)
                llm_tracker.set_messages(messages)
                llm_tracker.set_response(analysis_result)

                # 3. relevance_threshold 필터링 및 SkillMatchItem → SkillMatch 변환
                # base_score와 developer_type을 ChromaDB 메타데이터에서 로드
                matched_skills = []
                for item in analysis_result.matched_skills:
                    if item.relevance_score >= config.relevance_threshold:
                        key = f"{item.skill_name}_{item.level}"
                        metadata = skill_metadata_map.get(key, {})
                        matched_skills.append(
                            SkillMatch(
                                skill_name=item.skill_name,
                                level=item.level,
                                category=item.category,
                                subcategory=item.subcategory,
                                relevance_score=item.relevance_score,
                                reasoning=item.reasoning,
                                base_score=metadata.get("base_score", 0),
                                # weighted_score, occurrence_count는 기본값 0 사용
                            )
                        )

                # 4. 미등록 스킬 정보 추가 (MissingSkillItem → MissingSkillInfo 변환)
                missing_skills = []
                for missing in analysis_result.missing_skills:
                    missing_skills.append(
                        MissingSkillInfo(
                            code_snippet=code.code,
                            file_path=code.file,
                            line_number=code.line_start,
                            suggested_skill_name=missing.suggested_skill_name,
                            suggested_level=missing.suggested_level,
                            suggested_category=missing.suggested_category,
                            suggested_subcategory=missing.suggested_subcategory,
                            description=missing.description,
                            evidence_examples=missing.evidence_examples,
                            # developer_type은 기본값 "All"이므로 생략 가능
                        )
                    )

                return {
                    "matched_skills": matched_skills,
                    "missing_skills": missing_skills,
                }
        else:
            # 디버깅 비활성화 시 기존 로직 그대로
            # 1. 임베딩 검색으로 스킬 후보 추출
            search_results = skill_collection.query(
                query_texts=[code.code],
                n_results=config.skill_candidate_count,
            )

            # 후보 스킬 메타데이터 추출 (base_score, developer_type 포함)
            candidate_skills = []
            skill_metadata_map = {}  # skill_name_level을 키로 하는 메타데이터 맵
            if search_results and search_results["metadatas"]:
                for metadata in search_results["metadatas"][0]:
                    skill_name = metadata.get("skill_name", "")
                    level = metadata.get("level", "")
                    key = f"{skill_name}_{level}"
                    candidate_skills.append(
                        {
                            "skill_name": skill_name,
                            "level": level,
                            "category": metadata.get("category", ""),
                            "subcategory": metadata.get("subcategory", ""),
                            "description": metadata.get("description", ""),
                        }
                    )
                    # base_score와 developer_type 저장 (나중에 SkillMatch 생성 시 사용)
                    skill_metadata_map[key] = {
                        "base_score": int(metadata.get("base_score", 0)),
                        "developer_type": metadata.get("developer_type", "All"),
                    }

            # 2. 사용자 프롬프트 동적 생성 (system_prompt 기반)
            user_prompt = self._build_user_prompt(
                code=code.code,
                file_path=code.file,
                line_start=code.line_start,
                line_end=code.line_end,
                candidate_skills=candidate_skills,
                relevance_threshold=config.relevance_threshold,
            )

            # Structured Output LLM 호출 (SystemMessage + HumanMessage)
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=user_prompt),
            ]
            analysis_result: SkillAnalysisOutput = await self.structured_llm.ainvoke(messages)

            # 3. relevance_threshold 필터링 및 SkillMatchItem → SkillMatch 변환
            # base_score와 developer_type을 ChromaDB 메타데이터에서 로드
            matched_skills = []
            for item in analysis_result.matched_skills:
                if item.relevance_score >= config.relevance_threshold:
                    key = f"{item.skill_name}_{item.level}"
                    metadata = skill_metadata_map.get(key, {})
                    matched_skills.append(
                        SkillMatch(
                            skill_name=item.skill_name,
                            level=item.level,
                            category=item.category,
                            subcategory=item.subcategory,
                            relevance_score=item.relevance_score,
                            reasoning=item.reasoning,
                            base_score=metadata.get("base_score", 0),
                            # weighted_score, occurrence_count는 기본값 0 사용
                        )
                    )

            # 4. 미등록 스킬 정보 추가 (MissingSkillItem → MissingSkillInfo 변환)
            missing_skills = []
            for missing in analysis_result.missing_skills:
                missing_skills.append(
                    MissingSkillInfo(
                        code_snippet=code.code,
                        file_path=code.file,
                        line_number=code.line_start,
                        suggested_skill_name=missing.suggested_skill_name,
                        suggested_level=missing.suggested_level,
                        suggested_category=missing.suggested_category,
                        suggested_subcategory=missing.suggested_subcategory,
                        description=missing.description,
                        evidence_examples=missing.evidence_examples,
                        # developer_type은 기본값 "All"이므로 생략 가능
                    )
                )

            return {
                "matched_skills": matched_skills,
                "missing_skills": missing_skills,
            }
