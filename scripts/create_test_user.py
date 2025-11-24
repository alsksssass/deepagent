import os
import uuid
from datetime import datetime, timezone
import psycopg2
from dotenv import load_dotenv

# .env 로드
load_dotenv()

# DB 설정
DB_HOST = os.getenv("POSTGRES_HOST")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")

def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

def create_test_user():
    user_id = "00000000-0000-0000-0000-000000000001"
    username = "test_user_batch"
    email = "test_batch@example.com"
    
    print(f"🔌 Connecting to database {DB_HOST}...")
    
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # 사용자 존재 확인
        cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if cur.fetchone():
            print(f"ℹ️  User {user_id} already exists.")
            return

        print(f"🔨 Creating user {user_id}...")
        
        # INSERT
        insert_query = """
        INSERT INTO users (
            id, github_id, username, nickname, repository_request_count, 
            email, avatar_url, access_token, created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, 
            %s, %s, %s, %s, %s
        )
        """
        
        now = datetime.now(timezone.utc)
        
        cur.execute(insert_query, (
            user_id,
            "test_github_id",
            username,
            "Test User Batch",
            0,
            email,
            "https://example.com/avatar.png",
            "dummy_token",
            now,
            now
        ))
        
        conn.commit()
        print(f"✅ User {user_id} created successfully!")
        
    except Exception as e:
        print(f"❌ Error creating user: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    create_test_user()
