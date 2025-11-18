"""
Deep Agents Orchestrator

전체 워크플로우 조율 및 에이전트 실행 (Pydantic 기반)
"""

import logging
import asyncio
from typing import Any
from datetime import datetime
from pathlib import Path
import uuid

from langchain_aws import ChatBedrockConverse
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from core.state import AgentState
from core.planner.agent import PlannerAgent
from shared.storage import ResultStore

# Agents (새 아키텍처)
from agents.repo_cloner import RepoClonerAgent, RepoClonerContext
from agents.static_analyzer import StaticAnalyzerAgent, StaticAnalyzerContext
from agents.commit_analyzer import CommitAnalyzerAgent, CommitAnalyzerContext
from agents.commit_evaluator import CommitEvaluatorAgent, CommitEvaluatorContext
from agents.user_aggregator import UserAggregatorAgent, UserAggregatorContext
from agents.reporter import ReporterAgent, ReporterContext

# Agents (Phase 5 마이그레이션 완료)
from agents.code_rag_builder import CodeRAGBuilderAgent, CodeRAGBuilderContext
from agents.skill_charts_rag_builder import SkillChartsRAGBuilderAgent, SkillChartsRAGBuilderContext
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
        skill_charts_path: str,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "password",
    ):
        self.sonnet_llm = sonnet_llm
        self.haiku_llm = haiku_llm
        self.data_dir = data_dir
        self.skill_charts_path = skill_charts_path
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password

        # Planner
        self.planner = PlannerAgent(llm=sonnet_llm)

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
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("execute", self._execute_node)
        workflow.add_node("finalize", self._finalize_node)

        # 엣지 추가
        workflow.set_entry_point("setup")
        workflow.add_edge("setup", "plan")
        workflow.add_edge("plan", "execute")
        workflow.add_edge("execute", "finalize")
        workflow.add_edge("finalize", END)

        return workflow

    async def run(
        self,
        git_url: str,
        target_user: str | None = None,
    ) -> AgentState:
        """
        전체 분석 파이프라인 실행

        Args:
            git_url: Git 레포지토리 URL
            target_user: 특정 유저 이메일 (None이면 전체 분석)

        Returns:
            AgentState: 최종 상태
        """
        logger.info("🚀 Deep Agents 분석 시작 (Pydantic 기반)")
        logger.info(f"   Git URL: {git_url}")
        logger.info(f"   Target User: {target_user if target_user else '전체 유저'}")

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

        # 워크플로우 실행
        config = {"configurable": {"thread_id": initial_state["task_uuid"]}}
        final_state = await self.app.ainvoke(initial_state, config=config)

        logger.info("✅ Deep Agents 분석 완료")
        return final_state

    async def _setup_node(self, state: AgentState) -> dict[str, Any]:
        """
        작업 초기화 노드

        작업 디렉토리 생성 및 기본 경로 설정
        """
        logger.info("⚙️  Setup: 작업 초기화")

        task_uuid = state["task_uuid"]
        base_path = self.data_dir / "analyze" / task_uuid
        base_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"   작업 경로: {base_path}")

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

            # Level 1-2: 병렬 실행 (StaticAnalyzer, CommitAnalyzer, CodeRAGBuilder, SkillChartsRAGBuilder)
            logger.info("📊 Level 1-2: 병렬 분석 시작")

            static_analyzer = StaticAnalyzerAgent()
            commit_analyzer = CommitAnalyzerAgent(
                neo4j_uri=self.neo4j_uri,
                neo4j_user=self.neo4j_user,
                neo4j_password=self.neo4j_password,
            )
            code_rag_builder = CodeRAGBuilderAgent()
            skill_charts_rag_builder = SkillChartsRAGBuilderAgent()

            # Pydantic Context 생성
            static_ctx = StaticAnalyzerContext(
                task_uuid=task_uuid,
                repo_path=repo_path,
                result_store_path=str(store.results_dir),
            )
            commit_ctx = CommitAnalyzerContext(
                task_uuid=task_uuid,
                repo_path=repo_path,
                target_user=target_user,
                result_store_path=str(store.results_dir),
            )
            code_rag_ctx = CodeRAGBuilderContext(
                task_uuid=task_uuid,
                repo_path=repo_path,
                persist_dir=str(self.data_dir / "chroma_db"),
                result_store_path=str(store.results_dir),
            )
            skill_rag_ctx = SkillChartsRAGBuilderContext(
                task_uuid=task_uuid,
                skill_charts_path=self.skill_charts_path,
                persist_dir=str(self.data_dir / "chroma_db"),
                result_store_path=str(store.results_dir),
            )

            static_response, commit_response, rag_response, skill_rag_response = await asyncio.gather(
                static_analyzer.run(static_ctx),
                commit_analyzer.run(commit_ctx),
                code_rag_builder.run(code_rag_ctx),
                skill_charts_rag_builder.run(skill_rag_ctx),
            )

            # ResultStore에 저장
            store.save_result("static_analyzer", static_response)
            store.save_result("commit_analyzer", commit_response)
            store.save_result("code_rag_builder", rag_response)
            store.save_result("skill_charts_rag_builder", skill_rag_response)

            # Pydantic Response → dict 변환 (기존 호환성을 위해 유지)
            static_result = static_response.model_dump()
            commit_result = commit_response.model_dump()
            rag_result = rag_response.model_dump()
            skill_rag_result = skill_rag_response.model_dump()

            # Level 1-3: CommitEvaluator (병렬)
            logger.info("📝 Level 1-3: CommitEvaluator 실행")

            if commit_response.status != "success":
                logger.warning("CommitAnalyzer 실패, CommitEvaluator 스킵")
                commit_evaluations = []
            else:
                # Neo4j에서 유저 커밋 목록 가져오기
                if target_user:
                    user_commits = await get_user_commits.ainvoke({
                        "user_email": target_user,
                        "limit": 100,
                        "neo4j_uri": self.neo4j_uri,
                        "neo4j_user": self.neo4j_user,
                        "neo4j_password": self.neo4j_password,
                    })
                    logger.info(f"🔍 타겟 유저 {target_user}: {len(user_commits)}개 커밋")
                else:
                    # 전체 유저의 경우: 모든 유저의 최근 커밋 샘플링
                    from shared.tools.neo4j_tools import query_graph

                    # 1. 모든 유저 이메일 가져오기
                    all_users_query = """
                    MATCH (u:User)-[:COMMITTED]->(c:Commit)
                    RETURN DISTINCT u.email AS email, count(c) AS commit_count
                    ORDER BY commit_count DESC
                    """
                    all_users = await query_graph.ainvoke({
                        "cypher_query": all_users_query,
                        "neo4j_uri": self.neo4j_uri,
                        "neo4j_user": self.neo4j_user,
                        "neo4j_password": self.neo4j_password,
                    })

                    logger.info(f"🔍 전체 {len(all_users)}명의 유저 발견")

                    # 2. 각 유저의 최근 커밋 샘플링 (유저당 최대 20개)
                    user_commits = []
                    for user_info in all_users:
                        user_email = user_info["email"]
                        user_sample = await get_user_commits.ainvoke({
                            "user_email": user_email,
                            "limit": 20,
                            "neo4j_uri": self.neo4j_uri,
                            "neo4j_user": self.neo4j_user,
                            "neo4j_password": self.neo4j_password,
                        })
                        # 각 커밋에 author_email 추가
                        for commit in user_sample:
                            commit["author_email"] = user_email
                        user_commits.extend(user_sample)

                    logger.info(f"🔍 전체 샘플링: {len(user_commits)}개 커밋 (유저당 최대 20개)")

                # CommitEvaluator 병렬 실행 (배치 크기 10) - Pydantic 기반
                commit_evaluator = CommitEvaluatorAgent(llm=self.haiku_llm)
                total_evaluated = 0  # 통계용 카운터만 유지

                batch_size = 10
                for i in range(0, len(user_commits), batch_size):
                    batch = user_commits[i : i + batch_size]

                    # Pydantic Context 생성
                    batch_contexts = [
                        CommitEvaluatorContext(
                            task_uuid=task_uuid,
                            commit_hash=commit["hash"],
                            user=target_user if target_user else commit.get("author_email", ""),
                            neo4j_uri=self.neo4j_uri,
                            neo4j_user=self.neo4j_user,
                            neo4j_password=self.neo4j_password,
                        )
                        for commit in batch
                    ]

                    batch_responses = await asyncio.gather(*[
                        commit_evaluator.run(ctx) for ctx in batch_contexts
                    ])

                    # 배치 결과를 ResultStore에 저장 (메모리 효율성: 즉시 저장)
                    batch_id = i // batch_size
                    store.save_batched_result(
                        "commit_evaluator",
                        batch_id,
                        [resp.model_dump() for resp in batch_responses]
                    )

                    # 메모리 해제: batch_responses는 더 이상 필요 없음
                    total_evaluated += len(batch_responses)
                    del batch_responses

                    logger.info(f"   {i + len(batch)}/{len(user_commits)} 커밋 평가 완료 (배치 {batch_id} 저장됨)")

            # Level 1-4: UserAggregator - Pydantic 기반 (스트리밍 처리)
            logger.info("👤 Level 1-4: UserAggregator 실행")

            # CommitEvaluator 배치가 저장되었는지 확인
            batch_dir = store.get_batch_dir("commit_evaluator")
            has_commit_evaluations = batch_dir.exists() and any(batch_dir.glob("batch_*.json"))

            if has_commit_evaluations:
                user_aggregator = UserAggregatorAgent()
                # UserAggregator가 ResultStore에서 스트리밍으로 로드하므로 commit_evaluations 전달 불필요
                user_agg_ctx = UserAggregatorContext(
                    task_uuid=task_uuid,
                    user=target_user if target_user else "ALL_USERS",
                    commit_evaluations=None,  # ResultStore에서 스트리밍 로드
                    result_store_path=str(store.results_dir),
                )
                user_agg_response = await user_aggregator.run(user_agg_ctx)
                store.save_result("user_aggregator", user_agg_response)
                user_agg_result = user_agg_response.model_dump()
            else:
                user_agg_result = {
                    "status": "failed",
                    "user": target_user if target_user else "ALL_USERS",
                    "aggregate_stats": {},
                    "error": "커밋 평가 결과 없음",
                }

            # Level 1-4.5: UserSkillProfiler - Pydantic 기반
            logger.info("🎯 Level 1-4.5: UserSkillProfiler 실행")

            if target_user and rag_result["status"] == "success" and skill_rag_result["status"] == "success":
                user_skill_profiler = UserSkillProfilerAgent()
                skill_profile_ctx = UserSkillProfilerContext(
                    task_uuid=task_uuid,
                    user=target_user,
                    persist_dir=str(self.data_dir / "chroma_db"),
                    result_store_path=str(store.results_dir),
                )
                skill_profile_response = await user_skill_profiler.run(skill_profile_ctx)
                store.save_result("user_skill_profiler", skill_profile_response)
                skill_profile_result = skill_profile_response.model_dump()
            else:
                skill_profile_result = {
                    "status": "skipped",
                    "user": target_user if target_user else "N/A",
                    "skill_profile": {},
                    "error": "Target user not specified or RAG not ready",
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
                user_aggregate={},   # ResultStore에서 로드하므로 빈 dict
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
                "chromadb_ready": rag_result["status"] == "success" and skill_rag_result["status"] == "success",
                "total_commits": commit_result.get("total_commits", 0),
                "total_files": static_result.get("loc_stats", {}).get("total_files", 0),
                "subagent_results": {
                    "repo_cloner": {"status": repo_response.status, "path": "results/repo_cloner.json"},
                    "static_analyzer": {"status": static_response.status, "path": "results/static_analyzer.json"},
                    "commit_analyzer": {"status": commit_response.status, "path": "results/commit_analyzer.json"},
                    "code_rag_builder": {"status": rag_response.status, "path": "results/code_rag_builder.json"},
                    "skill_charts_rag_builder": {"status": skill_rag_response.status, "path": "results/skill_charts_rag_builder.json"},
                    "user_skill_profiler": {"status": skill_profile_result.get("status", "skipped"), "path": "results/user_skill_profiler.json"},
                    "user_aggregator": {"status": user_agg_result.get("status", "failed"), "path": "results/user_aggregator.json"},
                    "reporter": {"status": report_response.status, "path": "results/reporter.json"},
                },
                "final_report_path": report_result.get("report_path"),
                "updated_at": datetime.now().isoformat(),
                "error_message": None,
            }

        except Exception as e:
            logger.error(f"❌ Execute 노드 에러: {e}")
            import traceback
            traceback.print_exc()
            return {
                "error_message": str(e),
                "updated_at": datetime.now().isoformat(),
            }

    async def _finalize_node(self, state: AgentState) -> dict[str, Any]:
        """
        최종 처리 노드

        결과 저장 및 리포트 생성
        """
        logger.info("🎉 Finalize: 작업 완료 처리")

        base_path = Path(state["base_path"])
        report_path = base_path / "final_report.md"

        # 임시 리포트
        report_content = f"""# 코드 분석 리포트 (Pydantic 기반)

**Task UUID**: {state['task_uuid']}
**Git URL**: {state['git_url']}
**Target User**: {state.get('target_user', '전체 유저')}

## 실행 결과

TodoList: {len(state.get('todo_list', []))}개 작업
서브에이전트 결과: {state.get('subagent_results', {})}

**생성 시간**: {datetime.now().isoformat()}
"""

        report_path.write_text(report_content, encoding="utf-8")

        logger.info(f"   리포트 저장: {report_path}")

        return {
            "final_report_path": str(report_path),
            "final_report": report_content,
            "updated_at": datetime.now().isoformat(),
        }
