"""
CommitEvaluator Agent

개별 커밋을 LLM으로 평가하는 서브에이전트 (Pydantic 스키마 사용)
"""

import logging
import asyncio
import json
from typing import Any, Optional
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import SystemMessage, HumanMessage

# Pydantic 스키마
from .schemas import (
    CommitEvaluatorContext,
    CommitEvaluatorResponse,
    CommitEvaluation,
)

# 공통 유틸리티
from shared.utils.prompt_loader import PromptLoader
from shared.utils.token_tracker import TokenTracker

# Tools (기존 유지)
from shared.tools.neo4j_tools import get_commit_details
from shared.tools.chromadb_tools import search_code

logger = logging.getLogger(__name__)


class CommitEvaluatorAgent:
    """
    개별 커밋을 평가하는 서브에이전트

    Level 3 병렬 처리:
    - 커밋 메타데이터 조회 (Neo4j)
    - 관련 코드 검색 (ChromaDB)
    - LLM 평가
    """

    def __init__(self, llm: Optional[ChatBedrockConverse] = None):
        # 하이브리드 방식: YAML 모델 우선, 외부 LLM 전달 시 오버라이드
        if llm is None:
            # YAML 설정 기반으로 LLM 인스턴스 생성
            self.llm = PromptLoader.get_llm("commit_evaluator")
            model_id = PromptLoader.get_model("commit_evaluator")
            logger.info(f"✅ CommitEvaluatorAgent: YAML 모델 사용 - {model_id}")
        else:
            # 외부 전달된 LLM 사용 (오버라이드)
            self.llm = llm
            logger.info(f"✅ CommitEvaluatorAgent: 외부 LLM 사용")
        
        # 하이브리드: 스키마 자동 주입
        self.prompts = PromptLoader.load_with_schema(
            "commit_evaluator",
            response_schema_class=CommitEvaluation
        )

    async def run(self, context: CommitEvaluatorContext) -> CommitEvaluatorResponse:
        """
        커밋 평가 실행 (Pydantic 스키마 사용)

        Args:
            context: CommitEvaluatorContext (검증된 입력)

        Returns:
            CommitEvaluatorResponse (타입 안전 출력)
        """
        commit_hash = context.commit_hash
        user = context.user
        task_uuid = context.task_uuid

        logger.info(f"📝 CommitEvaluator: {commit_hash[:8]} 평가 시작")

        try:
            # Repository ID 생성 (제약조건이 복합 키이므로 필수)
            repo_id = context.repo_id
            
            # Level 3-1: 병렬 데이터 수집
            commit_info, code_contexts = await asyncio.gather(
                # Neo4j에서 커밋 상세 정보 (repo_id 필수)
                get_commit_details.ainvoke(
                    {
                        "commit_hash": commit_hash,
                        "repo_id": repo_id,  # 제약조건이 복합 키이므로 필수
                        "neo4j_uri": context.neo4j_uri,
                        "neo4j_user": context.neo4j_user,
                        "neo4j_password": context.neo4j_password,
                    }
                ),
                # ChromaDB에서 관련 코드 검색
                self._search_related_code(commit_hash, task_uuid),
            )

            # Level 3-2: LLM 평가
            evaluation = await self._evaluate_with_llm(
                commit_info=commit_info,
                code_contexts=code_contexts,
                user=user,
            )

            # Pydantic 모델로 변환 (자동 검증)
            commit_eval = CommitEvaluation(**evaluation)

            logger.info(
                f"✅ CommitEvaluator: {commit_hash[:8]} - 점수 {commit_eval.quality_score}"
            )

            return CommitEvaluatorResponse(
                status="success",
                commit_hash=commit_hash,
                quality_score=commit_eval.quality_score,
                technologies=commit_eval.technologies,
                complexity=commit_eval.complexity,
                evaluation=commit_eval.evaluation,
                error=None,
            )

        except Exception as e:
            logger.error(f"❌ CommitEvaluator: {commit_hash[:8]} - {e}")
            return CommitEvaluatorResponse(
                status="failed",
                commit_hash=commit_hash,
                quality_score=0.0,
                technologies=[],
                complexity="unknown",
                evaluation="",
                error=str(e),
            )

    async def _search_related_code(
        self, commit_hash: str, task_uuid: str, n_results: int = 5
    ) -> list[dict[str, Any]]:
        """
        ChromaDB에서 커밋 관련 코드 검색
        """
        try:
            collection_name = f"code_{task_uuid}"
            results = await search_code.ainvoke(
                {
                    "query": commit_hash,  # 커밋 해시로 검색
                    "collection_name": collection_name,
                    "n_results": n_results,
                }
            )
            return results
        except Exception as e:
            logger.warning(f"⚠️  코드 검색 실패: {e}")
            return []

    async def _evaluate_with_llm(
        self,
        commit_info: dict[str, Any],
        code_contexts: list[dict[str, Any]],
        user: str,
    ) -> dict[str, Any]:
        """
        LLM으로 커밋 평가 (YAML 프롬프트 사용)
        """
        # YAML 프롬프트 사용 (json_schema 변수 자동 주입)
        system_prompt = PromptLoader.format(
            self.prompts["system_prompt"],
            json_schema=self.prompts.get("json_schema", "")
        )

        # 템플릿 변수 치환
        user_prompt = PromptLoader.format(
            self.prompts["user_template"],
            commit_hash=commit_info.get("hash", "unknown")[:8],
            user=user,
            commit_message=commit_info.get("message", "No message"),
            files_count=len(commit_info.get("files", [])),
            lines_added=commit_info.get("lines_added", 0),
            lines_deleted=commit_info.get("lines_deleted", 0),
            code_contexts=self._format_code_contexts(code_contexts[:3]),
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        # 토큰 추적 (각 커밋 평가마다)
        response = await self.llm.ainvoke(messages)
        TokenTracker.record_usage("commit_evaluator", response, model_id=PromptLoader.get_model("commit_evaluator"))
        content = response.content

        # JSON 파싱
        try:
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()

            evaluation_data = json.loads(json_str)
            return evaluation_data

        except Exception as e:
            logger.warning(f"⚠️  LLM 응답 파싱 실패: {e}")
            return {
                "quality_score": 5.0,
                "technologies": [],
                "complexity": "medium",
                "evaluation": "평가 실패",
            }

    def _format_code_contexts(self, contexts: list[dict[str, Any]]) -> str:
        """
        코드 컨텍스트 포맷팅
        """
        if not contexts:
            return "관련 코드 없음"

        formatted = []
        for ctx in contexts:
            formatted.append(
                f"- {ctx['file']} (유사도: {ctx['score']:.2f})\n  {ctx['code'][:100]}..."
            )
        return "\n".join(formatted)
