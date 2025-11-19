"""SkillChartsRAGBuilder Agent - Skill Charts RAG 구축"""

import logging
import csv
from pathlib import Path
from typing import Any
import chromadb
from sentence_transformers import SentenceTransformer
from shared.tools.skill_tools import get_skill_chroma_client

from .schemas import SkillChartsRAGBuilderContext, SkillChartsRAGBuilderResponse

logger = logging.getLogger(__name__)


class SkillChartsRAGBuilderAgent:
    """
    Skill Charts를 ChromaDB에 RAG로 구축하는 에이전트

    skill_charts.csv를 파싱하여 각 스킬을 벡터 임베딩으로 저장
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None

    async def run(
        self, context: SkillChartsRAGBuilderContext
    ) -> SkillChartsRAGBuilderResponse:
        """
        Skill Charts RAG 구축 실행

        Args:
            context: SkillChartsRAGBuilderContext

        Returns:
            SkillChartsRAGBuilderResponse
        """
        skill_charts_path = context.skill_charts_path
        persist_dir = context.persist_dir

        logger.info(f"🔨 SkillChartsRAGBuilder: {skill_charts_path} RAG 구축 시작")

        # 파일 경로 검증
        skill_charts_file = Path(skill_charts_path)
        if not skill_charts_file.exists():
            error_msg = f"Skill charts file not found: {skill_charts_path}"
            logger.error(f"❌ SkillChartsRAGBuilder: {error_msg}")
            return SkillChartsRAGBuilderResponse(
                status="failed",
                error=error_msg,
            )

        try:
            # SentenceTransformer 로드
            if self.model is None:
                self.model = SentenceTransformer(self.model_name)
                logger.info(f"📦 SentenceTransformer 로드 완료: {self.model_name}")

            # CSV 파싱
            skills_data = self._parse_skill_charts(skill_charts_path)

            # ChromaDB 클라이언트 (싱글톤 사용)
            client = get_skill_chroma_client(persist_dir)

            # 컬렉션 확인: 기존 컬렉션이 있으면 재사용, 없으면 생성
            collection_name = "skill_charts"
            
            # list_collections()가 실패할 수 있으므로 try-except로 처리
            # (원격 서버의 컬렉션 configuration에 _type 필드가 없을 수 있음)
            existing_collections = []
            try:
                existing_collections = [col.name for col in client.list_collections()]
            except Exception as e:
                logger.warning(f"⚠️ 컬렉션 목록 조회 실패 (직접 확인 시도): {e}")
                # list_collections() 실패 시 직접 get_collection()으로 확인
                try:
                    collection = client.get_collection(name=collection_name)
                    count = collection.count()
                    if count > 0:
                        logger.info(f"✅ 기존 '{collection_name}' 컬렉션 재사용 (기존 데이터 {count}개)")
                        return SkillChartsRAGBuilderResponse(
                            status="success",
                            total_skills=count,
                            categories=[],
                            collection_name=collection_name,
                            message="기존 컬렉션 재사용됨",
                        )
                except Exception:
                    # 컬렉션이 없으면 새로 생성
                    pass
            
            if collection_name in existing_collections:
                collection = client.get_collection(name=collection_name)
                # 컬렉션에 데이터가 있는지 확인
                count = collection.count()
                if count > 0:
                    logger.info(f"✅ 기존 '{collection_name}' 컬렉션 재사용 (기존 데이터 {count}개)")
                    return SkillChartsRAGBuilderResponse(
                        status="success",
                        total_skills=count,
                        categories=[],  # 기존 데이터 재사용 시 카테고리는 확인 불가
                        collection_name=collection_name,
                        message="기존 컬렉션 재사용됨",
                    )
                else:
                    logger.info(f"⚠️ 기존 '{collection_name}' 컬렉션은 있지만 비어있음, 재생성")
                    try:
                        client.delete_collection(name=collection_name)
                    except Exception as e:
                        logger.warning(f"⚠️ 컬렉션 삭제 실패 (무시): {e}")
                    collection = client.create_collection(
                        name=collection_name,
                        metadata={"description": "Skill charts collection"}
                    )
            else:
                logger.info(f"🆕 새 '{collection_name}' 컬렉션 생성")
                # 컬렉션이 이미 존재할 수 있으므로 try-except로 처리
                try:
                    collection = client.create_collection(
                        name=collection_name,
                        metadata={"description": "Skill charts collection"}
                    )
                except Exception as e:
                    # 이미 존재하는 경우 get_collection()으로 가져오기
                    if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                        logger.info(f"⚠️ 컬렉션이 이미 존재함, 기존 컬렉션 사용: {e}")
                        collection = client.get_collection(name=collection_name)
                        count = collection.count()
                        if count > 0:
                            logger.info(f"✅ 기존 '{collection_name}' 컬렉션 재사용 (기존 데이터 {count}개)")
                            return SkillChartsRAGBuilderResponse(
                                status="success",
                                total_skills=count,
                                categories=[],
                                collection_name=collection_name,
                                message="기존 컬렉션 재사용됨",
                            )
                    else:
                        raise

            # 임베딩 및 저장
            await self._embed_and_store(skills_data, collection)

            # 카테고리 통계
            categories = list(set([skill["category"] for skill in skills_data]))

            logger.info(
                f"✅ SkillChartsRAGBuilder: {len(skills_data)}개 스킬, "
                f"{len(categories)}개 카테고리 저장 완료"
            )

            return SkillChartsRAGBuilderResponse(
                status="success",
                total_skills=len(skills_data),
                categories=categories,
                collection_name=collection_name,
            )

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"❌ SkillChartsRAGBuilder: {e}")
            logger.error(f"   상세 에러:\n{error_trace}")
            return SkillChartsRAGBuilderResponse(
                status="failed",
                total_skills=0,
                categories=[],
                collection_name="",
                error=str(e),
            )

    def _parse_skill_charts(self, csv_path: str) -> list[dict[str, Any]]:
        """
        skill_charts.csv 파싱

        Returns:
            list of skill dictionaries
        """
        skills_data = []

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                # 각 스킬을 하나의 문서로 저장
                skill = {
                    "category": row["category"],
                    "subcategory": row["subcategory"],
                    "skill_name": row["skill_name"],
                    "level": row["level"],
                    "base_score": int(row["base_score"]),
                    "description": row["description"],
                    "evidence_examples": row["evidence_examples"],
                    "developer_type": row["developer_type"],
                }

                skills_data.append(skill)

        logger.info(f"📂 {len(skills_data)}개 스킬 파싱 완료")
        return skills_data

    async def _embed_and_store(
        self, skills_data: list[dict[str, Any]], collection: chromadb.Collection
    ):
        """
        스킬 데이터를 임베딩하여 ChromaDB에 저장
        """
        documents = []
        metadatas = []
        ids = []

        for idx, skill in enumerate(skills_data):
            # 임베딩할 텍스트: 스킬명 + 설명 + 증거 예시
            doc_text = (
                f"{skill['skill_name']} ({skill['level']})\n"
                f"Category: {skill['category']} > {skill['subcategory']}\n"
                f"Description: {skill['description']}\n"
                f"Evidence: {skill['evidence_examples']}"
            )

            documents.append(doc_text)

            # 메타데이터 (ChromaDB는 모든 값을 문자열로 변환 필요)
            metadatas.append(
                {
                    "category": str(skill["category"]),
                    "subcategory": str(skill["subcategory"]),
                    "skill_name": str(skill["skill_name"]),
                    "level": str(skill["level"]),
                    "base_score": str(skill["base_score"]),  # 숫자를 문자열로 변환
                    "developer_type": str(skill["developer_type"]),
                }
            )

            # 고유 ID
            desc_hash = abs(hash(skill["description"])) % 10000
            skill_id = (
                f"{skill['category']}_{skill['subcategory']}_"
                f"{skill['skill_name']}_{skill['level']}_{desc_hash}"
            ).replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "")

            ids.append(skill_id)

        # 배치 크기로 저장
        batch_size = 100
        for i in range(0, len(documents), batch_size):
            batch_docs = documents[i : i + batch_size]
            batch_metas = metadatas[i : i + batch_size]
            batch_ids = ids[i : i + batch_size]

            # 임베딩 생성
            embeddings = self.model.encode(batch_docs).tolist()

            # ChromaDB에 저장 (에러 처리 추가)
            try:
                collection.add(
                    documents=batch_docs,
                    metadatas=batch_metas,
                    embeddings=embeddings,
                    ids=batch_ids,
                )
                logger.info(f"📊 {i + len(batch_docs)}/{len(documents)} 스킬 저장 중...")
            except Exception as e:
                logger.error(f"❌ ChromaDB 저장 실패 (배치 {i//batch_size + 1}): {e}")
                logger.error(f"   첫 번째 메타데이터 샘플: {batch_metas[0] if batch_metas else 'None'}")
                raise

        logger.info(f"✅ {len(documents)}개 스킬 ChromaDB 저장 완료")
