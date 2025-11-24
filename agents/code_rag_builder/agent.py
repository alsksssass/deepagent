"""CodeRAGBuilder Agent - 코드 RAG 구축"""

import logging
import asyncio
from pathlib import Path
from typing import Any
import hashlib

import chromadb
from sentence_transformers import SentenceTransformer
from shared.tools.chromadb_tools import get_code_chroma_client

from .schemas import CodeRAGBuilderContext, CodeRAGBuilderResponse
from shared.utils.tree_sitter_utils import (
    extract_functions_and_classes,
    get_language_from_extension,
    is_language_supported,
)

logger = logging.getLogger(__name__)


class CodeRAGBuilderAgent:
    """
    코드를 파싱하고 ChromaDB에 임베딩을 저장하는 에이전트

    Level 2 병렬 처리:
    - 파일 읽기 및 파싱
    - 임베딩 생성 및 저장
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self.client = None

    async def run(self, context: CodeRAGBuilderContext) -> CodeRAGBuilderResponse:
        """
        코드 RAG 구축 실행

        Args:
            context: CodeRAGBuilderContext

        Returns:
            CodeRAGBuilderResponse
        """
        repo_path = Path(context.repo_path)
        task_uuid = context.task_uuid
        collection_name = f"code_{task_uuid}"

        logger.info(f"🔨 CodeRAGBuilder: {repo_path} RAG 구축 시작")

        try:
            # 임베딩 모델 로드 (동기)
            # device="cpu"를 명시하여 meta tensor 오류 방지
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(
                None, lambda: SentenceTransformer(self.model_name, device="cpu")
            )

            # ChromaDB 클라이언트 (task_uuid별 로컬 저장소)
            self.client = get_code_chroma_client(task_uuid)

            # 컬렉션 생성 (기존 것 삭제)
            try:
                self.client.delete_collection(name=collection_name)
            except Exception:
                pass

            collection = self.client.create_collection(name=collection_name)

            # Level 2-1: 코드 파일 수집
            code_files = await self._collect_code_files(repo_path)

            logger.info(f"📂 {len(code_files)}개 코드 파일 발견")

            # Level 2-2: 파일별 파싱 및 청크 생성 (배치 병렬)
            all_chunks = []
            batch_size = 10

            for i in range(0, len(code_files), batch_size):
                batch = code_files[i : i + batch_size]

                # 배치 병렬 처리
                batch_chunks_list = await asyncio.gather(
                    *[self._parse_file(file_path) for file_path in batch]
                )

                for chunks in batch_chunks_list:
                    all_chunks.extend(chunks)

                logger.info(f"📊 {i + len(batch)}/{len(code_files)} 파일 파싱 완료")

            # Level 2-3: 임베딩 생성 및 저장
            total_chunks = await self._store_embeddings(collection, all_chunks)

            logger.info(f"✅ CodeRAGBuilder: {total_chunks}개 청크 저장 완료")

            return CodeRAGBuilderResponse(
                status="success",
                total_files=len(code_files),
                total_chunks=total_chunks,
                collection_name=collection_name,
            )

        except Exception as e:
            logger.error(f"❌ CodeRAGBuilder: {e}")
            return CodeRAGBuilderResponse(
                status="failed",
                total_files=0,
                total_chunks=0,
                collection_name="",
                error=str(e),
            )

    async def _collect_code_files(self, repo_path: Path) -> list[Path]:
        """
        코드 파일 수집 (.py, .js, .ts, .tsx, .jsx, .java, .go, .rs 등)
        """
        code_extensions = {
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".java",
            ".go",
            ".rs",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
            ".cs",
            ".rb",
            ".php",
            ".swift",
            ".kt",
        }

        def _collect():
            files = []
            for ext in code_extensions:
                files.extend(repo_path.rglob(f"*{ext}"))
            return files

        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(None, _collect)

        # 테스트, 빌드, node_modules 등 제외
        exclude_patterns = [
            "test",
            "tests",
            "__pycache__",
            "node_modules",
            "venv",
            ".venv",
            "build",
            "dist",
            ".git",
        ]

        filtered_files = [
            f
            for f in files
            if not any(pattern in str(f) for pattern in exclude_patterns)
        ]

        return filtered_files

    async def _parse_file(self, file_path: Path) -> list[dict[str, Any]]:
        """
        파일을 파싱하여 청크로 분할

        통합 파서 전략:
        1. Tree-sitter 지원 언어: Tree-sitter 기반 함수/클래스 단위 분할 (Python 포함)
        2. 기타: 빈 줄 2개 이상 기준 분할 (폴백)
        3. 최대 청크 크기 제한 (200줄)

        Returns:
            list of {"file": str, "chunk_id": str, "code": str, "type": str, "line_start": int, "line_end": int}
        """

        def _parse():
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"⚠️  {file_path} 읽기 실패: {e}")
                return []

            lines = content.split("\n")
            chunks = []
            parser_type = self._select_parser(file_path)
            
            # Tree-sitter: 구조적 파싱 (실제 AST 기반)
            if parser_type == "tree-sitter":
                language = get_language_from_extension(file_path.suffix)
                if language:
                    tree_sitter_chunks = extract_functions_and_classes(
                        content, language, max_chunk_lines=200
                    )
                    if tree_sitter_chunks:
                        chunks.extend(tree_sitter_chunks)
                        logger.debug(f"✅ {file_path.name}: Tree-sitter 기반 {len(tree_sitter_chunks)}개 청크 생성 ({language})")
                    else:
                        # Tree-sitter 파싱 실패 시 폴백
                        logger.warning(f"⚠️  {file_path.name} Tree-sitter 파싱 실패, 빈 줄 기준으로 폴백")
                        parser_type = "blank-line"
                else:
                    parser_type = "blank-line"
            
            # 빈 줄 기준 분할 (폴백)
            if parser_type == "blank-line" or not chunks:
                blank_line_chunks = self._extract_blank_line_chunks(content, lines)
                if blank_line_chunks:
                    # 기존 청크와 중복되지 않는 빈 줄 청크만 추가
                    if chunks:
                        existing_ranges = {(c["line_start"], c["line_end"]) for c in chunks}
                        for blank_chunk in blank_line_chunks:
                            # 기존 청크와 겹치지 않는지 확인
                            overlaps = False
                            for start, end in existing_ranges:
                                if not (blank_chunk["line_end"] < start or blank_chunk["line_start"] > end):
                                    overlaps = True
                                    break
                            if not overlaps:
                                chunks.append(blank_chunk)
                    else:
                        chunks.extend(blank_line_chunks)
            
            # 최대 청크 크기 제한 (200줄 초과 시 분할)
            final_chunks = []
            for chunk in chunks:
                chunk_lines = chunk["line_end"] - chunk["line_start"] + 1
                if chunk_lines > 200:
                    # 큰 청크를 여러 개로 분할
                    split_chunks = self._split_large_chunk(chunk, lines, max_size=200)
                    final_chunks.extend(split_chunks)
                else:
                    final_chunks.append(chunk)
            
            # 청크 ID 생성 (고유성 보장: file_path + line_start + line_end + type + code)
            seen_ids = set()
            unique_chunks = []
            for chunk in final_chunks:
                chunk_code = chunk["code"]
                line_start = chunk.get("line_start", 0)
                line_end = chunk.get("line_end", 0)
                chunk_type = chunk.get("type", "unknown")
                
                # 고유한 chunk_id 생성 (위치 정보 포함)
                chunk_id = hashlib.md5(
                    (
                        str(file_path) + 
                        str(line_start) + 
                        str(line_end) + 
                        chunk_type + 
                        chunk_code
                    ).encode()
                ).hexdigest()
                
                # 중복 체크: 같은 ID가 이미 있으면 스킵
                if chunk_id not in seen_ids:
                    seen_ids.add(chunk_id)
                    chunk["chunk_id"] = chunk_id
                    chunk["file"] = str(file_path)
                    unique_chunks.append(chunk)
                else:
                    logger.debug(
                        f"⚠️ 중복 청크 스킵: {file_path.name}:{line_start}-{line_end} "
                        f"(type={chunk_type})"
                    )
            
            return unique_chunks

        loop = asyncio.get_event_loop()
        chunks = await loop.run_in_executor(None, _parse)

        return chunks
    
    def _select_parser(self, file_path: Path) -> str:
        """
        파일 확장자에 따라 최적 파서 선택

        우선순위:
        1. Tree-sitter 지원 언어: Tree-sitter (실제 AST 기반)
        2. 기타: 빈 줄 기준 (폴백)

        Returns:
            "tree-sitter" 또는 "blank-line"
        """
        # Tree-sitter 지원 언어 확인
        if is_language_supported(file_path.suffix):
            return "tree-sitter"

        # 기타는 빈 줄 기준
        return "blank-line"
    
    def _extract_blank_line_chunks(
        self, content: str, lines: list[str]
    ) -> list[dict[str, Any]]:
        """
        빈 줄 2개 이상 기준으로 청크 추출 (기존 로직)
        """
        chunks = []
        current_chunk = []
        blank_count = 0
        chunk_start_line = 1
        
        for line_idx, line in enumerate(lines, start=1):
            if line.strip() == "":
                blank_count += 1
            else:
                if blank_count >= 2 and current_chunk:
                    chunk_code = "\n".join(current_chunk)
                    chunk_end_line = line_idx - blank_count - 1
                    
                    chunks.append({
                        "code": chunk_code,
                        "type": "code_block",
                        "line_start": chunk_start_line,
                        "line_end": chunk_end_line,
                    })
                    
                    current_chunk = []
                    chunk_start_line = line_idx
                
                current_chunk.append(line)
                blank_count = 0
        
        # 마지막 청크
        if current_chunk:
            chunk_code = "\n".join(current_chunk)
            chunks.append({
                "code": chunk_code,
                "type": "code_block",
                "line_start": chunk_start_line,
                "line_end": len(lines),
            })
        
        return chunks
    
    def _split_large_chunk(
        self, chunk: dict[str, Any], lines: list[str], max_size: int = 200
    ) -> list[dict[str, Any]]:
        """
        큰 청크를 최대 크기로 분할
        """
        chunk_start = chunk["line_start"]
        chunk_end = chunk["line_end"]
        chunk_lines = chunk_end - chunk_start + 1
        
        if chunk_lines <= max_size:
            return [chunk]
        
        split_chunks = []
        current_start = chunk_start
        
        while current_start <= chunk_end:
            current_end = min(current_start + max_size - 1, chunk_end)
            chunk_code = "\n".join(lines[current_start - 1 : current_end])
            
            split_chunks.append({
                "code": chunk_code,
                "type": chunk.get("type", "code_block"),
                "line_start": current_start,
                "line_end": current_end,
                "name": chunk.get("name", ""),
            })
            
            current_start = current_end + 1
        
        return split_chunks

    async def _store_embeddings(
        self, collection, chunks: list[dict[str, Any]]
    ) -> int:
        """
        청크에 대한 임베딩을 생성하고 ChromaDB에 저장

        Args:
            collection: ChromaDB collection
            chunks: 코드 청크 리스트

        Returns:
            저장된 청크 수
        """
        if not chunks:
            return 0

        # 임베딩 생성 (동기)
        def _embed():
            texts = [chunk["code"] for chunk in chunks]
            embeddings = self.model.encode(texts, show_progress_bar=True)
            return embeddings.tolist()

        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(None, _embed)

        # ChromaDB에 배치 저장 (중복 ID 체크)
        batch_size = 1000
        saved_count = 0

        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i : i + batch_size]
            batch_embeddings = embeddings[i : i + batch_size]
            
            # 중복 ID 필터링 (ChromaDB 저장 전 최종 체크)
            unique_batch = []
            unique_embeddings = []
            seen_batch_ids = set()
            
            for idx, chunk in enumerate(batch_chunks):
                chunk_id = chunk["chunk_id"]
                if chunk_id not in seen_batch_ids:
                    seen_batch_ids.add(chunk_id)
                    unique_batch.append(chunk)
                    unique_embeddings.append(batch_embeddings[idx])
            
            if not unique_batch:
                continue

            try:
                collection.add(
                    ids=[chunk["chunk_id"] for chunk in unique_batch],
                    embeddings=unique_embeddings,
                    documents=[chunk["code"] for chunk in unique_batch],
                    metadatas=[
                        {
                            "file": chunk["file"],
                            "type": chunk["type"],
                            "line_start": chunk.get("line_start", 0),
                            "line_end": chunk.get("line_end", 0),
                        }
                        for chunk in unique_batch
                    ],
                )
                saved_count += len(unique_batch)
                logger.info(f"📊 {saved_count}/{len(chunks)} 청크 저장 중...")
            except Exception as e:
                # 중복 ID 오류 발생 시 개별 저장으로 재시도
                logger.warning(f"⚠️ 배치 저장 실패, 개별 저장 시도: {str(e)}")
                for chunk, embedding in zip(unique_batch, unique_embeddings):
                    try:
                        collection.add(
                            ids=[chunk["chunk_id"]],
                            embeddings=[embedding],
                            documents=[chunk["code"]],
                            metadatas=[{
                                "file": chunk["file"],
                                "type": chunk["type"],
                                "line_start": chunk.get("line_start", 0),
                                "line_end": chunk.get("line_end", 0),
                            }],
                        )
                        saved_count += 1
                    except Exception as e2:
                        logger.warning(
                            f"⚠️ 청크 저장 실패 (ID: {chunk['chunk_id'][:8]}...): {str(e2)}"
                        )

        return saved_count
