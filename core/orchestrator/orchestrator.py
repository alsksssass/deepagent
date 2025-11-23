"""
Deep Agents Orchestrator

전체 워크플로우 조율 및 에이전트 실행 (Pydantic 기반)
"""

import logging
import asyncio
import os
from typing import Any
from datetime import datetime
from pathlib import Path
import uuid

from langchain_aws import ChatBedrockConverse
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from core.state import AgentState
# from core.planner.agent import PlannerAgent
from shared.storage import ResultStore
from shared.utils.token_tracker import TokenTracker
from .config_loader import OrchestratorConfig

# Agents (새 아키텍처)
from agents.repo_cloner import RepoClonerAgent, RepoClonerContext
from agents.static_analyzer import StaticAnalyzerAgent, StaticAnalyzerContext
from agents.commit_analyzer import CommitAnalyzerAgent, CommitAnalyzerContext
from agents.commit_evaluator import CommitEvaluatorAgent, CommitEvaluatorContext
from agents.user_aggregator import UserAggregatorAgent, UserAggregatorContext, UserAggregatorResponse
from agents.reporter import ReporterAgent, ReporterContext

# Agents (Phase 5 마이그레이션 완료)
from agents.code_rag_builder import CodeRAGBuilderAgent, CodeRAGBuilderContext
from agents.user_skill_profiler import UserSkillProfilerAgent, UserSkillProfilerContext

# Tools (for CommitEvaluator)
from shared.tools.neo4j_tools import get_user_commits

logger = logging.getLogger(__name__)


class DeepAgentOrchestrator:
    """
    Deep Agents 오케스트레이터

    LangGraph 워크플로우를 관리하고 에이전트를 조율 (Pydantic 기반)
    """

    def __init__(
        self,
        sonnet_llm: ChatBedrockConverse,
        haiku_llm: ChatBedrockConverse,
        data_dir: Path,
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
        config_path: Path | None = None,
        user_id: uuid.UUID | None = None,
        db_writer: Any | None = None,
    ):
        self.sonnet_llm = sonnet_llm
        self.haiku_llm = haiku_llm
        self.data_dir = data_dir

        # Neo4j 설정: 파라미터 우선, 환경 변수, Settings 순서
        from shared.config import settings
        self.neo4j_uri = neo4j_uri or os.getenv("NEO4J_URI") or settings.NEO4J_URI
        self.neo4j_user = neo4j_user or os.getenv("NEO4J_USER", settings.NEO4J_USER)
        self.neo4j_password = neo4j_password or os.getenv("NEO4J_PASSWORD", settings.NEO4J_PASSWORD)

        # DB Writer (옵셔널: Batch 모드에서만 사용)
        self.user_id = user_id
        self.db_writer = db_writer

        # Orchestrator 설정 로드
        self.config = OrchestratorConfig(config_path)

        # Planner
        # self.planner = PlannerAgent(llm=sonnet_llm)

        # LangGraph 워크플로우 생성
        self.workflow = self._create_workflow()
        self.app = self.workflow.compile(checkpointer=MemorySaver())

    def _create_workflow(self) -> StateGraph:
        """
        LangGraph 워크플로우 생성

        노드:
        1. setup: 작업 초기화
        2. plan: 동적 계획 생성 (Planner)
        3. execute: 에이전트 실행
        4. finalize: 작업 완료 처리

        Returns:
            StateGraph: LangGraph 워크플로우
        """
        workflow = StateGraph(AgentState)

        # 노드 추가
        workflow.add_node("setup", self._setup_node)
        # workflow.add_node("plan", self._plan_node)
        workflow.add_node("execute", self._execute_node)
        workflow.add_node("finalize", self._finalize_node)

        # 엣지 추가
        workflow.set_entry_point("setup")
        # workflow.add_edge("setup", "plan")
        # workflow.add_edge("plan", "execute")
        workflow.add_edge("setup", "execute")
        workflow.add_edge("execute", "finalize")
        workflow.add_edge("finalize", END)

        return workflow

    async def run(
        self,
        git_url: str,
        target_user: str | None = None,
        main_task_uuid: str | None = None,
        main_base_path: str | Path | None = None,
    ) -> AgentState:
        """
        전체 분석 파이프라인 실행

        Args:
            git_url: Git 레포지토리 URL
            target_user: 특정 유저 이메일 (None이면 전체 분석)
            main_task_uuid: 멀티 분석 시 메인 task UUID (None이면 단일 분석)
            main_base_path: 멀티 분석 시 메인 base path (None이면 단일 분석)

        Returns:
            AgentState: 최종 상태
        """
        logger.info("🚀 Deep Agents 분석 시작 (Pydantic 기반)")
        logger.info(f"   Git URL: {git_url}")
        logger.info(f"   Target User: {target_user if target_user else '전체 유저'}")
        if main_task_uuid:
            logger.info(f"   멀티 분석 모드: {main_task_uuid}")

        # 초기 상태
        initial_state: AgentState = {
            "task_uuid": str(uuid.uuid4()),
            "git_url": git_url,
            "target_user": target_user,
            "base_path": "",
            "repo_path": None,
            "static_analysis": None,
            "neo4j_ready": False,
            "chromadb_ready": False,
            "todo_list": None,
            "subagent_results": {},
            "final_report_path": None,
            "final_report": None,
            "error_message": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "total_commits": 0,
            "total_files": 0,
            "elapsed_time": 0.0,
        }
        
        # 멀티 분석 모드 정보를 상태에 추가 (내부 사용)
        if main_task_uuid and main_base_path:
            initial_state["_main_task_uuid"] = main_task_uuid
            initial_state["_main_base_path"] = str(main_base_path)

        # 워크플로우 실행
        config = {"configurable": {"thread_id": initial_state["task_uuid"]}}

        try:
            final_state = await self.app.ainvoke(initial_state, config=config)
            logger.info("✅ Deep Agents 분석 완료")
            return final_state
        except Exception as e:
            # 워크플로우 외부에서 예외 발생 시 DB FAILED 업데이트
            logger.exception(f"❌ 워크플로우 실행 중 예외 발생: {e}")

            if self.db_writer and self.user_id:
                try:
                    from shared.graph_db import AnalysisStatus

                    task_uuid_obj = uuid.UUID(initial_state["task_uuid"])

                    # 기존 레코드가 있으면 FAILED로 업데이트
                    existing = await self.db_writer.get_repository_analysis(task_uuid_obj)
                    if existing:
                        await self.db_writer.update_repository_result(
                            task_uuid=task_uuid_obj,
                            result={},
                            status=AnalysisStatus.FAILED,
                            error_message=str(e)
                        )
                        logger.info(f"📊 DB FAILED 업데이트 완료: {initial_state['task_uuid']}")
                    else:
                        # 레코드가 없으면 생성 (setup_node 실패 시)
                        await self.db_writer.save_repository_analysis(
                            user_id=self.user_id,
                            repository_url=git_url,
                            result={},
                            task_uuid=task_uuid_obj,
                            status=AnalysisStatus.FAILED,
                            error_message=str(e)
                        )
                        logger.info(f"📊 DB FAILED 레코드 생성 완료: {initial_state['task_uuid']}")
                except Exception as db_err:
                    logger.warning(f"⚠️ DB FAILED 업데이트 실패: {db_err}")

            # 에러 정보를 포함한 상태 반환
            initial_state["error_message"] = str(e)
            return initial_state

    async def _setup_node(self, state: AgentState) -> dict[str, Any]:
        """
        작업 초기화 노드

        작업 디렉토리 생성 및 기본 경로 설정
        Task별 로그 파일 핸들러 추가
        DB 레코드 생성 (PROCESSING 상태)
        """
        logger.info("⚙️  Setup: 작업 초기화")

        task_uuid = state["task_uuid"]
        
        # 멀티 분석 모드인지 확인
        main_task_uuid = state.get("_main_task_uuid")
        main_base_path = state.get("_main_base_path")
        is_multi_analysis = bool(main_task_uuid and main_base_path)
        
        # shared/storage의 create_storage_backend를 사용하여 경로 생성
        from shared.storage import create_storage_backend
        from shared.storage.local_store import LocalStorageBackend
        
        backend = create_storage_backend(
            task_uuid=task_uuid,
            base_path=None,  # 자동 생성
            is_multi_analysis=is_multi_analysis,
            main_task_uuid=main_task_uuid if is_multi_analysis else None,
        )
        
        # base_path 추출 (로컬/S3 환경에 맞게)
        if isinstance(backend, LocalStorageBackend):
            base_path = Path(backend.base_path)
            base_path.mkdir(parents=True, exist_ok=True)
        else:
            # S3 환경: base_path는 문자열로 관리
            base_path = backend.base_path
            logger.info(f"   S3 경로: s3://{backend.bucket_name}/{base_path}")
        
        if is_multi_analysis:
            logger.info(f"   멀티 분석 모드: {main_task_uuid}")

        # Task별 로그 디렉토리 생성 (로컬 환경에서만)
        if isinstance(backend, LocalStorageBackend):
            log_dir = base_path / "logs"
            log_dir.mkdir(exist_ok=True)
            task_log_file = log_dir / "combined.log"
        else:
            # S3 환경: 로컬 임시 디렉토리 사용
            import tempfile
            log_dir = Path(tempfile.mkdtemp(prefix=f"deep-agents-logs-{task_uuid}-"))
            task_log_file = log_dir / "combined.log"
        
        # Task별 통합 로그 파일 핸들러 추가
        task_handler = logging.FileHandler(task_log_file, encoding="utf-8")
        task_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        task_handler.setLevel(logging.INFO)

        # 루트 로거에 핸들러 추가
        root_logger = logging.getLogger()
        root_logger.addHandler(task_handler)

        # Task UUID를 핸들러에 저장 (나중에 제거하기 위해)
        task_handler.task_uuid = task_uuid

        logger.info(f"   작업 경로: {base_path}")
        logger.info(f"   로그 파일: {task_log_file}")

        # DB Writer가 있으면 빈 레코드 생성 (PROCESSING 상태)
        if self.db_writer and self.user_id:
            try:
                from shared.graph_db import AnalysisStatus

                git_url = state["git_url"]
                task_uuid_obj = uuid.UUID(task_uuid)
                
                # main_task_uuid 추출 (멀티 분석 시)
                main_task_uuid_obj = None
                if state.get("_main_task_uuid"):
                    main_task_uuid_obj = uuid.UUID(state["_main_task_uuid"])

                # 기존 레코드 확인 (중복 방지)
                existing = await self.db_writer.get_repository_analysis(task_uuid_obj)
                if existing:
                    logger.info(f"📊 기존 DB 레코드 재사용: {task_uuid} (상태: {existing.status.value})")
                else:
                    # 새 레코드 생성
                    await self.db_writer.save_repository_analysis(
                        user_id=self.user_id,
                        repository_url=git_url,
                        result={},  # 빈 결과
                        task_uuid=task_uuid_obj,
                        main_task_uuid=main_task_uuid_obj,  # 멀티 분석 시 종합 분석과 연결
                        status=AnalysisStatus.PROCESSING,
                        error_message=None
                    )
                    logger.info(f"📊 DB 레코드 생성 완료: {task_uuid} (PROCESSING, main_task: {main_task_uuid_obj})")
            except Exception as e:
                logger.warning(f"⚠️ DB 레코드 생성 실패: {e}")

        return {
            "base_path": str(base_path),
            "updated_at": datetime.now().isoformat(),
        }

    async def _plan_node(self, state: AgentState) -> dict[str, Any]:
        """
        계획 생성 노드

        Planner를 사용하여 동적 TodoList 생성
        """
        logger.info("📋 Plan: 작업 계획 생성")

        # Planner 실행
        plan_result = await self.planner.create_plan(state)

        return plan_result

    async def _execute_node(self, state: AgentState) -> dict[str, Any]:
        """
        에이전트 실행 노드 (Pydantic 기반)

        Level 1 병렬 처리: 독립적인 에이전트를 병렬 실행
        """
        logger.info("⚡ Execute: 에이전트 실행 (Pydantic)")

        try:
            task_uuid = state["task_uuid"]
            base_path = Path(state["base_path"])
            git_url = state["git_url"]
            target_user = state.get("target_user")

            # ResultStore 초기화
            store = ResultStore(task_uuid, base_path)

            # Level 1-1: RepoCloner (순차)
            logger.info("📥 Level 1-1: RepoCloner 실행")
            repo_cloner = RepoClonerAgent()
            repo_ctx = RepoClonerContext(
                task_uuid=task_uuid,
                git_url=git_url,
                base_path=str(base_path),
                result_store_path=str(store.results_dir),
                user_id=str(self.user_id) if self.user_id else None,
                db_writer=self.db_writer,
            )
            repo_response = await repo_cloner.run(repo_ctx)

            if repo_response.status != "success":
                return {
                    "error_message": f"RepoCloner 실패: {repo_response.error}",
                    "updated_at": datetime.now().isoformat(),
                }

            # ResultStore에 저장
            store.save_result("repo_cloner", repo_response)

            repo_path = repo_response.repo_path

            # Level 1-2: 병렬 실행 (StaticAnalyzer, CommitAnalyzer, CodeRAGBuilder)
            logger.info("📊 Level 1-2: 병렬 분석 시작")

            static_analyzer = StaticAnalyzerAgent()
            commit_analyzer = CommitAnalyzerAgent(
                neo4j_uri=self.neo4j_uri,
                neo4j_user=self.neo4j_user,
                neo4j_password=self.neo4j_password,
            )
            code_rag_builder = CodeRAGBuilderAgent()

            # Pydantic Context 생성
            static_ctx = StaticAnalyzerContext(
                task_uuid=task_uuid,
                repo_path=repo_path,
                result_store_path=str(store.results_dir),
            )
            commit_ctx = CommitAnalyzerContext(
                task_uuid=task_uuid,
                repo_path=repo_path,
                git_url=git_url,  # Repository Isolation용
                target_user=target_user,
                result_store_path=str(store.results_dir),
            )
            # ChromaDB persist 디렉토리: 환경 변수 우선, 없으면 data_dir/chroma_db
            chromadb_persist_dir = os.getenv(
                "CHROMADB_PERSIST_DIR", str(self.data_dir / "chroma_db")
            )

            code_rag_ctx = CodeRAGBuilderContext(
                task_uuid=task_uuid,
                repo_path=repo_path,
                persist_dir=chromadb_persist_dir,
                result_store_path=str(store.results_dir),
            )

            static_response, commit_response, rag_response = await asyncio.gather(
                static_analyzer.run(static_ctx),
                commit_analyzer.run(commit_ctx),
                code_rag_builder.run(code_rag_ctx),
            )

            # ResultStore에 저장
            store.save_result("static_analyzer", static_response)
            store.save_result("commit_analyzer", commit_response)
            store.save_result("code_rag_builder", rag_response)

            # Pydantic Response → dict 변환 (기존 호환성을 위해 유지)
            static_result = static_response.model_dump()
            commit_result = commit_response.model_dump()
            rag_result = rag_response.model_dump()

            # CommitAnalyzer 실패 시 작업 종료
            if commit_response.status != "success":
                error_msg = f"CommitAnalyzer 실패: {commit_result.get('error', 'Unknown error')}"
                logger.error(f"❌ {error_msg}")
                logger.error("❌ 작업을 종료합니다.")
                return {
                    "error_message": error_msg,
                    "static_analysis": static_result,
                    "neo4j_ready": False,
                    "chromadb_ready": rag_result.get("status") == "success",
                    "total_commits": 0,
                    "total_files": static_result.get("loc_stats", {}).get("total_files", 0),
                    "subagent_results": {
                        "repo_cloner": {
                            "status": "success",
                            "path": "results/repo_cloner.json",
                        },
                        "static_analyzer": {
                            "status": static_response.status,
                            "path": "results/static_analyzer.json",
                        },
                        "commit_analyzer": {
                            "status": commit_response.status,
                            "path": "results/commit_analyzer.json",
                        },
                        "code_rag_builder": {
                            "status": rag_response.status,
                            "path": "results/code_rag_builder.json",
                        },
                    },
                    "updated_at": datetime.now().isoformat(),
                }

            # Level 1-3: CommitEvaluator (병렬) - CommitAnalyzer 성공 시에만 실행
            logger.info("📝 Level 1-3: CommitEvaluator 실행")
            commit_evaluations = []
            
            # Neo4j에서 유저 커밋 목록 가져오기
            if target_user:
                    # Repository ID 생성 (제약조건이 복합 키이므로 필수)
                    from shared.utils.repo_utils import generate_repo_id

                    repo_id = generate_repo_id(git_url)

                    user_commits = await get_user_commits.ainvoke(
                        {
                            "user_email": target_user,
                            "repo_id": repo_id,  # 제약조건이 복합 키이므로 필수
                            "limit": 100,
                            "neo4j_uri": self.neo4j_uri,
                            "neo4j_user": self.neo4j_user,
                            "neo4j_password": self.neo4j_password,
                        }
                    )
                    # None 체크
                    if user_commits is None:
                        user_commits = []
                        logger.warning(f"⚠️ 타겟 유저 {target_user}의 커밋을 찾을 수 없습니다.")
                    logger.info(f"🔍 타겟 유저 {target_user}: {len(user_commits)}개 커밋")
            else:
                # 전체 유저의 경우: 모든 유저의 최근 커밋 샘플링
                from shared.tools.neo4j_tools import query_graph
                from shared.utils.repo_utils import generate_repo_id

                # Repository ID 생성 (제약조건이 복합 키이므로 필수)
                repo_id = generate_repo_id(git_url)

                # 1. 모든 유저 이메일 가져오기 (repo_id 필터링)
                all_users_query = f"""
                MATCH (u:User)-[:COMMITTED]->(c:Commit)
                WHERE u.repo_id = $repo_id AND c.repo_id = $repo_id
                RETURN DISTINCT u.email AS email, count(c) AS commit_count
                ORDER BY commit_count DESC
                """
                all_users = await query_graph.ainvoke(
                    {
                        "cypher_query": all_users_query,
                        "parameters": {"repo_id": repo_id},
                        "repo_id": repo_id,
                        "neo4j_uri": self.neo4j_uri,
                        "neo4j_user": self.neo4j_user,
                        "neo4j_password": self.neo4j_password,
                    }
                )

                # None 체크
                if all_users is None:
                    all_users = []
                    logger.warning("⚠️ 유저 목록을 가져올 수 없습니다.")

                logger.info(f"🔍 전체 {len(all_users)}명의 유저 발견")

                # 2. 각 유저의 최근 커밋 샘플링 (유저당 최대 20개)
                user_commits = []
                for user_info in all_users:
                    user_email = user_info["email"]
                    user_sample = await get_user_commits.ainvoke(
                        {
                            "user_email": user_email,
                            "repo_id": repo_id,  # 제약조건이 복합 키이므로 필수
                            "limit": 20,
                            "neo4j_uri": self.neo4j_uri,
                            "neo4j_user": self.neo4j_user,
                            "neo4j_password": self.neo4j_password,
                        }
                    )
                    # None 체크
                    if user_sample is None:
                        user_sample = []
                    # 각 커밋에 author_email 추가
                    for commit in user_sample:
                        commit["author_email"] = user_email
                    user_commits.extend(user_sample)

                logger.info(f"🔍 전체 샘플링: {len(user_commits)}개 커밋 (유저당 최대 20개)")

            # CommitEvaluator 병렬 실행 (설정에서 배치 크기 가져오기) - Pydantic 기반
            commit_evaluator = CommitEvaluatorAgent(llm=self.haiku_llm)
            total_evaluated = 0  # 통계용 카운터만 유지

            batch_size = self.config.commit_evaluator_batch_size
            for i in range(0, len(user_commits), batch_size):
                    batch = user_commits[i : i + batch_size]

                    # Pydantic Context 생성
                    batch_contexts = [
                        CommitEvaluatorContext(
                            task_uuid=task_uuid,
                            commit_hash=commit["hash"],
                            user=target_user if target_user else commit.get("author_email", ""),
                            git_url=git_url,  # Repository Isolation용
                            neo4j_uri=self.neo4j_uri,
                            neo4j_user=self.neo4j_user,
                            neo4j_password=self.neo4j_password,
                        )
                        for commit in batch
                    ]

                    batch_responses = await asyncio.gather(
                        *[commit_evaluator.run(ctx) for ctx in batch_contexts]
                    )

                    # 배치 결과를 ResultStore에 저장 (메모리 효율성: 즉시 저장)
                    batch_id = i // batch_size
                    store.save_batched_result(
                        "commit_evaluator",
                        batch_id,
                        [resp.model_dump() for resp in batch_responses],
                    )

                    # 메모리 해제: batch_responses는 더 이상 필요 없음
                    total_evaluated += len(batch_responses)
                    del batch_responses

                    logger.info(
                        f"   {i + len(batch)}/{len(user_commits)} 커밋 평가 완료 (배치 {batch_id} 저장됨)"
                    )

            # Level 1-4: UserAggregator - Pydantic 기반 (스트리밍 처리)
            logger.info("👤 Level 1-4: UserAggregator 실행")

            # CommitEvaluator 배치가 저장되었는지 확인
            batched_agents = store.list_batched_agents()
            has_commit_evaluations = "commit_evaluator" in batched_agents

            if has_commit_evaluations:
                user_aggregator = UserAggregatorAgent()
                # UserAggregator가 ResultStore에서 스트리밍으로 로드하므로 commit_evaluations 전달 불필요
                user_agg_ctx = UserAggregatorContext(
                    task_uuid=task_uuid,
                    user=target_user,  # None이면 전체 유저 (validator에서 허용)
                    commit_evaluations=None,  # ResultStore에서 스트리밍 로드
                    result_store_path=str(store.results_dir),
                )
                user_agg_response = await user_aggregator.run(user_agg_ctx)
                store.save_result("user_aggregator", user_agg_response)
                user_agg_result = user_agg_response.model_dump()
            else:
                user_agg_result = {
                    "status": "failed",
                    "user": target_user if target_user else None,
                    "aggregate_stats": {},
                    "error": "커밋 평가 결과 없음",
                }

            # Level 1-4.5: UserSkillProfiler - Pydantic 기반
            logger.info("🎯 Level 1-4.5: UserSkillProfiler 실행")

            # ℹ️ skill_charts는 독립 실행 스크립트(server/skill_charts_builder.py)로 사전 구축됨
            # ℹ️ get_skill_chroma_client()는 원격 ChromaDB(CHROMADB_HOST)를 사용하므로 persist_dir 불필요
            if rag_result["status"] == "success":
                logger.info(f"✅ 코드 RAG 구축 완료: {rag_result['total_chunks']} chunks")

                # ChromaDB persist 디렉토리 (코드 컬렉션용)
                chromadb_persist_dir = os.getenv(
                    "CHROMADB_PERSIST_DIR", str(self.data_dir / "chroma_db")
                )

                # target_user가 None이면 "ALL_USERS"로 처리 (UserAggregator와 동일)
                user_for_skill_profiler = target_user if target_user else "ALL_USERS"

                user_skill_profiler = UserSkillProfilerAgent()
                skill_profile_ctx = UserSkillProfilerContext(
                    task_uuid=task_uuid,
                    user=user_for_skill_profiler,
                    # persist_dir는 기본값 사용 (실제로는 원격 ChromaDB 사용으로 무시됨)
                    code_persist_dir=chromadb_persist_dir,  # 코드 컬렉션용 디렉토리
                    result_store_path=str(store.results_dir),
                )
                skill_profile_response = await user_skill_profiler.run(skill_profile_ctx)
                store.save_result("user_skill_profiler", skill_profile_response)
                skill_profile_result = skill_profile_response.model_dump()
            else:
                skill_profile_result = {
                    "status": "skipped",
                    "user": target_user if target_user else "ALL_USERS",
                    "skill_profile": {},
                    "error": "RAG not ready",
                }

            # Level 1-5: Reporter - Pydantic 기반
            logger.info("📝 Level 1-5: Reporter 실행")

            reporter = ReporterAgent(llm=self.sonnet_llm)
            # Reporter는 ResultStore에서 직접 로드하므로 dict 전달 불필요 (하위 호환성을 위해 빈 dict 전달)
            reporter_ctx = ReporterContext(
                task_uuid=task_uuid,
                base_path=str(base_path),
                git_url=git_url,
                static_analysis={},  # ResultStore에서 로드하므로 빈 dict
                user_aggregate={},  # ResultStore에서 로드하므로 빈 dict
                result_store_path=str(store.results_dir),
            )
            report_response = await reporter.run(reporter_ctx)
            store.save_result("reporter", report_response)
            report_result = report_response.model_dump()

            # 최종 결과 반환 (메타데이터만 저장하여 메모리 효율성 향상)
            return {
                "repo_path": repo_path,
                "static_analysis": static_result,  # Reporter 호환성을 위해 유지
                "neo4j_ready": commit_response.status == "success",
                "chromadb_ready": (
                    rag_result["status"] == "success"
                ),  # skill_charts는 독립 스크립트로 사전 구축
                "total_commits": commit_result.get("total_commits", 0),
                "total_files": static_result.get("loc_stats", {}).get("total_files", 0),
                "subagent_results": {
                    "repo_cloner": {
                        "status": repo_response.status,
                        "path": "results/repo_cloner.json",
                    },
                    "static_analyzer": {
                        "status": static_response.status,
                        "path": "results/static_analyzer.json",
                    },
                    "commit_analyzer": {
                        "status": commit_response.status,
                        "path": "results/commit_analyzer.json",
                    },
                    "code_rag_builder": {
                        "status": rag_response.status,
                        "path": "results/code_rag_builder.json",
                    },
                    # skill_charts_rag_builder는 독립 스크립트로 분리됨
                    "user_skill_profiler": {
                        "status": skill_profile_result.get("status", "skipped"),
                        "path": "results/user_skill_profiler.json",
                    },
                    "user_aggregator": {
                        "status": user_agg_result.get("status", "failed"),
                        "path": "results/user_aggregator.json",
                    },
                    "reporter": {"status": report_response.status, "path": "results/reporter.json"},
                },
                "final_report_path": report_result.get("report_path"),
                "updated_at": datetime.now().isoformat(),
                "error_message": None,
            }

        except Exception as e:
            logger.error(f"❌ Execute 노드 에러: {e}")
            import traceback

            logger.error(f"상세 Traceback:\n{traceback.format_exc()}")
            return {
                "error_message": str(e),
                "updated_at": datetime.now().isoformat(),
            }

    async def _finalize_node(self, state: AgentState) -> dict[str, Any]:
        """
        최종 처리 노드

        결과 저장 및 리포트 생성
        Task별 로그 핸들러 제거
        DB 결과 업데이트 (COMPLETED 또는 FAILED)
        """
        logger.info("🎉 Finalize: 작업 완료 처리")

        task_uuid = state["task_uuid"]
        base_path = Path(state["base_path"])

        # 임시 리포트
        report_content = f"""# 코드 분석 리포트 (Pydantic 기반)

**Task UUID**: {state['task_uuid']}
**Git URL**: {state['git_url']}
**Target User**: {state.get('target_user', '전체 유저')}

## 실행 결과

서브에이전트 결과: {state.get('subagent_results', {})}

**생성 시간**: {datetime.now().isoformat()}
"""

        # ResultStore를 통해 리포트 저장 (S3 또는 로컬)
        try:
            from shared.storage import ResultStore

            store = ResultStore(task_uuid, base_path)
            report_path = store.save_report("final_report.md", report_content)
            logger.info(f"   리포트 저장: {report_path}")
        except Exception as e:
            logger.warning(f"⚠️ ResultStore 저장 실패, 로컬에 저장: {e}")
            # Fallback: 로컬에 저장
            report_path = base_path / "final_report.md"
            report_path.write_text(report_content, encoding="utf-8")
            logger.info(f"   리포트 저장 (로컬): {report_path}")

        # 로그 파일을 S3에 업로드 (작업 완료 시)
        log_dir = base_path / "logs"
        if log_dir.exists():
            try:
                from shared.storage import ResultStore

                store = ResultStore(task_uuid, base_path)
                uploaded_logs = store.upload_log_directory(log_dir)
                if uploaded_logs:
                    logger.info(f"   로그 파일 업로드 완료: {len(uploaded_logs)}개 파일")
            except Exception as e:
                logger.warning(f"⚠️ 로그 파일 업로드 실패: {e}")

        # 디버그 로그 디렉토리도 S3에 업로드
        debug_dir = base_path / "debug"
        if debug_dir.exists():
            try:
                from shared.storage import ResultStore

                store = ResultStore(task_uuid, base_path)
                # debug 디렉토리를 logs/debug/ 아래에 업로드
                uploaded_debug = store.upload_log_directory(debug_dir, remote_subdir="debug")
                if uploaded_debug:
                    logger.info(f"   디버그 로그 업로드 완료: {len(uploaded_debug)}개 파일")
            except Exception as e:
                logger.warning(f"⚠️ 디버그 로그 업로드 실패: {e}")

        # 토큰 사용량 전체 집계 출력
        logger.info("")
        TokenTracker.print_summary()

        # Task별 로그 핸들러 제거 (메모리 누수 방지)
        root_logger = logging.getLogger()
        handlers_to_remove = [
            h for h in root_logger.handlers if hasattr(h, 'task_uuid') and h.task_uuid == task_uuid
        ]
        for handler in handlers_to_remove:
            handler.close()
            root_logger.removeHandler(handler)
            logger.debug(f"   로그 핸들러 제거: {task_uuid}")

        # DB Writer가 있으면 결과 업데이트
        if self.db_writer and self.user_id:
            try:
                from shared.graph_db import AnalysisStatus
                from shared.storage import ResultStore

                # ResultStore에서 user_aggregator 결과 로드
                store = ResultStore(task_uuid, base_path)
                user_agg_result = store.load_result("user_aggregator", UserAggregatorResponse)

                # 에러 여부 확인
                has_error = state.get("error_message") is not None
                status = AnalysisStatus.FAILED if has_error else AnalysisStatus.COMPLETED
                error_message = state.get("error_message")

                task_uuid_obj = uuid.UUID(task_uuid)
                
                # main_task_uuid 추출 (멀티 분석 시)
                main_task_uuid_obj = None
                if state.get("_main_task_uuid"):
                    main_task_uuid_obj = uuid.UUID(state["_main_task_uuid"])

                # DB 업데이트
                await self.db_writer.update_repository_result(
                    task_uuid=task_uuid_obj,
                    result=user_agg_result.model_dump() if user_agg_result else {},
                    main_task_uuid=main_task_uuid_obj,  # 멀티 분석 시 종합 분석과 연결
                    status=status,
                    error_message=error_message
                )
                logger.info(f"📊 DB 결과 업데이트 완료: {task_uuid} ({status.value}, main_task: {main_task_uuid_obj})")
            except Exception as e:
                logger.warning(f"⚠️ DB 결과 업데이트 실패: {e}")

        return {
            "final_report_path": str(report_path),
            "final_report": report_content,
            "updated_at": datetime.now().isoformat(),
        }
