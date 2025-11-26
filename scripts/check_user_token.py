import os
import sys
import uuid
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# .env 로드
load_dotenv(project_root / ".env")

# ENCRYPTION_KEY 강제 설정 (테스트용)
if not os.getenv("ENCRYPTION_KEY"):
    os.environ["ENCRYPTION_KEY"] = "_DS83qC5xQJhzk24zPO_L7kbjusKtuI6k1hDF90mgUE="

from shared.graph_db.db_writer import AnalysisDBWriter

async def check_token(user_id: str):
    print(f"🔍 Checking token for user: {user_id}")
    
    try:
        await AnalysisDBWriter.initialize(echo=False)
        db_writer = AnalysisDBWriter.get_instance()
        
        user_uuid = uuid.UUID(user_id)
        token = await db_writer.get_user_access_token(user_uuid)
        
        if token:
            print(f"✅ Token found and decrypted: {token[:4]}...{token[-4:]}")
        else:
            print("❌ No token found or user does not exist.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await AnalysisDBWriter.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_user_token.py <user_id>")
        sys.exit(1)
    
    asyncio.run(check_token(sys.argv[1]))
