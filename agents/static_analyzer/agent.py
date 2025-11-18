"""
StaticAnalyzer Agent

코드 품질 정적 분석 수행 (Pydantic 스키마 사용)
"""

import logging
import asyncio
import json
from pathlib import Path
from .schemas import (
    StaticAnalyzerContext,
    StaticAnalyzerResponse,
    ComplexityResult,
    TypeCheckResult,
    LocStatsResult,
)

logger = logging.getLogger(__name__)


class StaticAnalyzerAgent:
    """
    정적 분석을 수행하는 서브에이전트

    Level 2 병렬 처리:
    - Radon (복잡도)
    - Pyright (타입 체크)
    - Cloc (라인 수)
    """

    async def run(self, context: StaticAnalyzerContext) -> StaticAnalyzerResponse:
        """
        정적 분석 실행 (Pydantic 스키마 사용)

        Args:
            context: StaticAnalyzerContext (검증된 입력)

        Returns:
            StaticAnalyzerResponse (타입 안전 출력)
        """
        repo_path = Path(context.repo_path)

        logger.info(f"📊 StaticAnalyzer: {repo_path} 분석 시작")

        try:
            # Level 2: 병렬 정적 분석
            complexity, type_check, loc_stats = await asyncio.gather(
                self._run_radon(repo_path),
                self._run_pyright(repo_path),
                self._run_cloc(repo_path),
            )

            logger.info(f"✅ StaticAnalyzer: 분석 완료")

            return StaticAnalyzerResponse(
                status="success",
                complexity=complexity,
                type_check=type_check,
                loc_stats=loc_stats,
                error=None,
            )

        except Exception as e:
            logger.error(f"❌ StaticAnalyzer: {e}")
            return StaticAnalyzerResponse(
                status="failed",
                complexity=ComplexityResult(),
                type_check=TypeCheckResult(),
                loc_stats=LocStatsResult(),
                error=str(e),
            )

    async def _run_radon(self, repo_path: Path) -> ComplexityResult:
        """
        Radon 복잡도 분석

        Returns:
            ComplexityResult (Pydantic 모델)
        """
        try:
            # Radon CC (Cyclomatic Complexity)
            cmd = f"radon cc {repo_path} -a -j"
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.warning(f"⚠️  Radon 실행 실패: {stderr.decode()}")
                return ComplexityResult(error=stderr.decode())

            # JSON 파싱
            result = json.loads(stdout.decode())

            # 복잡도 집계
            all_complexity = []
            high_complexity_files = []

            for file_path, functions in result.items():
                for func in functions:
                    complexity = func.get("complexity", 0)
                    all_complexity.append(complexity)

                    # 복잡도 10 이상은 높음
                    if complexity >= 10:
                        high_complexity_files.append({
                            "file": file_path,
                            "function": func.get("name"),
                            "complexity": complexity,
                            "rank": func.get("rank"),
                        })

            avg_complexity = (
                sum(all_complexity) / len(all_complexity)
                if all_complexity
                else 0.0
            )

            return ComplexityResult(
                average_complexity=round(avg_complexity, 2),
                total_functions=len(all_complexity),
                high_complexity_files=high_complexity_files[:10],  # 상위 10개
                summary={
                    "A": sum(1 for c in all_complexity if c <= 5),
                    "B": sum(1 for c in all_complexity if 6 <= c <= 10),
                    "C": sum(1 for c in all_complexity if 11 <= c <= 20),
                    "D": sum(1 for c in all_complexity if 21 <= c <= 50),
                    "F": sum(1 for c in all_complexity if c > 50),
                },
            )

        except Exception as e:
            logger.warning(f"⚠️  Radon 분석 실패: {e}")
            return ComplexityResult(error=str(e))

    async def _run_pyright(self, repo_path: Path) -> TypeCheckResult:
        """
        Pyright 타입 체크

        Returns:
            TypeCheckResult (Pydantic 모델)
        """
        try:
            # Pyright JSON 출력
            cmd = f"pyright {repo_path} --outputjson"
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            # Pyright는 에러가 있어도 JSON 출력
            result = json.loads(stdout.decode())

            return TypeCheckResult(
                total_errors=result.get("summary", {}).get("errorCount", 0),
                total_warnings=result.get("summary", {}).get("warningCount", 0),
                total_info=result.get("summary", {}).get("informationCount", 0),
                files_analyzed=result.get("summary", {}).get("filesAnalyzed", 0),
                time_ms=result.get("summary", {}).get("timeInSec", 0) * 1000,
            )

        except Exception as e:
            logger.warning(f"⚠️  Pyright 분석 실패: {e}")
            return TypeCheckResult(error=str(e))

    async def _run_cloc(self, repo_path: Path) -> LocStatsResult:
        """
        Cloc 라인 수 분석

        Returns:
            LocStatsResult (Pydantic 모델)
        """
        try:
            # Cloc JSON 출력
            cmd = f"cloc {repo_path} --json --quiet"
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.warning(f"⚠️  Cloc 실행 실패: {stderr.decode()}")
                return LocStatsResult(error=stderr.decode())

            result = json.loads(stdout.decode())

            # 언어별 통계 추출
            by_language = {}
            total_code = 0
            total_comment = 0
            total_blank = 0

            for lang, stats in result.items():
                if lang in ["header", "SUM"]:
                    continue

                by_language[lang] = {
                    "files": stats.get("nFiles", 0),
                    "code": stats.get("code", 0),
                    "comment": stats.get("comment", 0),
                    "blank": stats.get("blank", 0),
                }

                total_code += stats.get("code", 0)
                total_comment += stats.get("comment", 0)
                total_blank += stats.get("blank", 0)

            return LocStatsResult(
                total_lines=total_code + total_comment + total_blank,
                code_lines=total_code,
                comment_lines=total_comment,
                blank_lines=total_blank,
                by_language=by_language,
            )

        except Exception as e:
            logger.warning(f"⚠️  Cloc 분석 실패: {e}")
            return LocStatsResult(error=str(e))
