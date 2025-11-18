# 서브에이전트 생성 가이드

Deep Agents 프레임워크에서 새로운 서브에이전트를 생성하는 핵심 가이드입니다.

---

## 📋 목차

1. [시스템 아키텍처](#시스템-아키텍처)
2. [에이전트 구조](#에이전트-구조)
3. [생성 프로세스](#생성-프로세스)
4. [오케스트레이터 통합](#오케스트레이터-통합)
5. [베스트 프랙티스](#베스트-프랙티스)

---

## 시스템 아키텍처

### 전체 실행 흐름

```
┌─────────────────────────────────────────────────────────────┐
│                    DeepAgentOrchestrator                     │
│                  (LangGraph StateGraph)                      │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
    ┌───▼───┐          ┌───▼───┐          ┌───▼────┐
    │ Setup │          │ Plan  │          │Execute │
    │ Node  │─────────▶│ Node  │─────────▶│  Node  │
    └───────┘          └───────┘          └───┬────┘
                                               │
                                               │
        ┌──────────────────────────────────────┼──────────────────────┐
        │                                      │                      │
   ┌────▼────┐                          ┌─────▼─────┐         ┌─────▼─────┐
   │ Level 1 │                          │  Level 2  │         │  Level 3  │
   │  순차   │                          │   순차    │         │   병렬    │
   └────┬────┘                          └─────┬─────┘         └─────┬─────┘
        │                                      │                      │
   ┌────▼────┐                          ┌─────▼─────┐         ┌─────▼─────┐
   │RepoCloner│                         │CommitEval │         │Security   │
   │ (순차)   │                         │ (병렬배치)│         │Quality    │
   └────┬────┘                         └─────┬─────┘         │Performance│
        │                                      │              │Architect  │
   ┌────▼──────────────────────────┐    ┌─────▼─────┐         └───────────┘
   │ Level 1-2: 병렬 실행          │    │UserAgg    │
   │ ┌──────────┐ ┌──────────┐    │    │UserSkill  │
   │ │Static    │ │Commit    │    │    │Profiler   │
   │ │Analyzer  │ │Analyzer  │    │    └───────────┘
   │ └──────────┘ └──────────┘    │
   │ ┌──────────┐ ┌──────────┐    │
   │ │CodeRAG   │ │SkillRAG  │    │
   │ │Builder   │ │Builder   │    │
   │ └──────────┘ └──────────┘    │
   └───────────────────────────────┘
```

### 데이터 흐름

```
RepoCloner
    ↓ repo_path
StaticAnalyzer → ResultStore → static_analysis.json
CommitAnalyzer → Neo4j (commit graph)
CodeRAGBuilder → ChromaDB (code collection)
SkillRAGBuilder → ChromaDB (skill_charts collection)
    ↓
CommitEvaluator → ResultStore → commit_evaluator/batch_*.json
    ↓
UserAggregator → ResultStore → user_aggregator.json
UserSkillProfiler → ResultStore → user_skill_profiler.json
    ↓
Reporter → final_report.md
```

### 핵심 컴포넌트

#### 1. **Orchestrator** (`core/orchestrator.py`)
- LangGraph StateGraph 기반 워크플로우 관리
- 4개 노드: Setup → Plan → Execute → Finalize
- 에이전트 실행 순서 및 병렬 처리 제어

#### 2. **ResultStore** (`shared/storage/result_store.py`)
- 에이전트 결과를 JSON 파일로 저장/로드
- Pydantic 기반 타입 안전성 보장
- 배치 결과 지원 (CommitEvaluator 등)

#### 3. **PromptLoader** (`shared/utils/prompt_loader.py`)
- YAML 프롬프트 로드 및 캐싱
- 스키마 자동 주입 (`load_with_schema`)
- LLM 인스턴스 생성 및 관리

#### 4. **BaseContext/BaseResponse** (`shared/schemas/common.py`)
- 모든 에이전트의 입출력 스키마 기반 클래스
- Pydantic 기반 검증

---

## 에이전트 구조

### 표준 디렉토리 구조

```
agents/
└── {agent_name}/
    ├── __init__.py          # 공개 인터페이스
    ├── agent.py             # 에이전트 클래스
    ├── schemas.py           # Pydantic 스키마
    ├── prompts.yaml         # LLM 프롬프트 (LLM 사용 시)
    └── README.md            # 문서
```

### 에이전트 타입

| 타입 | LLM 사용 | 예시 | 특징 |
|------|---------|------|------|
| **데이터 수집** | ❌ | RepoCloner, StaticAnalyzer | 빠른 실행, 외부 도구 사용 |
| **DB 구축** | ❌ | CodeRAGBuilder, SkillRAGBuilder | 임베딩 생성 및 저장 |
| **LLM 평가** | ✅ | CommitEvaluator, UserSkillProfiler | Structured Output 사용 |
| **집계** | 선택 | UserAggregator | 여러 결과 통합 |
| **전문 분석** | ✅ | SecurityAgent, QualityAgent | 도메인 특화 분석 |
| **리포트** | ✅ | ReporterAgent | 최종 리포트 생성 |

---

## 생성 프로세스

### Step 1: 디렉토리 생성

```bash
cd agents
mkdir -p new_agent
cd new_agent
touch __init__.py agent.py schemas.py README.md
# LLM 사용 시
touch prompts.yaml
```

### Step 2: 스키마 정의 (`schemas.py`)

#### 2.1 기본 구조

```python
"""NewAgent Schemas"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Optional, Literal
from shared.schemas.common import BaseContext, BaseResponse


class NewAgentContext(BaseContext):
    """입력 스키마"""
    input_data: Dict[str, Any] = Field(
        ...,
        description="분석할 데이터"
    )
    option_flag: bool = Field(
        default=False,
        description="옵션 플래그"
    )

    @field_validator("input_data")
    def validate_input_data(cls, v):
        """입력 데이터 검증 (선택적)"""
        if not isinstance(v, dict):
            raise ValueError("input_data는 dict여야 합니다")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "task_uuid": "test-uuid",
                "input_data": {"key": "value"},
                "option_flag": True
            }
        }


class AnalysisResult(BaseModel):
    """LLM 출력 스키마 (중간 모델)"""
    findings: List[str] = Field(
        default_factory=list,
        description=(
            "분석 결과 - 반드시 문자열 배열이어야 합니다. "
            "각 항목은 '파일:라인 - 이슈 설명' 형식을 권장합니다. "
            "예시: ['auth.py:23 - 타입 에러 발견', 'api.py:45 - 보안 취약점']"
        )
    )
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description=(
            "점수 (0.0~10.0). 반드시 소수점 형태의 숫자여야 합니다 (예: 7.5, 8.2). "
            "10.0 = 탁월, 7.0-9.9 = 양호, 4.0-6.9 = 보통, 1.0-3.9 = 낮음, 0.0 = 매우 낮음"
        )
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description="권장사항 목록 (우선순위 순)"
    )

    @field_validator("score")
    @classmethod
    def round_score(cls, v):
        """점수 소수점 1자리로 반올림"""
        return round(v, 1)


class NewAgentResponse(BaseResponse):
    """출력 스키마"""
    analysis: AnalysisResult = Field(
        default_factory=AnalysisResult,
        description="분석 결과"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "analysis": {
                    "findings": ["발견사항 1", "발견사항 2"],
                    "score": 8.5,
                    "recommendations": ["권장사항 1"]
                }
            }
        }
```

#### 2.2 스키마 파일 구조 패턴

**표준 구조**:
```
schemas.py
├── {Agent}Context (BaseContext 상속)
│   ├── 필수 필드
│   ├── 선택 필드 (default 값)
│   ├── @field_validator (검증 로직)
│   └── Config.json_schema_extra (예시)
│
├── 중간 모델들 (LLM 출력용)
│   ├── {Analysis/Result} 모델
│   ├── 중첩 모델 (예: VulnerabilityRisk)
│   ├── 상세한 Field description
│   └── @field_validator (변환/정규화)
│
└── {Agent}Response (BaseResponse 상속)
    ├── 중간 모델 필드
    └── Config.json_schema_extra (예시)
```

**핵심 원칙**:
- ✅ `BaseContext` 상속 (입력)
- ✅ `BaseResponse` 상속 (출력)
- ✅ Field description에 형식 명시 ("반드시", "예시" 포함)
- ✅ 제약 조건 명시 (`ge`, `le`, `default_factory`)
- ✅ `@field_validator`로 검증 및 변환
- ✅ `Config.json_schema_extra`로 예시 제공
- ✅ 중첩 모델 사용 (복잡한 구조 분리)

**Description 작성 가이드**:
```python
# ✅ 좋은 예시
field: str = Field(
    ...,
    description=(
        "필드 설명 - 반드시 형식을 명시하고 예시를 포함합니다. "
        "예시: 'value1', 'value2'. "
        "평가 기준: 조건1, 조건2, 조건3"
    )
)

# ❌ 나쁜 예시
field: str = Field(..., description="필드")  # 너무 간략
```

### Step 3: 에이전트 구현 (`agent.py`)

#### LLM 사용 에이전트

```python
"""NewAgent - LLM 기반 분석"""

import logging
import json
import re
from typing import Optional
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import SystemMessage, HumanMessage

from .schemas import NewAgentContext, NewAgentResponse, AnalysisResult
from shared.utils.prompt_loader import PromptLoader
from shared.utils.token_tracker import TokenTracker

logger = logging.getLogger(__name__)


class NewAgent:
    """분석 전문 에이전트"""

    def __init__(self, llm: Optional[ChatBedrockConverse] = None):
        # 하이브리드: YAML 우선, 외부 LLM 전달 시 오버라이드
        if llm is None:
            self.llm = PromptLoader.get_llm("new_agent")
            logger.info(f"✅ NewAgent: YAML 모델 사용")
        else:
            self.llm = llm
            logger.info(f"✅ NewAgent: 외부 LLM 사용")

        # 스키마 자동 주입
        self.prompts = PromptLoader.load_with_schema(
            "new_agent",
            response_schema_class=AnalysisResult
        )

    async def run(self, context: NewAgentContext) -> NewAgentResponse:
        """분석 실행"""
        logger.info("🔍 NewAgent: 분석 시작")

        try:
            # 데이터 추출
            input_data = context.input_data

            # 프롬프트 생성
            system_prompt = PromptLoader.format(
                self.prompts["system_prompt"],
                json_schema=self.prompts.get("json_schema", "")
            )
            user_prompt = PromptLoader.format(
                self.prompts["user_template"],
                input_data=input_data,
            )

            # LLM 호출 (토큰 추적)
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]

            response = await TokenTracker.track_async(
                self.llm.ainvoke,
                messages,
                agent_name="new_agent"
            )

            # JSON 파싱
            analysis = self._parse_json_response(response.content)

            logger.info(f"✅ NewAgent: 완료 - 점수 {analysis.score}/10")

            return NewAgentResponse(
                status="success",
                analysis=analysis,
            )

        except Exception as e:
            logger.error(f"❌ NewAgent 실행 실패: {e}")
            return NewAgentResponse(
                status="failed",
                analysis=AnalysisResult(),
                error=str(e),
            )

    def _parse_json_response(self, content: str) -> AnalysisResult:
        """JSON 파싱"""
        try:
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
            json_str = json_match.group(1) if json_match else content
            data = json.loads(json_str)
            return AnalysisResult(**data)
        except Exception as e:
            logger.warning(f"⚠️ JSON 파싱 실패: {e}")
            return AnalysisResult()
```

#### LLM 미사용 에이전트

```python
"""NewAgent - 데이터 수집"""

import logging
from pathlib import Path
from .schemas import NewAgentContext, NewAgentResponse

logger = logging.getLogger(__name__)


class NewAgent:
    """데이터 수집 에이전트"""

    def __init__(self):
        logger.info("✅ NewAgent 초기화")

    async def run(self, context: NewAgentContext) -> NewAgentResponse:
        """데이터 수집 실행"""
        logger.info("📥 NewAgent: 데이터 수집 시작")

        try:
            # 처리 로직
            result_data = self._process_data(context.input_data)

            logger.info(f"✅ NewAgent: 완료 - {len(result_data)}개 항목")

            return NewAgentResponse(
                status="success",
                data=result_data,
            )

        except Exception as e:
            logger.error(f"❌ NewAgent 실행 실패: {e}")
            return NewAgentResponse(
                status="failed",
                data={},
                error=str(e),
            )

    def _process_data(self, input_data: dict) -> dict:
        """데이터 처리"""
        # 실제 구현
        return {"processed": True}
```

### Step 4: 프롬프트 작성 (`prompts.yaml` - LLM 사용 시)

#### 4.1 기본 구조

```yaml
version: "1.0"
model: "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

system_prompt: |
  당신은 {역할} 전문가입니다. 다음 데이터를 분석하세요.

  분석 영역:
  1. {영역 1} - {설명}
  2. {영역 2} - {설명}
  3. {영역 3} - {설명}

  ## Response Format (JSON):
  {json_schema}

user_template: |
  다음 데이터를 분석하세요:

  필드 1:
  {field1}

  필드 2:
  {field2}

  상세 분석을 제공해주세요.
```

#### 4.2 프롬프트 파일 구조 패턴

**표준 구조**:
```yaml
version: "1.0"                    # 필수
model: "us.anthropic.claude-3-5-sonnet-20241022-v2:0"  # 필수

# 단일 system_prompt (기본)
system_prompt: |
  ...

# 또는 여러 system 프롬프트 (ReporterAgent 패턴)
executive_summary_system: |
  ...
domain_synthesis_system: |
  ...

# user_template (필수)
user_template: |
  ...

# 추가 설정 (선택적)
evaluation_criteria:           # 평가 기준
  quality_factors:
    - ...
  complexity_thresholds:
    ...

section_templates:             # 재사용 가능한 템플릿
  section_name: |
    ...
```

**실제 예시 (SecurityAgent)**:
```yaml
version: "1.0"
model: "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

system_prompt: |
  당신은 보안 전문가입니다. 코드 분석 결과를 바탕으로 보안 위험 요소를 식별하고 개선 방안을 제시하세요.

  분석 영역:
  1. 타입 안정성 - 타입 에러가 보안에 미치는 영향
  2. 인증/인가 - 기술 스택에서 보안 관련 패턴 식별
  3. 입력 검증 - 복잡도가 높은 함수의 입력 검증 위험
  4. 취약점 위험도 - 전반적인 보안 취약점 평가

  응답 형식 (JSON):
  {json_schema}

user_template: |
  다음 코드 분석 결과를 바탕으로 보안 분석을 수행하세요:

  타입 체크 결과:
  - 에러: {type_errors}개
  - 경고: {type_warnings}개

  복잡도 분포:
  - A: {complexity_a}개
  - B: {complexity_b}개
  - C: {complexity_c}개
  - D: {complexity_d}개
  - F: {complexity_f}개

  기술 스택:
  {tech_stack}

  보안 관점에서 상세 분석을 제공해주세요.
```

**실제 예시 (CommitEvaluator - 평가 기준 포함)**:
```yaml
version: "1.0"
model: "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

system_prompt: |
  당신은 코드 품질과 기여도를 평가하는 전문가입니다.

  커밋 정보를 분석하여 다음을 제공하세요:
  1. **quality_score** (0.0-10.0): 코드 품질 점수
  2. **technologies** (list): 사용된 기술 스택
  3. **complexity** (low|medium|high): 복잡도
  4. **evaluation** (str): 평가 설명

  JSON 형식으로 응답하세요:
  {json_schema}

user_template: |
  다음 커밋을 평가하세요:

  **커밋 해시**: {commit_hash}
  **작성자**: {user}
  **메시지**: {commit_message}
  **수정 파일 수**: {files_count}
  **추가 라인**: +{lines_added}
  **삭제 라인**: -{lines_deleted}

  **관련 코드 컨텍스트**:
  {code_contexts}

evaluation_criteria:
  quality_factors:
    - "단일 책임 원칙 준수"
    - "테스트 코드 포함 여부"
    - "명확한 커밋 메시지"
  complexity_thresholds:
    low: "< 100 줄 변경, 1-2 파일"
    medium: "100-500 줄, 3-10 파일"
    high: "> 500 줄 또는 10+ 파일"
```

**핵심 원칙**:
- ✅ `version`, `model` 필드 필수
- ✅ `system_prompt`에 `{json_schema}` 변수 반드시 포함
- ✅ `user_template`에서 `{변수명}` 형태로 변수 정의
- ✅ 분석 영역, 평가 기준 명시
- ✅ Few-shot 예시 포함 가능 (UserSkillProfiler 패턴)
- ❌ 하드코딩된 JSON 예제 작성 금지 (자동 생성됨)
- ❌ 스키마 형식을 프롬프트에 직접 작성 금지

### Step 5: Export (`__init__.py`)

```python
"""NewAgent"""

from .agent import NewAgent
from .schemas import NewAgentContext, NewAgentResponse, AnalysisResult

__all__ = [
    "NewAgent",
    "NewAgentContext",
    "NewAgentResponse",
    "AnalysisResult",
]
```

---

## 오케스트레이터 통합

### Step 6: Orchestrator에 등록

#### 6.1 Import 추가

`core/orchestrator.py`:

```python
# 기존 imports...
from agents.new_agent import NewAgent, NewAgentContext
```

#### 6.2 Execute Node에 통합

```python
async def _execute_node(self, state: AgentState) -> dict[str, Any]:
    """에이전트 실행 노드"""
    
    task_uuid = state["task_uuid"]
    base_path = Path(state["base_path"])
    store = ResultStore(task_uuid, base_path)

    # ... 기존 에이전트 실행 ...

    # Level X: NewAgent 실행
    logger.info("🔍 Level X: NewAgent 실행")
    
    new_agent = NewAgent()  # 또는 NewAgent(llm=self.sonnet_llm)
    
    new_ctx = NewAgentContext(
        task_uuid=task_uuid,
        input_data=some_previous_result,  # 이전 결과 활용
        result_store_path=str(store.results_dir),
    )
    
    new_response = await new_agent.run(new_ctx)
    
    if new_response.status != "success":
        logger.warning(f"⚠️ NewAgent 실패: {new_response.error}")
    else:
        store.save_result("new_agent", new_response)
    
    # 상태 업데이트
    return {
        "subagent_results": {
            # ... 기존 결과 ...
            "new_agent": {
                "status": new_response.status,
                "path": "results/new_agent.json"
            }
        },
        # ...
    }
```

#### 6.3 병렬 실행 (asyncio.gather)

```python
# Level 3: 전문 분석 에이전트 병렬 실행
security_agent = SecurityAgent(llm=self.sonnet_llm)
quality_agent = QualityAgent(llm=self.sonnet_llm)
new_agent = NewAgent(llm=self.sonnet_llm)

security_ctx = SecurityAgentContext(...)
quality_ctx = QualityAgentContext(...)
new_ctx = NewAgentContext(...)

# 병렬 실행
security_response, quality_response, new_response = await asyncio.gather(
    security_agent.run(security_ctx),
    quality_agent.run(quality_ctx),
    new_agent.run(new_ctx),
)

# 결과 저장
store.save_result("security_agent", security_response)
store.save_result("quality_agent", quality_response)
store.save_result("new_agent", new_response)
```

### 실행 레벨 가이드

| 레벨 | 실행 방식 | 예시 | 의존성 |
|------|----------|------|--------|
| **Level 1-1** | 순차 | RepoCloner | 없음 |
| **Level 1-2** | 병렬 | StaticAnalyzer, CommitAnalyzer, CodeRAGBuilder | RepoCloner |
| **Level 1-3** | 병렬 배치 | CommitEvaluator | CommitAnalyzer |
| **Level 1-4** | 순차 | UserAggregator | CommitEvaluator |
| **Level 1-4.5** | 순차 | UserSkillProfiler | CodeRAGBuilder, SkillRAGBuilder |
| **Level 1-5** | 순차 | Reporter | 모든 이전 결과 |

**새 에이전트 추가 시**:
- 의존성 확인: 어떤 에이전트 결과가 필요한가?
- 실행 방식 결정: 순차 vs 병렬
- 적절한 레벨 선택

---

## 베스트 프랙티스

### 1. 스키마 설계

✅ **DO**:
```python
# 상세한 description
field: str = Field(
    ...,
    description="필드 설명 - 반드시 형식을 명시하고 예시 포함 (예: 'value1', 'value2')"
)

# 제약 조건 명시
score: float = Field(..., ge=0.0, le=10.0, description="점수 (0.0~10.0)")

# default_factory 사용
items: List[str] = Field(default_factory=list, description="항목 목록")
```

❌ **DON'T**:
```python
# Description 없음
field: str = Field(...)

# 가변 기본값 (위험)
items: List[str] = Field(default=[])  # ❌ 공유됨
```

### 2. LLM 통합

✅ **DO - load_with_schema 사용**:
```python
self.prompts = PromptLoader.load_with_schema(
    "agent_name",
    response_schema_class=OutputSchema
)
```

❌ **DON'T - 수동 스키마 하드코딩**:
```python
self.prompts = PromptLoader.load("agent_name")
# JSON 스키마 수동 작성 ❌
```

### 3. 에러 처리

✅ **DO**:
```python
async def run(self, context: Context) -> Response:
    try:
        result = await self._process(context)
        return Response(status="success", result=result)
    except Exception as e:
        logger.error(f"❌ 에러: {e}")
        return Response(
            status="failed",
            result=DefaultResult(),
            error=str(e),
        )
```

### 4. ResultStore 활용

✅ **DO**:
```python
# Orchestrator에서
store = ResultStore(task_uuid, base_path)
store.save_result("agent_name", response)

# 다른 에이전트에서
previous_result = store.load_result("previous_agent", PreviousResponse)
```

### 5. 로깅

✅ **DO**:
```python
logger.info("🚀 Agent: 작업 시작")
logger.info(f"✅ Agent: 완료 - {count}개 항목")
logger.warning(f"⚠️ Agent: 경고 - {message}")
logger.error(f"❌ Agent: 오류 - {error}")
```

### 6. TokenTracker 사용

✅ **DO**:
```python
from shared.utils.token_tracker import TokenTracker

response = await TokenTracker.track_async(
    self.llm.ainvoke,
    messages,
    agent_name="agent_name"
)
```

---

## 체크리스트

### 파일 생성
- [ ] `agents/{agent_name}/__init__.py`
- [ ] `agents/{agent_name}/agent.py`
- [ ] `agents/{agent_name}/schemas.py`
- [ ] `agents/{agent_name}/README.md`
- [ ] `agents/{agent_name}/prompts.yaml` (LLM 사용 시)

### 스키마
- [ ] `BaseContext` 상속한 `{Agent}Context` 정의
- [ ] `BaseResponse` 상속한 `{Agent}Response` 정의
- [ ] Field description 상세 작성 ("반드시" 키워드 활용)
- [ ] 제약 조건 명시 (ge, le, default_factory)

### 에이전트
- [ ] LLM 사용 시 `PromptLoader.load_with_schema` 적용
- [ ] `async def run(context) -> response` 구현
- [ ] 에러 처리 (try-except with status="failed")
- [ ] 로깅 추가 (이모지 포함)
- [ ] TokenTracker 사용 (LLM 호출 시)

### 프롬프트 (LLM 사용 시)
- [ ] `model` 필드 설정
- [ ] `system_prompt`에 `{json_schema}` 변수 포함
- [ ] `user_template`에 변수 정의 (`{변수명}`)

### Orchestrator 통합
- [ ] `orchestrator.py`에 import 추가
- [ ] `_execute_node`에 에이전트 실행 추가
- [ ] Context 생성 (task_uuid, 필요한 데이터)
- [ ] `ResultStore.save_result` 호출
- [ ] 병렬 실행 고려 (asyncio.gather)

---

## 예시: SecurityAgent 구조

### 파일 구조
```
agents/security_agent/
├── __init__.py          # SecurityAgent, Context, Response export
├── agent.py             # SecurityAgent 클래스
├── schemas.py           # Context, Response, SecurityAnalysis, VulnerabilityRisk
├── prompts.yaml         # system_prompt, user_template
└── README.md
```

### schemas.py 구조

```python
# 1. Context (입력)
class SecurityAgentContext(BaseContext):
    static_analysis: Dict[str, Any] = Field(...)
    user_aggregate: Dict[str, Any] = Field(...)
    git_url: str = Field(...)
    # Config.json_schema_extra 예시 포함

# 2. 중첩 모델 (LLM 출력의 일부)
class VulnerabilityRisk(BaseModel):
    category: str = Field(..., description="상세한 설명...")
    severity: Literal["High", "Medium", "Low"] = Field(...)
    description: str = Field(...)
    mitigation: str = Field(...)

# 3. LLM 출력 모델 (중간 모델)
class SecurityAnalysis(BaseModel):
    type_safety_issues: List[str] = Field(...)
    auth_patterns: List[str] = Field(...)
    vulnerability_risks: List[VulnerabilityRisk] = Field(...)
    security_score: float = Field(..., ge=0.0, le=10.0)
    recommendations: List[str] = Field(...)
    # @field_validator로 변환/정규화

# 4. Response (출력)
class SecurityAgentResponse(BaseResponse):
    security_analysis: SecurityAnalysis = Field(...)
    # Config.json_schema_extra 예시 포함
```

### prompts.yaml 구조

```yaml
version: "1.0"
model: "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

system_prompt: |
  당신은 보안 전문가입니다. 코드 분석 결과를 바탕으로 보안 위험 요소를 식별하고 개선 방안을 제시하세요.

  분석 영역:
  1. 타입 안정성 - 타입 에러가 보안에 미치는 영향
  2. 인증/인가 - 기술 스택에서 보안 관련 패턴 식별
  3. 입력 검증 - 복잡도가 높은 함수의 입력 검증 위험
  4. 취약점 위험도 - 전반적인 보안 취약점 평가

  응답 형식 (JSON):
  {json_schema}

user_template: |
  다음 코드 분석 결과를 바탕으로 보안 분석을 수행하세요:

  타입 체크 결과:
  - 에러: {type_errors}개
  - 경고: {type_warnings}개

  복잡도 분포:
  - A: {complexity_a}개
  - B: {complexity_b}개
  - C: {complexity_c}개
  - D: {complexity_d}개
  - F: {complexity_f}개

  기술 스택:
  {tech_stack}

  보안 관점에서 상세 분석을 제공해주세요.
```

### agent.py 핵심

```python
class SecurityAgent:
    def __init__(self, llm: Optional[ChatBedrockConverse] = None):
        if llm is None:
            self.llm = PromptLoader.get_llm("security_agent")
        else:
            self.llm = llm
        
        # 스키마 자동 주입
        self.prompts = PromptLoader.load_with_schema(
            "security_agent",
            response_schema_class=SecurityAnalysis
        )

    async def run(self, context: SecurityAgentContext) -> SecurityAgentResponse:
        # 1. 데이터 추출
        static_analysis = context.static_analysis
        user_aggregate = context.user_aggregate
        
        # 2. 프롬프트 생성
        system_prompt = PromptLoader.format(
            self.prompts["system_prompt"],
            json_schema=self.prompts.get("json_schema", "")
        )
        user_prompt = PromptLoader.format(
            self.prompts["user_template"],
            type_errors=...,
            complexity_a=...,
            # ...
        )
        
        # 3. LLM 호출
        messages = [SystemMessage(...), HumanMessage(...)]
        response = await TokenTracker.track_async(...)
        
        # 4. JSON 파싱
        analysis = self._parse_json_response(response.content)
        
        # 5. 응답 반환
        return SecurityAgentResponse(
            status="success",
            security_analysis=analysis
        )
```

### Orchestrator 통합

```python
# Level 3: 전문 분석
security_agent = SecurityAgent(llm=self.sonnet_llm)
security_ctx = SecurityAgentContext(
    task_uuid=task_uuid,
    static_analysis=static_response.analysis,
    user_aggregate=user_agg_response.aggregate,
    git_url=git_url,
)
security_response = await security_agent.run(security_ctx)
store.save_result("security_agent", security_response)
```

---

## 요약

### 핵심 원칙
1. **Pydantic 스키마**: 모든 입출력은 Pydantic 모델
2. **load_with_schema**: LLM 사용 시 스키마 자동 주입
3. **비동기**: `async/await` 패턴 준수
4. **에러 처리**: 모든 예외를 캐치하고 `status="failed"` 반환
5. **ResultStore**: 에이전트 결과 저장으로 재사용성 확보
6. **TokenTracker**: LLM 비용 추적
7. **로깅**: 명확한 이모지 + 메시지

### 참고 에이전트
- **LLM 사용**: SecurityAgent, QualityAgent, PerformanceAgent, ArchitectAgent
- **LLM 미사용**: StaticAnalyzer, RepoCloner, CommitAnalyzer
- **하위 에이전트**: UserSkillProfiler → CodeBatchProcessorAgent

---

**완성된 가이드입니다!** 새로운 서브에이전트 생성 시 이 가이드를 참고하세요. 🚀
