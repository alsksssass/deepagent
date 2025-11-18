"""
YAML 기반 프롬프트 로더

에이전트별 프롬프트를 YAML 파일로 관리하고 캐싱하여 성능 최적화
"""

import yaml
import importlib
import inspect
import os
from pathlib import Path
from functools import lru_cache
from typing import Dict, Any, Optional, Type
import logging

from pydantic import BaseModel
from langchain_aws import ChatBedrockConverse
from shared.schemas.common import BaseResponse
from .schema_prompt_generator import SchemaPromptGenerator

logger = logging.getLogger(__name__)


class PromptLoader:
    """
    YAML 프롬프트 로더 (캐싱 지원)

    사용 예시:
        prompts = PromptLoader.load("commit_evaluator")
        system_prompt = prompts["system_prompt"]
        user_template = PromptLoader.format(
            prompts["user_template"],
            commit_hash="abc123",
            message="Add feature"
        )
    """

    @staticmethod
    @lru_cache(maxsize=32)
    def load(agent_name: str) -> Dict[str, Any]:
        """
        에이전트별 프롬프트 YAML 로드

        Args:
            agent_name: 에이전트 이름 (예: "commit_evaluator", "planner")

        Returns:
            prompts: {
                "system_prompt": "...",
                "user_template": "...",
                "model": "...",
                ...
            }

        Raises:
            FileNotFoundError: prompts.yaml 파일이 없을 때
            yaml.YAMLError: YAML 파싱 실패 시
        """
        base_path = Path(__file__).parent.parent.parent

        # planner는 core/planner/prompts.yaml에 있음
        if agent_name == "planner":
            prompt_path = base_path / "core" / "planner" / "prompts.yaml"
        else:
            # agents/{agent_name}/prompts.yaml 경로
            prompt_path = base_path / "agents" / agent_name / "prompts.yaml"

        if not prompt_path.exists():
            expected_location = (
                f"core/planner/prompts.yaml" if agent_name == "planner"
                else f"agents/{agent_name}/prompts.yaml"
            )
            raise FileNotFoundError(
                f"Prompt file not found: {prompt_path}\n"
                f"Expected location: {expected_location}"
            )

        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompts = yaml.safe_load(f)

            logger.debug(f"✅ Loaded prompts for {agent_name} (cached)")
            return prompts

        except yaml.YAMLError as e:
            logger.error(f"❌ YAML parsing error in {prompt_path}: {e}")
            raise

    @staticmethod
    def format(template: str, **kwargs) -> str:
        """
        프롬프트 템플릿 변수 치환

        Args:
            template: 템플릿 문자열 (예: "Hash: {commit_hash}")
            **kwargs: 치환할 변수들

        Returns:
            치환된 문자열

        Example:
            >>> template = "Commit {hash} by {author}"
            >>> PromptLoader.format(template, hash="abc123", author="John")
            "Commit abc123 by John"
        """
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning(f"⚠️ Missing template variable: {e}")
            return template

    @staticmethod
    def get_model(agent_name: str) -> str:
        """
        에이전트의 기본 모델 ID 반환

        Args:
            agent_name: 에이전트 이름

        Returns:
            model_id: Bedrock 모델 ID (기본값: claude-3-5-sonnet)
        """
        prompts = PromptLoader.load(agent_name)
        return prompts.get("model", "us.anthropic.claude-3-5-sonnet-20241022-v2:0")

    @staticmethod
    @lru_cache(maxsize=16)
    def get_llm(agent_name: str) -> ChatBedrockConverse:
        """
        에이전트의 YAML 설정을 기반으로 ChatBedrockConverse 인스턴스 생성 및 반환
        
        YAML에서 모델 ID와 설정을 로드하여 LLM 인스턴스를 생성합니다.
        같은 에이전트에 대해서는 캐싱된 인스턴스를 반환합니다.
        
        Args:
            agent_name: 에이전트 이름
            
        Returns:
            ChatBedrockConverse 인스턴스
            
        Example:
            >>> llm = PromptLoader.get_llm("security_agent")
            >>> response = await llm.ainvoke([SystemMessage(...), HumanMessage(...)])
        """
        prompts = PromptLoader.load(agent_name)
        model_id = prompts.get("model", "anthropic.claude-3-5-sonnet-20241022-v2:0")
        
        # YAML에서 모델 설정 로드 (선택적)
        model_config = prompts.get("model_config", {})
        
        # 우선순위: 환경 변수 > YAML model_config > 기본값
        region = (
            os.getenv("AWS_DEFAULT_REGION") or 
            model_config.get("region") or 
            "us-east-1"
        )
        temperature = model_config.get("temperature", 0.0)
        max_tokens = model_config.get("max_tokens", 4096)
        
        logger.debug(
            f"✅ LLM 생성: {agent_name} - model={model_id}, "
            f"region={region}, temperature={temperature}, max_tokens={max_tokens}"
        )
        
        return ChatBedrockConverse(
            model=model_id,
            region_name=region,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @staticmethod
    def clear_cache():
        """
        캐시 초기화 (테스트 또는 프롬프트 변경 시)

        사용 예시:
            PromptLoader.clear_cache()  # 캐시 삭제
            prompts = PromptLoader.load("commit_evaluator")  # 재로드
            llm = PromptLoader.get_llm("security_agent")  # 재생성
        """
        PromptLoader.load.cache_clear()
        PromptLoader.get_llm.cache_clear()
        logger.info("🔄 Prompt and LLM cache cleared")

    @staticmethod
    def validate_prompts(agent_name: str, required_keys: list[str]) -> bool:
        """
        프롬프트 YAML의 필수 키 검증

        Args:
            agent_name: 에이전트 이름
            required_keys: 필수 키 리스트 (예: ["system_prompt", "user_template"])

        Returns:
            True if all required keys exist

        Raises:
            ValueError: 필수 키 누락 시
        """
        prompts = PromptLoader.load(agent_name)
        missing_keys = [key for key in required_keys if key not in prompts]

        if missing_keys:
            raise ValueError(
                f"Missing required prompt keys for {agent_name}: {missing_keys}"
            )

        logger.debug(f"✅ Prompt validation passed for {agent_name}")
        return True

    @staticmethod
    def load_with_schema(
        agent_name: str,
        response_schema_class: Optional[Type[BaseModel]] = None,
        schema_key: str = "json_schema"
    ) -> Dict[str, Any]:
        """
        프롬프트 로드 + 스키마 자동 주입 (하이브리드 방식)
        
        하이브리드 동작:
        1. 커스터마이징된 스키마가 있으면 우선 사용 (custom_json_schema)
        2. response_schema_class가 제공되면 자동 생성
        3. auto_detect_schema가 true이면 자동 감지 시도
        4. 없으면 기본 프롬프트만 반환 (하위 호환성)
        
        Args:
            agent_name: 에이전트 이름
            response_schema_class: Response 스키마 클래스 (None이면 자동 감지 시도)
            schema_key: 프롬프트 템플릿에서 사용할 변수명 (기본: "json_schema")
            
        Returns:
            프롬프트 dict (json_schema 변수 포함)
            
        Example:
            >>> from agents.security_agent.schemas import SecurityAnalysis
            >>> prompts = PromptLoader.load_with_schema(
            ...     "security_agent",
            ...     response_schema_class=SecurityAnalysis
            ... )
            >>> system_prompt = PromptLoader.format(
            ...     prompts["system_prompt"],
            ...     json_schema=prompts["json_schema"]
            ... )
        """
        # 1. 기본 프롬프트 로드
        prompts = PromptLoader.load(agent_name)
        
        # 2. 커스터마이징된 스키마가 있으면 우선 사용
        if "custom_json_schema" in prompts:
            prompts[schema_key] = prompts["custom_json_schema"]
            logger.debug(f"✅ Using custom JSON schema for {agent_name}")
            return prompts
        
        # 3. 스키마 클래스가 제공되면 자동 생성
        if response_schema_class:
            try:
                prompts[schema_key] = SchemaPromptGenerator.generate_json_schema_example(
                    response_schema_class
                )
                logger.debug(f"✅ Auto-generated JSON schema for {agent_name} from {response_schema_class.__name__}")
                return prompts
            except Exception as e:
                logger.warning(f"⚠️ Failed to generate schema for {agent_name}: {e}")
        
        # 4. 자동 감지 시도 (선택적)
        if prompts.get("auto_detect_schema", False):
            schema_class = PromptLoader._detect_response_schema(agent_name)
            if schema_class:
                try:
                    prompts[schema_key] = SchemaPromptGenerator.generate_json_schema_example(
                        schema_class
                    )
                    logger.debug(f"✅ Auto-detected and generated JSON schema for {agent_name}")
                    return prompts
                except Exception as e:
                    logger.warning(f"⚠️ Failed to generate schema from auto-detection: {e}")
        
        # 5. 스키마가 없으면 빈 문자열 (하위 호환성)
        prompts[schema_key] = ""
        logger.debug(f"⚠️ No JSON schema generated for {agent_name} (using empty string)")
        return prompts

    @staticmethod
    def _detect_response_schema(agent_name: str) -> Optional[Type[BaseModel]]:
        """
        에이전트 이름에서 Response 스키마 클래스 자동 감지
        
        예: "security_agent" → SecurityAgentResponse
            "commit_evaluator" → CommitEvaluatorResponse
        
        Args:
            agent_name: 에이전트 이름
            
        Returns:
            Response 스키마 클래스 또는 None
        """
        try:
            # agents/{agent_name}/schemas.py 모듈 로드
            module_name = f"agents.{agent_name}.schemas"
            module = importlib.import_module(module_name)
            
            # Response로 끝나는 클래스 찾기 (BaseResponse 제외)
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and 
                    name.endswith("Response") and 
                    name != "BaseResponse" and
                    issubclass(obj, BaseResponse) and
                    obj != BaseResponse):
                    logger.debug(f"✅ Auto-detected schema: {name} for {agent_name}")
                    return obj
            
            # Response가 없으면 Analysis로 끝나는 클래스 찾기
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and 
                    name.endswith("Analysis") and 
                    issubclass(obj, BaseModel) and
                    obj != BaseModel):
                    logger.debug(f"✅ Auto-detected schema: {name} for {agent_name}")
                    return obj
                    
        except ImportError as e:
            logger.debug(f"⚠️ Could not import schemas for {agent_name}: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Error detecting schema for {agent_name}: {e}")
        
        return None
