-- Test User Creation SQL
-- Run this in your PostgreSQL database (sesami)

-- 1. Create Table if not exists
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    github_id VARCHAR UNIQUE,
    username VARCHAR UNIQUE,
    nickname VARCHAR UNIQUE,
    repository_request_count INTEGER DEFAULT 0,
    email VARCHAR UNIQUE,
    avatar_url VARCHAR,
    access_token VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Create Indexes (to match SQLAlchemy model)
CREATE INDEX IF NOT EXISTS ix_users_id ON users (id);
CREATE INDEX IF NOT EXISTS ix_users_github_id ON users (github_id);
CREATE INDEX IF NOT EXISTS ix_users_username ON users (username);
CREATE INDEX IF NOT EXISTS ix_users_nickname ON users (nickname);
CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);

-- 3. Insert Test User
INSERT INTO users (
    id, 
    github_id, 
    username, 
    nickname, 
    repository_request_count, 
    email, 
    avatar_url, 
    access_token, 
    created_at, 
    updated_at
) VALUES (
    '00000000-0000-0000-0000-000000000001', 
    'test_github_id', 
    'test_user_batch', 
    'Test User Batch', 
    0, 
    'test_batch@example.com', 
    'https://example.com/avatar.png', 
    'dummy_token', 
    NOW(), 
    NOW()
) ON CONFLICT (id) DO NOTHING;
