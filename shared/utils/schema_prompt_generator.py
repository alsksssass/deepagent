"""
Schema-based Prompt Generator

Pydantic 스키마에서 프롬프트용 JSON 스키마 예제를 자동 생성하는 유틸리티
"""

import json
import logging
from typing import Type, Dict, Any, Optional, List
from functools import lru_cache
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SchemaPromptGenerator:
    """
    Pydantic 스키마에서 프롬프트용 JSON 스키마 예제를 자동 생성
    
    하이브리드 방식:
    - 기본: Pydantic 스키마에서 자동 생성
    - 커스터마이징: prompts.yaml에서 오버라이드 가능
    """

    @staticmethod
    @lru_cache(maxsize=64)
    def generate_json_schema_example(
        schema_class: Type[BaseModel],
        include_description: bool = True,
        max_depth: int = 3
    ) -> str:
        """
        Pydantic 모델에서 JSON 스키마 예제 생성
        
        Args:
            schema_class: Pydantic 모델 클래스
            include_description: Field description 포함 여부
            max_depth: 중첩 깊이 제한 (무한 재귀 방지)
            
        Returns:
            마크다운 형식의 JSON 예제 문자열
            
        Example:
            >>> from agents.security_agent.schemas import SecurityAnalysis
            >>> example = SchemaPromptGenerator.generate_json_schema_example(SecurityAnalysis)
            >>> print(example)
            ```json
            {
              "type_safety_issues": ["example_string"],
              "security_score": 0.0,
              ...
            }
            ```
        """
        try:
            # 1. Pydantic JSON Schema 생성
            json_schema = schema_class.model_json_schema()
            
            # 2. $defs 추출 (중첩 모델 정의)
            definitions = json_schema.get("$defs", {})
            # definitions도 확인 (하위 호환성)
            if not definitions:
                definitions = json_schema.get("definitions", {})
            
            # 3. 예제 값 생성 ($defs 전달)
            example = SchemaPromptGenerator._generate_example_from_schema(
                json_schema, 
                max_depth=max_depth,
                current_depth=0,
                definitions=definitions
            )
            
            # 4. 마크다운 포맷팅
            formatted = SchemaPromptGenerator._format_as_markdown_code_block(
                example,
                include_description=include_description,
                schema_class=schema_class
            )
            
            logger.debug(f"✅ JSON 스키마 예제 생성: {schema_class.__name__}")
            return formatted
            
        except Exception as e:
            logger.error(f"❌ JSON 스키마 예제 생성 실패 ({schema_class.__name__}): {e}")
            # 기본 예제 반환
            return "```json\n{}\n```"

    @staticmethod
    def _generate_example_from_schema(
        json_schema: Dict[str, Any],
        max_depth: int = 3,
        current_depth: int = 0,
        definitions: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        JSON Schema에서 예제 값 생성 (재귀적)
        
        Args:
            json_schema: JSON Schema dict
            max_depth: 최대 중첩 깊이
            current_depth: 현재 깊이
            definitions: $defs 딕셔너리 ($ref 참조 해결용)
            
        Returns:
            예제 값 (dict, list, 또는 기본 타입)
        """
        if current_depth >= max_depth:
            return None
        
        # $ref 참조 처리
        if "$ref" in json_schema:
            ref_path = json_schema["$ref"]
            # #/definitions/ModelName 또는 #/$defs/ModelName 형식
            if ref_path.startswith("#/$defs/") or ref_path.startswith("#/definitions/"):
                model_name = ref_path.split("/")[-1]
                if definitions and model_name in definitions:
                    # 참조된 모델의 스키마로 재귀 호출
                    return SchemaPromptGenerator._generate_example_from_schema(
                        definitions[model_name],
                        max_depth=max_depth,
                        current_depth=current_depth + 1,
                        definitions=definitions
                    )
            # 참조를 해결할 수 없으면 None 반환
            logger.debug(f"⚠️ $ref 참조를 해결할 수 없음: {ref_path}")
            return None
        
        # allOf, anyOf, oneOf 처리
        if "allOf" in json_schema:
            # allOf의 첫 번째 스키마 사용
            return SchemaPromptGenerator._generate_example_from_schema(
                json_schema["allOf"][0], max_depth, current_depth, definitions
            )
        
        # enum 처리
        if "enum" in json_schema:
            return json_schema["enum"][0]
        
        # 타입별 처리
        schema_type = json_schema.get("type")
        
        if schema_type == "object":
            properties = json_schema.get("properties", {})
            example = {}
            
            # 모든 필드를 포함 (예제 생성 목적)
            # required 필드는 반드시 포함
            required_fields = json_schema.get("required", [])
            for prop_name, prop_schema in properties.items():
                prop_example = SchemaPromptGenerator._generate_example_from_schema(
                    prop_schema, max_depth, current_depth + 1, definitions
                )
                # required 필드는 None이어도 포함 (기본값 생성)
                if prop_name in required_fields or prop_example is not None:
                    if prop_example is None:
                        # required 필드인데 예제 생성 실패 시 기본값 생성 시도
                        prop_example = SchemaPromptGenerator._generate_default_value(prop_schema)
                    if prop_example is not None:
                        example[prop_name] = prop_example
            
            return example if example else {}
        
        elif schema_type == "array":
            items_schema = json_schema.get("items", {})
            item_example = SchemaPromptGenerator._generate_example_from_schema(
                items_schema, max_depth, current_depth + 1, definitions
            )
            # 배열은 최대 2개 항목으로 제한
            if item_example is not None:
                return [item_example]
            # default_factory가 있는 경우 빈 배열이 아닌 예제 배열 반환
            return ["example_string"] if items_schema.get("type") == "string" else []
        
        elif schema_type == "string":
            # description에서 힌트 추출
            description = json_schema.get("description", "").lower()
            default = json_schema.get("default")
            
            if default is not None:
                return default
            
            # 특수 케이스 처리
            if "email" in description or "이메일" in description:
                return "user@example.com"
            elif "hash" in description or "해시" in description:
                return "abc1234"
            elif "url" in description or "uri" in description:
                return "https://example.com"
            elif "path" in description or "경로" in description:
                return "/path/to/file"
            elif "date" in description or "날짜" in description:
                return "2025-01-15"
            elif "time" in description or "시간" in description:
                return "2025-01-15T10:00:00"
            elif "평가" in description or "evaluation" in description or "assessment" in description:
                return "평가 설명 예시입니다."
            # 기술 스택은 배열이므로 여기서 처리하지 않음
            
            # format 처리
            format_type = json_schema.get("format")
            if format_type == "email":
                return "user@example.com"
            elif format_type == "uri":
                return "https://example.com"
            elif format_type == "date-time":
                return "2025-01-15T10:00:00"
            
            return "example_string"
        
        elif schema_type == "number":
            default = json_schema.get("default")
            if default is not None:
                return default
            
            # 범위 처리
            minimum = json_schema.get("minimum")
            maximum = json_schema.get("maximum")
            
            if minimum is not None and maximum is not None:
                return (minimum + maximum) / 2
            elif minimum is not None:
                return minimum
            elif maximum is not None:
                return maximum
            
            return 0.0
        
        elif schema_type == "integer":
            default = json_schema.get("default")
            if default is not None:
                return default
            
            minimum = json_schema.get("minimum")
            maximum = json_schema.get("maximum")
            
            if minimum is not None and maximum is not None:
                return (minimum + maximum) // 2
            elif minimum is not None:
                return minimum
            elif maximum is not None:
                return maximum
            
            return 0
        
        elif schema_type == "boolean":
            return json_schema.get("default", True)
        
        elif schema_type == "null":
            return None
        
        # 타입이 없으면 기본값
        return None
    
    @staticmethod
    def _generate_default_value(json_schema: Dict[str, Any]) -> Any:
        """
        필수 필드의 기본값 생성 (예제 생성 실패 시)
        
        Args:
            json_schema: JSON Schema dict
            
        Returns:
            기본값
        """
        schema_type = json_schema.get("type")
        if schema_type == "object":
            return {}
        elif schema_type == "array":
            return []
        elif schema_type == "string":
            return "example_string"
        elif schema_type == "number":
            return 0.0
        elif schema_type == "integer":
            return 0
        elif schema_type == "boolean":
            return True
        return None

    @staticmethod
    def _format_as_markdown_code_block(
        example: Any,
        include_description: bool = True,
        schema_class: Optional[Type[BaseModel]] = None
    ) -> str:
        """
        예제를 마크다운 코드 블록으로 포맷팅
        
        Args:
            example: 예제 값 (dict, list, 또는 기본 타입)
            include_description: 설명 포함 여부
            schema_class: Pydantic 모델 클래스 (description 추출용)
            
        Returns:
            마크다운 형식의 JSON 코드 블록 + 설명
        """
        try:
            json_str = json.dumps(example, indent=2, ensure_ascii=False)
            result = f"```json\n{json_str}\n```"
            
            # Field description에서 중요한 설명 추출
            if include_description and schema_class:
                descriptions = SchemaPromptGenerator._extract_field_descriptions(schema_class)
                if descriptions:
                    result += "\n\n**중요 사항:**\n"
                    for field_name, desc in descriptions.items():
                        if any(keyword in desc for keyword in ["반드시", "문자열 배열이 아닙니다", "숫자가 아닙니다"]):
                            result += f"- `{field_name}`: {desc}\n"
            
            return result
        except (TypeError, ValueError) as e:
            logger.warning(f"⚠️ JSON 직렬화 실패: {e}")
            return "```json\n{}\n```"
    
    @staticmethod
    def _extract_field_descriptions(schema_class: Type[BaseModel]) -> Dict[str, str]:
        """
        Pydantic 모델에서 Field description 추출
        
        Args:
            schema_class: Pydantic 모델 클래스
            
        Returns:
            필드명 -> description 매핑
        """
        descriptions = {}
        try:
            json_schema = schema_class.model_json_schema()
            properties = json_schema.get("properties", {})
            
            for field_name, field_schema in properties.items():
                desc = field_schema.get("description", "")
                if desc and any(keyword in desc for keyword in ["반드시", "문자열 배열이 아닙니다", "숫자가 아닙니다"]):
                    descriptions[field_name] = desc
        except Exception as e:
            logger.debug(f"⚠️ Field description 추출 실패: {e}")
        
        return descriptions

    @staticmethod
    def generate_schema_description(
        schema_class: Type[BaseModel]
    ) -> str:
        """
        스키마 클래스의 설명 생성 (선택적 기능)
        
        Args:
            schema_class: Pydantic 모델 클래스
            
        Returns:
            스키마 설명 문자열
        """
        json_schema = schema_class.model_json_schema()
        title = json_schema.get("title", schema_class.__name__)
        description = json_schema.get("description", "")
        
        if description:
            return f"**{title}**: {description}"
        return f"**{title}**"

    @staticmethod
    def clear_cache():
        """
        캐시 초기화 (테스트 또는 스키마 변경 시)
        
        사용 예시:
            SchemaPromptGenerator.clear_cache()
            example = SchemaPromptGenerator.generate_json_schema_example(SchemaClass)
        """
        SchemaPromptGenerator.generate_json_schema_example.cache_clear()
        logger.info("🔄 Schema prompt generator cache cleared")

