"""
Skill Level Calculator

스킬 레벨링 및 개발자 타입별 통계 계산 유틸리티

기능:
- base_score 기반 경험치 계산
- 경험치를 레벨로 변환
- 개발자 타입별 기술 보유율 계산
- 개발자 타입별 레벨링
"""

import logging
from typing import Dict, List, Any, Optional
from collections import defaultdict
import chromadb
from shared.tools.chromadb_tools import get_chroma_client

logger = logging.getLogger(__name__)


class SkillLevelCalculator:
    """스킬 레벨링 및 개발자 타입별 통계 계산 유틸리티"""

    # 레벨 경험치 구간 (base_score 합산 기준)
    # 레벨 1-10까지 정의 (게임 스타일 레벨링)
    LEVEL_THRESHOLDS = {
        1: 0,       # Lv.1 (초보): 0-99
        2: 100,     # Lv.2 (입문): 100-299
        3: 300,     # Lv.3 (초급): 300-599
        4: 600,     # Lv.4 (중급): 600-999
        5: 1000,    # Lv.5 (고급): 1000-1999
        6: 2000,    # Lv.6 (전문가): 2000-3999
        7: 4000,    # Lv.7 (시니어): 4000-6999
        8: 7000,    # Lv.8 (리드): 7000-9999
        9: 10000,   # Lv.9 (아키텍트): 10000-14999
        10: 15000,  # Lv.10 (마스터): 15000+
    }

    LEVEL_NAMES = {
        1: "초보",
        2: "입문",
        3: "초급",
        4: "중급",
        5: "고급",
        6: "전문가",
        7: "시니어",
        8: "리드",
        9: "아키텍트",
        10: "마스터",
    }

    @staticmethod
    def calculate_total_experience(skills: List[Dict[str, Any]]) -> int:
        """
        중복 제거된 스킬들의 base_score 합산 (경험치 계산)

        Args:
            skills: 스킬 리스트 (각 스킬은 skill_name, level, base_score 포함)

        Returns:
            총 경험치 (base_score 합산)
        """
        # 중복 제거: skill_name + level을 키로 사용
        unique_skills = {}
        for skill in skills:
            skill_name = skill.get("skill_name", "")
            level = skill.get("level", "")
            key = f"{skill_name}_{level}"
            
            # 중복되지 않은 스킬만 추가 (첫 번째 값 사용)
            if key not in unique_skills:
                base_score = skill.get("base_score", 0)
                if isinstance(base_score, str):
                    try:
                        base_score = int(base_score)
                    except (ValueError, TypeError):
                        base_score = 0
                unique_skills[key] = int(base_score) if base_score else 0

        total_experience = sum(unique_skills.values())
        logger.debug(
            f"📊 경험치 계산: {len(unique_skills)}개 고유 스킬, "
            f"총 {total_experience} EXP"
        )
        return total_experience

    @staticmethod
    def calculate_level(experience: int) -> Dict[str, Any]:
        """
        경험치를 레벨로 변환

        Args:
            experience: 총 경험치

        Returns:
            {
                "level": int,  # 현재 레벨
                "level_name": str,  # 레벨 이름
                "experience": int,  # 현재 경험치
                "current_level_exp": int,  # 현재 레벨 시작 경험치
                "next_level_exp": int,  # 다음 레벨 필요 경험치
                "progress_percentage": float,  # 현재 레벨 진행률 (%)
            }
        """
        thresholds = SkillLevelCalculator.LEVEL_THRESHOLDS
        level_names = SkillLevelCalculator.LEVEL_NAMES

        # 현재 레벨 찾기
        current_level = 1
        current_level_exp = 0
        next_level_exp = thresholds.get(2, 100)

        for level in sorted(thresholds.keys(), reverse=True):
            if experience >= thresholds[level]:
                current_level = level
                current_level_exp = thresholds[level]
                # 다음 레벨 경험치 찾기
                next_level = level + 1
                if next_level in thresholds:
                    next_level_exp = thresholds[next_level]
                else:
                    # 최대 레벨인 경우
                    next_level_exp = thresholds[level] + 5000  # 임의의 큰 값
                break

        # 진행률 계산
        if next_level_exp > current_level_exp:
            progress = (experience - current_level_exp) / (
                next_level_exp - current_level_exp
            )
            progress_percentage = min(100.0, max(0.0, progress * 100))
        else:
            progress_percentage = 100.0  # 최대 레벨

        level_name = level_names.get(current_level, f"Lv.{current_level}")

        return {
            "level": current_level,
            "level_name": level_name,
            "experience": experience,
            "current_level_exp": current_level_exp,
            "next_level_exp": next_level_exp,
            "progress_percentage": round(progress_percentage, 1),
        }

    @staticmethod
    async def calculate_developer_type_coverage(
        skills: List[Dict[str, Any]], persist_dir: str
    ) -> Dict[str, Dict[str, Any]]:
        """
        개발자 타입별 기술 보유율 계산

        Args:
            skills: 사용자가 보유한 스킬 리스트
            persist_dir: ChromaDB 저장 디렉토리

        Returns:
            {
                "Backend": {
                    "owned_count": 25,
                    "total_count": 200,
                    "percentage": 12.5,
                    "level": {...},  # 타입별 레벨 정보
                },
                ...
            }
        """
        try:
            # ChromaDB에서 전체 스킬 조회
            client = get_chroma_client(persist_dir)
            collection = client.get_collection(name="skill_charts")

            # 전체 스킬 메타데이터 가져오기
            all_skills = collection.get(include=["metadatas"])
            all_metadatas = all_skills.get("metadatas", [])

            # 개발자 타입별 전체 스킬 수 계산
            type_total_skills = defaultdict(set)  # 중복 제거를 위해 set 사용
            type_total_experience = defaultdict(int)  # 타입별 총 경험치

            for metadata in all_metadatas:
                developer_type = metadata.get("developer_type", "All")
                base_score = int(metadata.get("base_score", 0))
                skill_name = metadata.get("skill_name", "")
                level = metadata.get("level", "")
                key = f"{skill_name}_{level}"

                # "All"은 모든 타입에 포함
                if developer_type == "All":
                    # 모든 타입에 추가 (하지만 별도 카운트는 하지 않음)
                    pass
                else:
                    # 콤마로 구분된 타입들 처리 (예: "Backend,Fullstack")
                    types = [t.strip() for t in developer_type.split(",")]
                    for dev_type in types:
                        type_total_skills[dev_type].add(key)
                        type_total_experience[dev_type] += base_score

            # 사용자가 보유한 스킬을 타입별로 분류
            user_skills_by_type = defaultdict(set)
            user_experience_by_type = defaultdict(int)

            # 중복 제거된 사용자 스킬
            unique_user_skills = {}
            for skill in skills:
                skill_name = skill.get("skill_name", "")
                level = skill.get("level", "")
                key = f"{skill_name}_{level}"
                base_score = skill.get("base_score", 0)
                if isinstance(base_score, str):
                    try:
                        base_score = int(base_score)
                    except (ValueError, TypeError):
                        base_score = 0
                base_score = int(base_score) if base_score else 0

                if key not in unique_user_skills:
                    unique_user_skills[key] = base_score

            # 각 사용자 스킬의 developer_type 찾기
            # 전체 메타데이터에서 직접 찾기 (효율성 향상)
            skill_metadata_map = {}
            for metadata in all_metadatas:
                skill_name = metadata.get("skill_name", "")
                level = metadata.get("level", "")
                key = f"{skill_name}_{level}"
                skill_metadata_map[key] = metadata

            for key, base_score in unique_user_skills.items():
                # 메타데이터 맵에서 직접 조회
                metadata = skill_metadata_map.get(key)
                
                if metadata:
                    developer_type = metadata.get("developer_type", "All")

                    # "All"은 모든 타입에 포함하지 않음 (공통으로만 처리)
                    if developer_type == "All":
                        # All 타입은 별도로 카운트하지 않음
                        pass
                    else:
                        # 콤마로 구분된 타입들 처리
                        types = [t.strip() for t in developer_type.split(",")]
                        for dev_type in types:
                            user_skills_by_type[dev_type].add(key)
                            user_experience_by_type[dev_type] += base_score

            # 타입별 보유율 계산
            type_coverage = {}
            for dev_type in set(list(type_total_skills.keys()) + list(user_skills_by_type.keys())):
                total_count = len(type_total_skills.get(dev_type, set()))
                owned_count = len(user_skills_by_type.get(dev_type, set()))
                
                if total_count > 0:
                    percentage = (owned_count / total_count) * 100
                else:
                    percentage = 0.0

                # 타입별 경험치 및 레벨 계산
                type_exp = user_experience_by_type.get(dev_type, 0)
                type_level = SkillLevelCalculator.calculate_level(type_exp)

                type_coverage[dev_type] = {
                    "owned_count": owned_count,
                    "total_count": total_count,
                    "percentage": round(percentage, 1),
                    "experience": type_exp,
                    "level": type_level,
                }

            # 퍼센티지 내림차순 정렬
            sorted_coverage = dict(
                sorted(
                    type_coverage.items(),
                    key=lambda x: x[1]["percentage"],
                    reverse=True,
                )
            )

            logger.info(
                f"📊 개발자 타입별 보유율 계산 완료: {len(sorted_coverage)}개 타입"
            )
            return sorted_coverage

        except Exception as e:
            logger.error(f"❌ 개발자 타입별 보유율 계산 실패: {e}", exc_info=True)
            return {}

    @staticmethod
    def get_developer_type_levels(
        coverage: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        개발자 타입별 레벨 정보 추출

        Args:
            coverage: calculate_developer_type_coverage 결과

        Returns:
            {
                "Backend": {
                    "level": 5,
                    "level_name": "고급",
                    "experience": 1200,
                    ...
                },
                ...
            }
        """
        type_levels = {}
        for dev_type, data in coverage.items():
            if "level" in data:
                type_levels[dev_type] = data["level"]
        return type_levels

