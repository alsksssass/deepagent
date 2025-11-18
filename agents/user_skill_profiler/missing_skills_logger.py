"""MissingSkillsLogger - 미등록 스킬 로깅"""

import csv
import json
import logging
from pathlib import Path
from typing import List
from datetime import datetime

from .schemas import MissingSkillInfo

logger = logging.getLogger(__name__)


class MissingSkillsLogger:
    """
    미등록 스킬을 CSV 및 JSON 형식으로 로깅

    CSV 형식은 skill_charts.csv와 호환되도록 설계
    """

    def __init__(self, result_store_path: str):
        """
        Args:
            result_store_path: ResultStore 경로 (예: data/analyze/{task_uuid}/results)
        """
        self.result_store_path = Path(result_store_path)
        self.logs_dir = self.result_store_path.parent / "missing_skills"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def save_missing_skills(
        self,
        missing_skills: List[MissingSkillInfo],
        task_uuid: str,
    ) -> str:
        """
        미등록 스킬을 CSV 및 JSON으로 저장 (필터링 적용)

        Args:
            missing_skills: 미등록 스킬 리스트
            task_uuid: 작업 UUID

        Returns:
            CSV 파일 경로 (str)
        """
        if not missing_skills:
            logger.warning("저장할 미등록 스킬이 없습니다")
            return ""

        # 필터링 적용: 불필요한 미등록 스킬 제거
        filtered_skills = [
            skill for skill in missing_skills
            if not self._should_filter_missing_skill(skill)
        ]

        filtered_count = len(missing_skills) - len(filtered_skills)
        if filtered_count > 0:
            logger.info(
                f"🔍 미등록 스킬 필터링: {filtered_count}개 제거 "
                f"({len(missing_skills)} → {len(filtered_skills)})"
            )

        if not filtered_skills:
            logger.info("필터링 후 저장할 미등록 스킬이 없습니다")
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = self.logs_dir / f"missing_skills_{task_uuid}_{timestamp}.csv"
        json_path = self.logs_dir / f"missing_skills_{task_uuid}_{timestamp}.json"

        # CSV 저장 (skill_charts.csv 호환 형식)
        self._save_csv(filtered_skills, csv_path)

        # JSON 저장 (디버깅 및 재처리용)
        self._save_json(filtered_skills, json_path)

        logger.info(f"📝 미등록 스킬 {len(filtered_skills)}개 저장 완료")
        logger.info(f"   CSV: {csv_path}")
        logger.info(f"   JSON: {json_path}")

        return str(csv_path)
    
    def _should_filter_missing_skill(self, skill: MissingSkillInfo) -> bool:
        """
        미등록 스킬 필터링 로직
        
        Args:
            skill: 미등록 스킬 정보
            
        Returns:
            True: 필터링해야 함 (제거), False: 유지
        """
        skill_name_lower = skill.suggested_skill_name.lower()
        code_snippet_lower = skill.code_snippet.lower()
        description_lower = skill.description.lower()
        
        # 1. 기본 Python 문법 제외
        basic_syntax_patterns = [
            "if __name__",
            "__main__",
            "def ",
            "class ",
            "import ",
            "from ",
            "return ",
            "if ",
            "for ",
            "while ",
            "else",
            "elif",
        ]
        
        # 스킬 이름이 기본 문법과 관련된 경우
        basic_syntax_keywords = [
            "if __name__", "__main__", "main", "function", "class", 
            "import", "return", "if", "for", "while", "else", "elif"
        ]
        if any(keyword in skill_name_lower for keyword in basic_syntax_keywords):
            # 코드 스니펫에서도 기본 문법만 사용하는 경우 필터링
            if any(pattern in code_snippet_lower for pattern in basic_syntax_patterns):
                logger.debug(f"필터링: 기본 문법 - {skill.suggested_skill_name}")
                return True
        
        # 2. 표준 라이브러리 기본 사용 제외
        stdlib_modules = [
            "os.path", "os.listdir", "os.exists", "os.getcwd", "os.basename",
            "sys.argv", "sys.path", "sys.exit",
            "pathlib.path", "pathlib.path",
            "datetime.datetime", "datetime.date",
            "json.load", "json.dump", "json.loads", "json.dumps",
            "csv.reader", "csv.writer",
            "collections.", "itertools.",
            "random.", "math.",
            "socket.gethostname", "socket.",
        ]
        
        # 표준 라이브러리 사용 여부 확인
        uses_stdlib = any(module in code_snippet_lower for module in stdlib_modules)
        
        # 스킬 이름이 표준 라이브러리 관련인 경우
        stdlib_names = [
            "os 모듈", "os 사용", "sys 모듈", "pathlib", 
            "json", "csv", "datetime", "random", "math",
            "socket", "os.path", "sys.argv"
        ]
        if any(name in skill_name_lower for name in stdlib_names):
            if uses_stdlib or skill.suggested_level == "Basic":
                logger.debug(f"필터링: 표준 라이브러리 기본 사용 - {skill.suggested_skill_name}")
                return True
        
        # 3. 너무 일반적인 이름 제외
        generic_names = [
            "이미지 처리", "데이터 처리", "파일 처리", "문자열 처리",
            "이미지 전처리", "데이터 전처리", "코드 실행", "모듈 실행",
            "함수 정의", "클래스 정의", "변수 선언", "리스트 처리",
            "딕셔너리 처리", "반복문", "조건문", "예외 처리",
            "파일 읽기", "파일 쓰기", "파일 열기", "파일 닫기",
            "메인 함수", "main 함수", "메인 함수 정의", "main 함수 실행",
            "이미지 뷰어", "이미지 뷰어 ui", "이미지 뷰어 구현",
            "cctv 이미지", "cctv 영상", "cctv 처리",
            "객체 탐지 및 시각화", "객체 탐지 및",  # 너무 일반적
            "리스트 역순", "리스트 처리", "리스트 출력",
        ]
        if skill.suggested_skill_name in generic_names:
            logger.debug(f"필터링: 일반적인 이름 - {skill.suggested_skill_name}")
            return True
        
        # 일반적인 패턴 포함 여부 확인
        generic_patterns = [
            "뷰어", "viewer", "처리", "processing", "구현", "implementation",
            "정의", "definition", "실행", "execution", "사용", "usage",
        ]
        # 스킬 이름이 너무 일반적인 패턴만 포함하는 경우
        if len(skill.suggested_skill_name.split()) <= 3:  # 짧은 이름
            if any(pattern in skill_name_lower for pattern in generic_patterns):
                # 특정 라이브러리/프레임워크 이름이 없는 경우
                if not any(specific in skill_name_lower for specific in [
                    "yolov8", "yolo", "ultralytics", "fastapi", "django", 
                    "flask", "pytorch", "tensorflow", "keras", "opencv",
                    "cv2", "aiohttp", "asyncio", "sqlalchemy", "pandas",
                    "numpy", "matplotlib", "scikit", "detectron"
                ]):
                    logger.debug(f"필터링: 일반적인 패턴 - {skill.suggested_skill_name}")
                    return True
        
        # 4. 이미 기존 스킬로 커버 가능한 것 제외 (카테고리 기반)
        # 예: OpenCV 사용 → "컴퓨터 비전" 카테고리로 커버 가능
        # 예: Flask 사용 → "웹 프레임워크" 카테고리로 커버 가능
        coverage_keywords = {
            "opencv": ["컴퓨터 비전", "이미지 처리", "비디오 처리", "멀티미디어"],
            "cv2": ["컴퓨터 비전", "이미지 처리", "비디오 처리", "멀티미디어"],
            "cv2.imread": ["컴퓨터 비전", "이미지 처리"],
            "cv2.imshow": ["컴퓨터 비전", "gui", "사용자 인터페이스"],
            "cv2.rectangle": ["컴퓨터 비전", "이미지 처리"],
            "flask": ["웹 프레임워크", "flask"],
            "django": ["웹 프레임워크", "django"],
            "fastapi": ["웹 프레임워크", "fastapi"],
            "pandas": ["데이터 분석", "pandas"],
            "numpy": ["데이터 분석", "numpy", "과학 계산"],
            "matplotlib": ["데이터 분석", "시각화"],
            "asyncio": ["비동기 프로그래밍", "asyncio"],
            "aiohttp": ["비동기 프로그래밍", "네트워킹"],
            "zipfile": ["파일 및 예외 처리", "파일 처리"],
            "wave": ["멀티미디어", "오디오"],
            "pyaudio": ["멀티미디어", "오디오"],
            "speech_recognition": ["멀티미디어", "오디오", "stt"],
        }
        
        for keyword, categories in coverage_keywords.items():
            if keyword in code_snippet_lower:
                # 스킬 이름이나 카테고리가 이미 커버 가능한 카테고리인 경우
                if any(cat in skill.suggested_category for cat in categories):
                    # 특정 프레임워크/라이브러리 이름이 없는 경우 필터링
                    if not any(specific in skill_name_lower for specific in [
                        "yolov8", "yolo", "ultralytics", "detectron", 
                        "tensorflow", "pytorch", "keras", "scikit-learn",
                        "fastapi", "django", "flask", "aiohttp"
                    ]):
                        logger.debug(
                            f"필터링: 기존 스킬로 커버 가능 - {skill.suggested_skill_name} "
                            f"(카테고리: {skill.suggested_category}, 키워드: {keyword})"
                        )
                        return True
        
        # 5. 코드에 실제로 없는 기능 제안 제외
        # 예: "이미지 증강" 제안했는데 코드에 증강 기법이 없음
        augmentation_keywords = ["augment", "증강", "augmentation", "transform"]
        if any(keyword in skill_name_lower for keyword in augmentation_keywords):
            if not any(keyword in code_snippet_lower for keyword in [
                "augment", "transforms", "rotation", "flip", "crop", 
                "brightness", "contrast", "noise"
            ]):
                logger.debug(f"필터링: 코드에 없는 기능 - {skill.suggested_skill_name}")
                return True
        
        # 6. 단순 함수/클래스 정의만 있는 경우 제외
        if skill.suggested_level == "Basic":
            # 코드가 단순 함수/클래스 정의만 있는 경우
            code_lines = skill.code_snippet.strip().split('\n')
            non_comment_lines = [
                line for line in code_lines 
                if line.strip() and not line.strip().startswith('#') and not line.strip().startswith('"""')
            ]
            if len(non_comment_lines) <= 3:  # 매우 짧은 코드
                if any(keyword in code_snippet_lower for keyword in ["def ", "class "]):
                    logger.debug(f"필터링: 단순 정의만 있음 - {skill.suggested_skill_name}")
                    return True
        
        return False

    def _save_csv(self, missing_skills: List[MissingSkillInfo], csv_path: Path):
        """CSV 형식으로 저장 (skill_charts.csv 호환)"""
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)

            # 헤더 (skill_charts.csv와 동일 + 추가 필드)
            writer.writerow([
                "category",
                "subcategory",
                "skill_name",
                "level",
                "base_score",
                "weighted_score",
                "description",
                "evidence_examples",
                "developer_type",
                "source_file",
                "source_line",
                "code_snippet_preview",
            ])

            # 데이터
            for skill in missing_skills:
                writer.writerow([
                    skill.suggested_category,
                    skill.suggested_subcategory,
                    skill.suggested_skill_name,
                    skill.suggested_level,
                    0,  # base_score (수동 할당 필요)
                    0,  # weighted_score (수동 할당 필요)
                    skill.description,
                    skill.evidence_examples,
                    skill.developer_type,
                    skill.file_path,
                    skill.line_number,
                    skill.code_snippet[:100] + "..." if len(skill.code_snippet) > 100 else skill.code_snippet,
                ])

    def _save_json(self, missing_skills: List[MissingSkillInfo], json_path: Path):
        """JSON 형식으로 저장 (전체 정보 보존)"""
        data = [skill.model_dump() for skill in missing_skills]

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2,
            )

    def load_missing_skills(self, csv_path: str) -> List[MissingSkillInfo]:
        """
        CSV 파일에서 미등록 스킬 로드 (재처리용)

        Args:
            csv_path: CSV 파일 경로

        Returns:
            MissingSkillInfo 리스트
        """
        missing_skills = []

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                skill = MissingSkillInfo(
                    code_snippet=row.get("code_snippet_preview", ""),
                    file_path=row["source_file"],
                    line_number=int(row["source_line"]),
                    suggested_skill_name=row["skill_name"],
                    suggested_level=row["level"],
                    suggested_category=row["category"],
                    suggested_subcategory=row["subcategory"],
                    description=row["description"],
                    evidence_examples=row["evidence_examples"],
                    developer_type=row["developer_type"],
                )
                missing_skills.append(skill)

        logger.info(f"📂 {len(missing_skills)}개 미등록 스킬 로드: {csv_path}")
        return missing_skills
