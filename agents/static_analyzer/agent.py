"""
StaticAnalyzer Agent

코드 품질 정적 분석 수행 (Pydantic 스키마 사용)
"""

import logging
import asyncio
import json
import shutil
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
        Radon 복잡도 분석 (개선된 에러 처리)

        Returns:
            ComplexityResult (Pydantic 모델)
        """
        # 1. Radon 설치 확인
        radon_path = shutil.which("radon")
        if not radon_path:
            error_msg = "Radon이 설치되어 있지 않거나 PATH에 없습니다. 'pip install radon'으로 설치하세요."
            logger.error(f"❌ {error_msg}")
            return ComplexityResult(error=error_msg)
        
        logger.debug(f"🔍 Radon 경로: {radon_path}")

        # 2. Python 파일 존재 확인
        python_files = list(repo_path.rglob("*.py"))
        if not python_files:
            logger.warning(f"⚠️  Python 파일이 없습니다: {repo_path}")
            return ComplexityResult(
                error=f"Python 파일 없음: {repo_path}",
                summary={"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
            )
        
        logger.debug(f"📁 Python 파일 수: {len(python_files)}개")

        # 3. 재시도 로직 (최대 2회)
        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(f"🔄 Radon 재시도 {attempt}/{max_retries}")
                    await asyncio.sleep(1)  # 재시도 전 대기

                # Radon CC (Cyclomatic Complexity)
                cmd = f"radon cc {repo_path} -a -j"
                logger.debug(f"🔧 Radon 명령 실행: {cmd}")
                
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                
                # 타임아웃 설정 (60초)
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=60.0
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    error_msg = "Radon 실행 타임아웃 (60초 초과)"
                    logger.error(f"❌ {error_msg}")
                    last_error = error_msg
                    continue

                # 인코딩 처리
                try:
                    stdout_text = stdout.decode('utf-8')
                    stderr_text = stderr.decode('utf-8')
                except UnicodeDecodeError:
                    stdout_text = stdout.decode('utf-8', errors='replace')
                    stderr_text = stderr.decode('utf-8', errors='replace')
                    logger.warning("⚠️  Radon 출력 인코딩 문제 (UTF-8 대체 사용)")

                if process.returncode != 0:
                    error_msg = f"Radon 실행 실패 (exit code: {process.returncode}): {stderr_text}"
                    logger.warning(f"⚠️  {error_msg}")
                    last_error = error_msg
                    
                    # 특정 에러에 대한 처리
                    if "No such file or directory" in stderr_text:
                        error_msg = f"레포지토리 경로를 찾을 수 없습니다: {repo_path}"
                        logger.error(f"❌ {error_msg}")
                        return ComplexityResult(error=error_msg)
                    elif attempt < max_retries:
                        continue  # 재시도
                    else:
                        return ComplexityResult(error=error_msg)

                # 빈 출력 확인
                if not stdout_text.strip():
                    logger.warning("⚠️  Radon 출력이 비어있습니다")
                    return ComplexityResult(
                        error="Radon 출력 없음",
                        summary={"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
                    )

                # JSON 파싱
                try:
                    result = json.loads(stdout_text)
                except json.JSONDecodeError as json_err:
                    error_msg = f"Radon JSON 파싱 실패: {json_err}\n출력: {stdout_text[:200]}"
                    logger.error(f"❌ {error_msg}")
                    last_error = error_msg
                    if attempt < max_retries:
                        continue  # 재시도
                    else:
                        return ComplexityResult(error=error_msg)

                # 빈 결과 확인
                if not result or not isinstance(result, dict):
                    logger.warning("⚠️  Radon 결과가 비어있거나 잘못된 형식입니다")
                    return ComplexityResult(
                        error="Radon 결과 없음",
                        summary={"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
                    )

                # 복잡도 집계
                all_complexity = []
                high_complexity_files = []

                try:
                    for file_path, functions in result.items():
                        try:
                            # file_path가 문자열인지 확인
                            if not isinstance(file_path, str):
                                logger.debug(f"⚠️  Radon: 파일 경로가 문자열이 아님: {type(file_path)}, 값: {file_path}")
                                continue
                            
                            # functions가 리스트인지 확인
                            if not isinstance(functions, list):
                                logger.debug(f"⚠️  Radon: {file_path}의 functions가 리스트가 아님: {type(functions)}, 값: {functions}")
                                continue
                            
                            # 빈 리스트 건너뛰기
                            if not functions:
                                continue
                            
                            for func in functions:
                                try:
                                    # func가 딕셔너리인지 확인
                                    if not isinstance(func, dict):
                                        logger.debug(f"⚠️  Radon: {file_path}의 함수 항목이 딕셔너리가 아님: {type(func)}, 값: {func}")
                                        continue
                                    
                                    # complexity 값 추출 (안전하게)
                                    complexity = func.get("complexity", 0)
                                    
                                    # complexity가 숫자인지 확인
                                    if not isinstance(complexity, (int, float)) or complexity <= 0:
                                        continue
                                    
                                    all_complexity.append(complexity)

                                    # 복잡도 10 이상은 높음
                                    if complexity >= 10:
                                        high_complexity_files.append({
                                            "file": str(file_path),
                                            "function": func.get("name", "unknown"),
                                            "complexity": complexity,
                                            "rank": func.get("rank", "unknown"),
                                        })
                                except (AttributeError, TypeError, KeyError) as func_err:
                                    logger.debug(f"⚠️  Radon: 함수 항목 처리 중 오류 ({file_path}): {func_err}, func 타입: {type(func)}")
                                    continue
                        except Exception as file_err:
                            logger.warning(f"⚠️  Radon: 파일 {file_path} 처리 중 오류: {file_err}")
                            continue
                except Exception as parse_err:
                    error_msg = f"Radon 결과 파싱 중 오류: {parse_err}, result 타입: {type(result)}"
                    logger.error(f"❌ {error_msg}")
                    logger.debug(f"   result 내용 (처음 500자): {str(result)[:500]}")
                    return ComplexityResult(error=error_msg)

                if not all_complexity:
                    logger.info("ℹ️  Radon: 분석된 함수가 없습니다 (복잡도 데이터 없음)")
                    return ComplexityResult(
                        average_complexity=0.0,
                        total_functions=0,
                        high_complexity_files=[],
                        summary={"A": 0, "B": 0, "C": 0, "D": 0, "F": 0},
                    )

                avg_complexity = sum(all_complexity) / len(all_complexity)

                logger.info(f"✅ Radon 분석 완료: {len(all_complexity)}개 함수, 평균 복잡도 {avg_complexity:.2f}")

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

            except asyncio.TimeoutError:
                error_msg = "Radon 실행 타임아웃"
                logger.error(f"❌ {error_msg}")
                last_error = error_msg
                if attempt < max_retries:
                    continue
            except Exception as e:
                error_msg = f"Radon 분석 중 예외 발생: {type(e).__name__}: {e}"
                logger.error(f"❌ {error_msg}", exc_info=True)
                last_error = error_msg
                if attempt < max_retries:
                    continue

        # 모든 재시도 실패
        final_error = last_error or "Radon 분석 실패 (알 수 없는 오류)"
        logger.error(f"❌ {final_error} (재시도 {max_retries}회 모두 실패)")
        return ComplexityResult(error=final_error)

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
