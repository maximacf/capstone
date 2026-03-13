-- Migration 001: Initial schema
-- Creates bronze (raw_message), silver (message), and supporting tables
-- Idempotent: uses IF NOT EXISTS throughout

PRAGMA journal_mode=WAL;

-- =======================
-- BRONZE: exact Graph payload (audit/replay)
-- =======================
CREATE TABLE IF NOT EXISTS raw_message (
  id            TEXT PRIMARY KEY,              -- Graph message id
  internet_id   TEXT UNIQUE,                   -- RFC 5322 internetMessageId
  received_dt   TEXT NOT NULL,                 -- ISO8601
  from_addr     TEXT,
  subject       TEXT,
  body_html     TEXT,                          -- Graph body.content (may be HTML)
  body_type     TEXT CHECK(body_type IN ('html','text')) DEFAULT 'html',
  json_path     TEXT,                          -- optional: sidecar JSON path
  created_ts    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_raw_received ON raw_message(received_dt);

-- =======================
-- SILVER: normalized & queryable
-- =======================
CREATE TABLE IF NOT EXISTS message (
  id TEXT PRIMARY KEY,                         -- Graph id (same as raw_message.id)
  internet_id TEXT UNIQUE,                     -- for dedupe/upsert
  received_dt TEXT,
  from_addr   TEXT,
  from_domain TEXT,
  subject     TEXT,
  body_text   TEXT,                            -- HTML→text normalized
  body_html   TEXT,                            -- optional copy of raw HTML
  category    TEXT,                            -- Trades/Clients/Research/Internal
  source_hash TEXT,                            -- fallback dedupe if internet_id missing
  manual_category TEXT,                        -- human override (nullable)
  updated_ts  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_message_received ON message(received_dt);
CREATE INDEX IF NOT EXISTS idx_message_category ON message(COALESCE(manual_category, category));

-- convenience view exposing "current" category
CREATE VIEW IF NOT EXISTS vw_message AS
SELECT m.*,
       COALESCE(m.manual_category, m.category) AS category_current
FROM message m;

-- =======================
-- ATTACHMENTS
-- =======================
CREATE TABLE IF NOT EXISTS attachment (
  id            TEXT PRIMARY KEY,              -- Graph attachment id
  message_id    TEXT NOT NULL,                 -- FK -> message.id
  name          TEXT,
  content_type  TEXT,
  size_bytes    INTEGER,
  path          TEXT,                          -- local saved file path
  created_ts    TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(message_id) REFERENCES message(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_att_msg  ON attachment(message_id);
CREATE INDEX IF NOT EXISTS idx_att_name ON attachment(name);

-- =======================
-- IDEAS (Gold): parsed trade fields (allow multiple ideas per message)
-- =======================
CREATE TABLE IF NOT EXISTS idea (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id   TEXT NOT NULL,                 -- FK -> message.id
  product      TEXT,                          -- Rates/FX/Credit
  ccy          TEXT,                          -- EUR/USD/...
  tenor        TEXT,                          -- 5y, 2s10s, etc.
  direction    TEXT,                          -- Long/Short/Pay/Receive
  entry_level  REAL,
  target_level REAL,
  stop_level   REAL,
  horizon      TEXT,                          -- 1w, 1m, ASAP, etc.
  status       TEXT,                          -- Live/Closed/OnWatch
  owner        TEXT,                          -- salesperson/desk
  confidence   TEXT,
  tags         TEXT,                          -- CSV for v1 (fast); can normalize later
  extracted_by TEXT DEFAULT 'rules_v1',
  extracted_ts TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(message_id) REFERENCES message(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_idea_message ON idea(message_id);
CREATE INDEX IF NOT EXISTS idx_idea_product ON idea(product);
CREATE INDEX IF NOT EXISTS idx_idea_ccy     ON idea(ccy);
CREATE INDEX IF NOT EXISTS idx_idea_tenor   ON idea(tenor);
CREATE INDEX IF NOT EXISTS idx_idea_status  ON idea(status);

-- =======================
-- Classification provenance (audit/improvement)
-- =======================
CREATE TABLE IF NOT EXISTS classification_event (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id    TEXT NOT NULL,
  category_auto TEXT NOT NULL,
  rule_name     TEXT,                         -- e.g., TRADE_WORDS_TENOR_V1
  confidence    REAL,                         -- 0..1
  created_ts    TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(message_id) REFERENCES message(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cls_msg  ON classification_event(message_id);
CREATE INDEX IF NOT EXISTS idx_cls_time ON classification_event(created_ts);
