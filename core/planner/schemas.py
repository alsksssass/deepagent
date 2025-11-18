"""
Planner Pydantic schemas

계획 생성 에이전트의 입출력 스키마 정의
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from shared.schemas.common import BaseContext, BaseResponse


class PlannerContext(BaseContext):
    """
    Planner 입력 스키마

    계획 생성을 위한 컨텍스트
    """
    git_url: str = Field(..., description="분석할 Git 레포지토리 URL")
    target_user: Optional[str] = Field(None, description="분석 대상 유저 이메일 또는 이름")
    static_analysis: Optional[Dict[str, Any]] = Field(
        None, description="정적 분석 결과 (선택적)"
    )


class TodoItemSchema(BaseModel):
    """
    TodoList 아이템 스키마

    Planner가 생성하는 개별 작업 항목
    """
    id: str = Field(..., description="작업 ID (예: 'task_001')")
    description: str = Field(..., description="작업 설명")
    status: str = Field(default="pending", description="상태: pending|in_progress|completed|failed")
    assigned_to: Optional[str] = Field(None, description="할당된 서브에이전트 이름")
    dependencies: List[str] = Field(default_factory=list, description="의존하는 작업 ID 목록")
    result: Optional[Any] = Field(None, description="작업 실행 결과")
    error: Optional[str] = Field(None, description="에러 메시지")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="생성 시간")
    completed_at: Optional[str] = Field(None, description="완료 시간")


class PlannerResponse(BaseResponse):
    """
    Planner 출력 스키마
    """
    todo_list: List[TodoItemSchema] = Field(
        default_factory=list, description="생성된 작업 목록"
    )

    class Config:
        extra = "allow"

