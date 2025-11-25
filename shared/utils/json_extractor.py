"""
LLM 응답에서 JSON 추출 유틸리티

중괄호 매칭, 코드 블록 처리 등을 통합하여
일관된 JSON 추출 로직을 제공합니다.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class JSONExtractor:
    """LLM 응답에서 JSON 추출 (중괄호 매칭, 코드 블록 처리)"""
    
    @staticmethod
    def extract(content: str) -> Optional[str]:
        """
        LLM 응답에서 JSON 문자열 추출
        
        전략:
        1. JSON 코드 블록 (```json ... ```)
        2. 일반 코드 블록 (``` ... ```)
        3. 중괄호 매칭
        
        Args:
            content: LLM 응답 내용
            
        Returns:
            추출된 JSON 문자열 또는 None
        """
        if not content or not content.strip():
            logger.debug("⚠️ JSONExtractor: 응답 내용이 비어있음")
            return None
        
        # 1. JSON 코드 블록에서 추출 시도
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            # 중괄호 매칭으로 완전한 JSON 객체 추출
            json_start_pos = content.find("```json")
            if json_start_pos != -1:
                brace_start = content.find("{", json_start_pos)
                if brace_start != -1:
                    brace_count = 0
                    for i in range(brace_start, len(content)):
                        if content[i] == "{":
                            brace_count += 1
                        elif content[i] == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                json_str = content[brace_start:i+1]
                                logger.debug("✅ JSONExtractor: JSON 코드 블록에서 추출 성공")
                                return json_str
        
        # 2. 일반 코드 블록에서 추출 시도
        json_match = re.search(r"```\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            # 중괄호 매칭으로 완전한 JSON 객체 추출
            code_start_pos = content.find("```")
            if code_start_pos != -1:
                brace_start = content.find("{", code_start_pos)
                if brace_start != -1:
                    brace_count = 0
                    for i in range(brace_start, len(content)):
                        if content[i] == "{":
                            brace_count += 1
                        elif content[i] == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                json_str = content[brace_start:i+1]
                                logger.debug("✅ JSONExtractor: 일반 코드 블록에서 추출 성공")
                                return json_str
        
        # 3. 중괄호 매칭을 통해 첫 번째 완전한 JSON 객체 찾기
        try:
            start_idx = content.find("{")
            if start_idx == -1:
                logger.debug("⚠️ JSONExtractor: JSON 객체 시작을 찾을 수 없음")
                return None
            
            brace_count = 0
            end_idx = start_idx
            for i in range(start_idx, len(content)):
                if content[i] == "{":
                    brace_count += 1
                elif content[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break
            
            if brace_count != 0:
                logger.debug("⚠️ JSONExtractor: JSON 객체가 완전하지 않음")
                return None
            
            json_str = content[start_idx:end_idx]
            logger.debug("✅ JSONExtractor: 중괄호 매칭으로 JSON 추출 성공")
            return json_str
            
        except Exception as e:
            logger.debug(f"⚠️ JSONExtractor: JSON 추출 중 오류: {e}")
            return None

