-- Migration 002: Add cross-cutting fields to message table
-- Adds urgency, language, attachment tracking, thread support, and FTS
-- Idempotent: checks for column existence before adding

-- Add cross-cutting fields to message if they don't exist
-- Note: SQLite doesn't support IF NOT EXISTS for ALTER TABLE ADD COLUMN,
-- so we rely on Python migration runner to check column existence

-- Indexes (safe to re-create)
CREATE INDEX IF NOT EXISTS idx_msg_urgency ON message(urgency);
CREATE INDEX IF NOT EXISTS idx_msg_thread  ON message(thread_id);

-- Full-Text Search (subject/body/entities) for fast UI queries
CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    subject, body_text, entities, content='message', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS message_ai AFTER INSERT ON message BEGIN
  INSERT INTO message_fts(rowid, subject, body_text, entities)
  VALUES (new.rowid, new.subject, new.body_text, COALESCE(new.entities,''));
END;

CREATE TRIGGER IF NOT EXISTS message_ad AFTER DELETE ON message BEGIN
  INSERT INTO message_fts(message_fts, rowid, subject, body_text, entities)
  VALUES('delete', old.rowid, old.subject, old.body_text, COALESCE(old.entities,''));
END;

CREATE TRIGGER IF NOT EXISTS message_au AFTER UPDATE ON message BEGIN
  INSERT INTO message_fts(message_fts, rowid, subject, body_text, entities)
  VALUES('delete', old.rowid, old.subject, old.body_text, COALESCE(old.entities,''));
  INSERT INTO message_fts(rowid, subject, body_text, entities)
  VALUES (new.rowid, new.subject, new.body_text, COALESCE(new.entities,''));
END;
