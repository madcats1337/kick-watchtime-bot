-- Migration: Create processed_webhook_messages table for webhook idempotency
-- This table tracks which webhook messages have already been processed to prevent duplicates

CREATE TABLE IF NOT EXISTS processed_webhook_messages (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(255) NOT NULL,
    broadcaster_user_id VARCHAR(50) NOT NULL,
    event_type VARCHAR(100),
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Unique constraint on message_id (each message should only be processed once)
    CONSTRAINT unique_message_id UNIQUE (message_id)
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_processed_webhook_messages_lookup 
ON processed_webhook_messages(message_id, broadcaster_user_id);

-- Index for cleanup of old records
CREATE INDEX IF NOT EXISTS idx_processed_webhook_messages_processed_at 
ON processed_webhook_messages(processed_at);

-- Optional: Add a cleanup function to remove old records (older than 24 hours)
-- This can be run periodically to keep the table small
-- DELETE FROM processed_webhook_messages WHERE processed_at < NOW() - INTERVAL '24 hours';
