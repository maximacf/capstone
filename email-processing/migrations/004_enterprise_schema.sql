-- Migration 004: Enterprise model (orgs, users, mailboxes, canonical emails, outputs)
-- Adds per-user configs, automation runs, artifacts, and flags
-- Idempotent: uses IF NOT EXISTS throughout

-- =======================
-- ORGS + USERS
-- =======================
CREATE TABLE IF NOT EXISTS organization (
  org_id   TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  created_ts TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user (
  user_id  TEXT PRIMARY KEY,
  org_id   TEXT NOT NULL,
  email    TEXT,
  name     TEXT,
  created_ts TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(org_id) REFERENCES organization(org_id)
);

-- =======================
-- MAILBOXES
-- =======================
CREATE TABLE IF NOT EXISTS mailbox (
  mailbox_id     TEXT PRIMARY KEY,
  org_id         TEXT NOT NULL,
  mailbox_type   TEXT CHECK (mailbox_type IN ('personal','shared_team')) NOT NULL,
  owner_user_id  TEXT, -- nullable for shared_team
  name           TEXT,
  created_ts     TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(org_id) REFERENCES organization(org_id),
  FOREIGN KEY(owner_user_id) REFERENCES user(user_id)
);
CREATE INDEX IF NOT EXISTS idx_mailbox_org ON mailbox(org_id);

-- =======================
-- CANONICAL EMAILS
-- =======================
CREATE TABLE IF NOT EXISTS email (
  email_id        TEXT PRIMARY KEY,
  org_id          TEXT NOT NULL,
  provider_msg_id TEXT,
  thread_id       TEXT,
  from_addr       TEXT,
  to_addrs        TEXT,
  cc_addrs        TEXT,
  subject         TEXT,
  received_at     TEXT,
  body_text       TEXT,
  body_html       TEXT,
  raw_mime_ptr    TEXT,
  content_hash    TEXT,
  created_ts      TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(org_id) REFERENCES organization(org_id)
);
CREATE INDEX IF NOT EXISTS idx_email_org ON email(org_id);
CREATE INDEX IF NOT EXISTS idx_email_thread ON email(thread_id);
CREATE INDEX IF NOT EXISTS idx_email_received ON email(received_at);

-- Mailbox ↔ Email mapping (shared inbox view)
CREATE TABLE IF NOT EXISTS mailbox_email (
  mailbox_email_id INTEGER PRIMARY KEY AUTOINCREMENT,
  mailbox_id       TEXT NOT NULL,
  email_id         TEXT NOT NULL,
  delivered_at     TEXT,
  labels_json      TEXT,
  read_state       TEXT,
  archived_state   TEXT,
  created_ts       TEXT DEFAULT (datetime('now')),
  UNIQUE(mailbox_id, email_id),
  FOREIGN KEY(mailbox_id) REFERENCES mailbox(mailbox_id),
  FOREIGN KEY(email_id) REFERENCES email(email_id)
);
CREATE INDEX IF NOT EXISTS idx_mb_email_mailbox ON mailbox_email(mailbox_id);
CREATE INDEX IF NOT EXISTS idx_mb_email_email ON mailbox_email(email_id);

-- =======================
-- USER CONFIG (versioned)
-- =======================
CREATE TABLE IF NOT EXISTS user_config (
  user_id           TEXT PRIMARY KEY,
  classifications_json TEXT,
  preferences_json  TEXT,
  config_version    INTEGER DEFAULT 1,
  last_updated_at   TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES user(user_id)
);

CREATE TABLE IF NOT EXISTS user_config_versions (
  user_id           TEXT NOT NULL,
  version           INTEGER NOT NULL,
  classifications_json TEXT,
  preferences_json  TEXT,
  created_at        TEXT DEFAULT (datetime('now')),
  PRIMARY KEY(user_id, version),
  FOREIGN KEY(user_id) REFERENCES user(user_id)
);

CREATE TABLE IF NOT EXISTS user_config_audit (
  event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT NOT NULL,
  diff_json   TEXT,
  created_at  TEXT DEFAULT (datetime('now')),
  actor       TEXT,
  FOREIGN KEY(user_id) REFERENCES user(user_id)
);
CREATE INDEX IF NOT EXISTS idx_cfg_audit_user ON user_config_audit(user_id);

-- =======================
-- AUTOMATION RUNS + ARTIFACTS
-- =======================
CREATE TABLE IF NOT EXISTS automation_run (
  run_id         TEXT PRIMARY KEY,
  org_id         TEXT NOT NULL,
  mailbox_id     TEXT NOT NULL,
  email_id       TEXT NOT NULL,
  preference_id  TEXT,
  action_type    TEXT NOT NULL,
  status         TEXT NOT NULL,
  started_at     TEXT,
  finished_at    TEXT,
  model_name     TEXT,
  params_json    TEXT,
  input_fingerprint TEXT NOT NULL,
  error_message  TEXT,
  FOREIGN KEY(org_id) REFERENCES organization(org_id),
  FOREIGN KEY(mailbox_id) REFERENCES mailbox(mailbox_id),
  FOREIGN KEY(email_id) REFERENCES email(email_id),
  UNIQUE(mailbox_id, email_id, action_type, input_fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_run_mailbox ON automation_run(mailbox_id, status);
CREATE INDEX IF NOT EXISTS idx_run_email ON automation_run(email_id);

CREATE TABLE IF NOT EXISTS artifact (
  artifact_id   TEXT PRIMARY KEY,
  run_id        TEXT NOT NULL,
  email_id      TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  content_text  TEXT,
  content_json  TEXT,
  language      TEXT,
  content_ptr   TEXT,
  created_at    TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES automation_run(run_id),
  FOREIGN KEY(email_id) REFERENCES email(email_id)
);
CREATE INDEX IF NOT EXISTS idx_artifact_run ON artifact(run_id);
CREATE INDEX IF NOT EXISTS idx_artifact_email ON artifact(email_id);

-- =======================
-- EMAIL FLAGS (fast inbox badges)
-- =======================
CREATE TABLE IF NOT EXISTS email_flag (
  mailbox_email_id INTEGER PRIMARY KEY,
  has_summary      INTEGER DEFAULT 0,
  has_translation  INTEGER DEFAULT 0,
  has_extraction   INTEGER DEFAULT 0,
  last_action_at   TEXT,
  last_action_status TEXT,
  FOREIGN KEY(mailbox_email_id) REFERENCES mailbox_email(mailbox_email_id)
);
