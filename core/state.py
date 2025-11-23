"""
Deep Agents State Management

AgentState: 전체 작업 상태를 관리하는 TypedDict
"""

from typing import TypedDict, Optional, Any
from pathlib import Path


class AgentState(TypedDict, total=False):
    """
    전체 Deep Agents 작업 상태

    LangGraph Store와 함께 사용하여 에이전트 간 상태 공유
    """

    # 작업 식별자
    task_uuid: str  # 작업 고유 UUID
    main_task_uuid: Optional[str]  # 멀티 레포지토리 분석 시 메인 작업 UUID
    git_url: str  # 분석할 Git 레포지토리 URL
    target_user: Optional[str]  # 특정 유저 이메일 (None이면 전체 분석)

    # 경로 정보
    base_path: str  # 작업 기본 경로 (./data/analyze/{task_uuid})
    main_base_path: Optional[str]  # 멀티 레포지토리 분석 시 메인 경로
    repo_path: Optional[str]  # 클론된 레포지토리 경로

    # 정적 분석 결과
    static_analysis: Optional[dict[str, Any]]  # Radon, Pyright, Cloc 결과

    # 데이터베이스 상태
    neo4j_ready: bool  # Neo4j에 커밋 데이터 저장 완료
    chromadb_ready: bool  # ChromaDB에 코드 임베딩 저장 완료

    # 분석 계획
    todo_list: Optional[list[dict[str, Any]]]  # Planner가 생성한 작업 목록

    # 서브에이전트 실행 결과 (메타데이터만 저장, 실제 결과는 ResultStore에 저장)
    subagent_results: dict[str, dict[str, str]]  # 각 서브에이전트의 메타데이터 {"status": "...", "path": "..."}

    # 최종 리포트
    final_report_path: Optional[str]  # 최종 리포트 파일 경로
    final_report: Optional[str]  # 최종 리포트 내용

    # 에러 처리
    error_message: Optional[str]  # 에러 발생 시 메시지

    # 메타데이터
    created_at: str  # 작업 생성 시간
    updated_at: str  # 최종 업데이트 시간

    # 성능 메트릭
    total_commits: int  # 분석 대상 커밋 수
    total_files: int  # 분석 대상 파일 수
    elapsed_time: float  # 소요 시간 (초)


class TodoItem(TypedDict):
    """
    LangChain Deep Agents TodoList 아이템

    Planner가 생성하는 개별 작업 항목
    """

    id: str  # 작업 ID (예: "task_001")
    description: str  # 작업 설명
    status: str  # 상태: "pending" | "in_progress" | "completed" | "failed"
    assigned_to: Optional[str]  # 할당된 서브에이전트 이름
    dependencies: list[str]  # 의존하는 작업 ID 목록
    result: Optional[Any]  # 작업 실행 결과
    error: Optional[str]  # 에러 메시지
    created_at: str  # 생성 시간
    completed_at: Optional[str]  # 완료 시간


class SubagentResult(TypedDict):
    """
    서브에이전트 실행 결과
    """

    subagent_name: str  # 서브에이전트 이름
    status: str  # 상태: "success" | "failed"
    output: Any  # 출력 결과
    error: Optional[str]  # 에러 메시지
    elapsed_time: float  # 소요 시간 (초)
    started_at: str  # 시작 시간
    completed_at: str  # 완료 시간
