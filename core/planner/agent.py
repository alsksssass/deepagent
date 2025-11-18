"""
Planner Agent - 동적 계획 생성 에이전트

유저 요청과 Neo4j 데이터를 기반으로 TodoList 생성
"""

import logging
import json
from typing import Any
from datetime import datetime

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_aws import ChatBedrockConverse

from core.state import AgentState, TodoItem
from shared.utils.prompt_loader import PromptLoader
from shared.utils.token_tracker import TokenTracker
from .schemas import PlannerContext, PlannerResponse, TodoItemSchema

logger = logging.getLogger(__name__)


class PlannerAgent:
    """
    동적 작업 계획 생성 에이전트

    유저 요청과 Neo4j 데이터를 기반으로 TodoList 생성
    """

    def __init__(self, llm: ChatBedrockConverse):
        self.llm = llm
        # YAML 프롬프트 로드 (캐싱됨)
        self.prompts = PromptLoader.load("planner")

    async def create_plan(self, state: AgentState) -> dict[str, Any]:
        """
        분석 계획 생성

        Args:
            state: 현재 AgentState

        Returns:
            업데이트된 상태 (todo_list 포함)
        """
        logger.info("🧠 Planner: 분석 계획 생성 시작")

        # PlannerContext 생성
        context = PlannerContext(
            task_uuid=state["task_uuid"],
            git_url=state["git_url"],
            target_user=state.get("target_user"),
            static_analysis=state.get("static_analysis"),
        )

        # PlannerResponse 생성
        response = await self._generate_plan(context)

        # TodoItemSchema → TodoItem (TypedDict) 변환
        todo_list: list[TodoItem] = [
            {
                "id": item.id,
                "description": item.description,
                "status": item.status,
                "assigned_to": item.assigned_to,
                "dependencies": item.dependencies,
                "result": item.result,
                "error": item.error,
                "created_at": item.created_at,
                "completed_at": item.completed_at,
            }
            for item in response.todo_list
        ]

        logger.info(f"✅ Planner: {len(todo_list)}개 작업 생성")

        return {
            "todo_list": todo_list,
            "updated_at": datetime.now().isoformat(),
        }

    async def _generate_plan(self, context: PlannerContext) -> PlannerResponse:
        """
        LLM을 사용하여 계획 생성

        Args:
            context: PlannerContext

        Returns:
            PlannerResponse
        """
        try:
            # 프롬프트 템플릿 변수 치환
            user_prompt = self.prompts["user_template"].format(
                git_url=context.git_url,
                target_user=context.target_user if context.target_user else "전체 유저",
                static_analysis=(
                    json.dumps(context.static_analysis, indent=2, ensure_ascii=False)
                    if context.static_analysis
                    else "아직 수행되지 않음"
                ),
            )

            messages = [
                SystemMessage(content=self.prompts["system_prompt"]),
                HumanMessage(content=user_prompt),
            ]

            # 토큰 추적
            with TokenTracker.track("planner"):
                response = await self.llm.ainvoke(messages)
                TokenTracker.record_usage("planner", response, model_id=PromptLoader.get_model("planner"))
            
            content = response.content

            # JSON 파싱
            plan_data = self._parse_json_response(content)
            todo_list = plan_data.get("todo_list", [])

            # TodoItemSchema 리스트 생성
            todo_items = [
                TodoItemSchema(**item) if isinstance(item, dict) else item
                for item in todo_list
            ]

            return PlannerResponse(
                status="success",
                todo_list=todo_items,
            )

        except Exception as e:
            logger.error(f"❌ Planner: 계획 생성 실패 - {e}", exc_info=True)
            logger.debug(f"LLM 응답:\n{content if 'content' in locals() else 'N/A'}")

            # 기본 계획 반환
            default_plan = self._create_default_plan(context.target_user)
            return PlannerResponse(
                status="success",
                todo_list=default_plan,
            )

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        """
        LLM 응답에서 JSON 추출 및 파싱

        Args:
            content: LLM 응답 내용

        Returns:
            파싱된 JSON 데이터
        """
        try:
            # JSON 코드 블록 추출
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()

            return json.loads(json_str)

        except json.JSONDecodeError as e:
            logger.error(f"❌ Planner: JSON 파싱 실패 - {e}")
            raise

    def _create_default_plan(self, target_user: str | None) -> list[TodoItemSchema]:
        """
        LLM 파싱 실패 시 기본 계획 반환

        Args:
            target_user: 타겟 유저 이메일

        Returns:
            기본 TodoItemSchema 리스트
        """
        now = datetime.now().isoformat()

        return [
            TodoItemSchema(
                id="task_001",
                description="Git 레포지토리 클론",
                status="pending",
                assigned_to="RepoCloner",
                dependencies=[],
                created_at=now,
            ),
            TodoItemSchema(
                id="task_002",
                description="정적 분석 (Radon, Pyright, Cloc)",
                status="pending",
                assigned_to="StaticAnalyzer",
                dependencies=["task_001"],
                created_at=now,
            ),
            TodoItemSchema(
                id="task_003",
                description="커밋 분석 및 Neo4j 저장",
                status="pending",
                assigned_to="CommitAnalyzer",
                dependencies=["task_001"],
                created_at=now,
            ),
            TodoItemSchema(
                id="task_004",
                description="코드 임베딩 및 ChromaDB 저장",
                status="pending",
                assigned_to="CodeRAGBuilder",
                dependencies=["task_001"],
                created_at=now,
            ),
            TodoItemSchema(
                id="task_005",
                description=f"{'특정 유저' if target_user else '전체 유저'} 커밋 평가",
                status="pending",
                assigned_to="CommitEvaluator",
                dependencies=["task_003", "task_004"],
                created_at=now,
            ),
            TodoItemSchema(
                id="task_006",
                description="유저별 집계 및 프로파일 생성",
                status="pending",
                assigned_to="UserAggregator",
                dependencies=["task_005"],
                created_at=now,
            ),
            TodoItemSchema(
                id="task_007",
                description="최종 리포트 생성",
                status="pending",
                assigned_to="Reporter",
                dependencies=["task_006"],
                created_at=now,
            ),
        ]

