-- Migration 003: Add mailbox awareness (shared vs personal inboxes)
-- Adds mailbox_id/mailbox_type to raw_message and creates mailbox_emails mapping table
-- Idempotent: uses IF NOT EXISTS and UNIQUE constraints

-- Indexes (safe to re-create)
CREATE INDEX IF NOT EXISTS idx_raw_mailbox ON raw_message(mailbox_id, received_dt);

-- Mailbox-specific mapping (enforces canonical email → mailbox relationship)
CREATE TABLE IF NOT EXISTS mailbox_emails (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  mailbox_id    TEXT NOT NULL,
  mailbox_type  TEXT CHECK (mailbox_type IN ('personal','shared')) NOT NULL,
  canonical_key TEXT NOT NULL,           -- prefer internet_id, fallback to raw_message.id
  raw_id        TEXT NOT NULL,           -- Graph message id (raw_message.id)
  seen          INTEGER DEFAULT 0,
  processed     INTEGER DEFAULT 0,
  created_ts    TEXT DEFAULT (datetime('now')),
  UNIQUE(mailbox_id, canonical_key)      -- Idempotency: one canonical email per mailbox
);
CREATE INDEX IF NOT EXISTS idx_mb_processed ON mailbox_emails(processed, created_ts);
