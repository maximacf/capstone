### Foundation layer
## STORAGE
# This Script creates + manages a local database (with SQLite)



# 0: Libs
# Foundation layer — creates & manages the local SQLite database (idempotent)
import sqlite3, hashlib, os
from contextlib import closing

DB_PATH = os.environ.get("DB_PATH", "data/mail.db")

SCHEMA = """
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
"""

# ---- Minimal migration + updated connect() ----
def _column_missing(con, table, column):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    return column not in cols


def migrate_v2(con):
    cur = con.cursor()

    # Add cross-cutting fields to message if they don't exist
    alters = []
    for col, sql in [
        ("urgency",       "ALTER TABLE message ADD COLUMN urgency TEXT CHECK (urgency IN ('high','medium','low','none')) DEFAULT 'none'"),
        ("language",      "ALTER TABLE message ADD COLUMN language TEXT"),
        ("has_attachment","ALTER TABLE message ADD COLUMN has_attachment INTEGER DEFAULT 0"),
        ("thread_id",     "ALTER TABLE message ADD COLUMN thread_id TEXT"),
        ("to_addresses",  "ALTER TABLE message ADD COLUMN to_addresses TEXT"),
        ("cc_addresses",  "ALTER TABLE message ADD COLUMN cc_addresses TEXT"),
        ("entities",      "ALTER TABLE message ADD COLUMN entities TEXT")
    ]:
        if _column_missing(con, "message", col):
            alters.append(sql)
    for sql in alters:
        cur.execute(sql)

    # Indexes (safe to re-create)
    cur.executescript("""
        CREATE INDEX IF NOT EXISTS idx_msg_urgency ON message(urgency);
        CREATE INDEX IF NOT EXISTS idx_msg_thread  ON message(thread_id);
    """)

    # Full-Text Search (subject/body/entities) for fast UI queries
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
            subject, body_text, entities, content='message', content_rowid='rowid'
        )
    """)
    cur.executescript("""
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
    """)
    con.commit()
    
def migrate_v3(con):
    cur = con.cursor()

    # v3 is so that we know when email comes from a shared vs personal inbox
    alters = []
    for col, sql in [
        ("mailbox_id",   "ALTER TABLE raw_message ADD COLUMN mailbox_id TEXT DEFAULT 'me'"),
        ("mailbox_type", "ALTER TABLE raw_message ADD COLUMN mailbox_type TEXT CHECK (mailbox_type IN ('personal','shared')) DEFAULT 'personal'")
    ]:
        if _column_missing(con, "raw_message", col):
            alters.append(sql)
    for sql in alters:
        cur.execute(sql)

    cur.executescript("""
    CREATE INDEX IF NOT EXISTS idx_raw_mailbox ON raw_message(mailbox_id, received_dt);

    -- 2) Create mailbox-specific mapping (this is your "Create Mailbox-Email Entry")
    CREATE TABLE IF NOT EXISTS mailbox_emails (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      mailbox_id    TEXT NOT NULL,
      mailbox_type  TEXT CHECK (mailbox_type IN ('personal','shared')) NOT NULL,
      canonical_key TEXT NOT NULL,           -- prefer internet_id, fallback to raw_message.id
      raw_id        TEXT NOT NULL,           -- Graph message id (raw_message.id)
      seen          INTEGER DEFAULT 0,
      processed     INTEGER DEFAULT 0,
      created_ts    TEXT DEFAULT (datetime('now')),
      UNIQUE(mailbox_id, canonical_key)
    );
    CREATE INDEX IF NOT EXISTS idx_mb_processed ON mailbox_emails(processed, created_ts);
    """)
    con.commit()

def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    # durability + concurrency
    con.execute("PRAGMA journal_mode=WAL;")
    with closing(con.cursor()) as cur:
        cur.executescript(SCHEMA)
    migrate_v2(con)
    migrate_v3(con)  #new for the shared 
    return con


# -----------------------
# Helpers
# -----------------------
def source_key(subject, from_addr, received_dt):
  """Fallback dedupe when internet_id is missing."""
  h = hashlib.sha256(f"{subject}|{from_addr}|{received_dt}".encode()).hexdigest()
  return h[:16]

# ---------- Quick sanity snapshot ----------
def debug_snapshot(con, limit=10):
    cur = con.cursor()
    print("\n== message counts by category ==")
    for cat, n in cur.execute("SELECT COALESCE(manual_category, category) AS cat, COUNT(*) FROM message GROUP BY cat ORDER BY COUNT(*) DESC"):
        print(f"{cat or '(null)'} : {n}")

    print("\n== message counts by urgency ==")
    for urg, n in cur.execute("SELECT urgency, COUNT(*) FROM message GROUP BY urgency ORDER BY COUNT(*) DESC"):
        print(f"{urg} : {n}")

    print(f"\n== latest {limit} messages ==")
    rows = cur.execute("""
        SELECT received_dt, from_addr, subject, COALESCE(manual_category, category) AS cat, urgency
        FROM message
        ORDER BY datetime(received_dt) DESC
        LIMIT ?
    """, (limit,)).fetchall()
    for rdt, frm, subj, cat, urg in rows:
        print(f"{rdt} | {cat}/{urg} | {frm} | {subj[:80]}")


# Add upserts, to not duplicate: 

# ---------- Bronze upsert ----------
def upsert_raw_message(con, row):
  """
  row keys: id, internet_id, received_dt, from_addr, subject,
            body_html, body_type, json_path
  """
  with closing(con.cursor()) as cur:
    cur.execute("""
      INSERT INTO raw_message(
        id, internet_id, received_dt, from_addr, subject,
        body_html, body_type, json_path, mailbox_id, mailbox_type
      )
      VALUES(
        :id, :internet_id, :received_dt, :from_addr, :subject,
        :body_html, :body_type, :json_path,
        COALESCE(:mailbox_id, 'me'),
        COALESCE(:mailbox_type, 'personal')
      )
      ON CONFLICT(id) DO UPDATE SET
        internet_id  = COALESCE(excluded.internet_id, raw_message.internet_id),
        received_dt  = excluded.received_dt,
        from_addr    = excluded.from_addr,
        subject      = excluded.subject,
        body_html    = excluded.body_html,
        body_type    = excluded.body_type,
        json_path    = COALESCE(excluded.json_path, raw_message.json_path),
        mailbox_id   = COALESCE(excluded.mailbox_id, raw_message.mailbox_id),
        mailbox_type = COALESCE(excluded.mailbox_type, raw_message.mailbox_type)
    """, row)

  con.commit()

# ---------- Silver upsert (future-proof: accepts optional fields) ----------
def upsert_message(con, row):
  """
  Required keys now: id, internet_id, received_dt, from_addr, subject,
                     body_text, body_html, category, source_hash,
                     manual_category (optional), from_domain (optional)

  Optional keys (added by migrate_v2): urgency, language, has_attachment,
                                       thread_id, to_addresses, cc_addresses, entities
  This function works even if you don't pass the optional keys yet.
  """

  # Safe defaults so callers can omit new fields
  row = dict(row)  # copy
  row.setdefault("manual_category", None)
  row.setdefault("from_domain", None)
  row.setdefault("urgency", "none")
  row.setdefault("language", None)
  row.setdefault("has_attachment", 0)
  row.setdefault("thread_id", None)
  row.setdefault("to_addresses", None)
  row.setdefault("cc_addresses", None)
  row.setdefault("entities", None)

  with closing(con.cursor()) as cur:
    # Prefer ON CONFLICT(id) since Graph id is stable; internet_id may be missing.
    cur.execute("""
      INSERT INTO message(
        id, internet_id, received_dt, from_addr, subject,
        body_text, body_html, category, source_hash, manual_category, from_domain,
        urgency, language, has_attachment, thread_id, to_addresses, cc_addresses, entities, updated_ts
      )
      VALUES(
        :id, :internet_id, :received_dt, :from_addr, :subject,
        :body_text, :body_html, :category, :source_hash, :manual_category, :from_domain,
        :urgency, :language, :has_attachment, :thread_id, :to_addresses, :cc_addresses, :entities, datetime('now')
      )
      ON CONFLICT(id) DO UPDATE SET
        internet_id     = COALESCE(excluded.internet_id, message.internet_id),
        received_dt     = excluded.received_dt,
        from_addr       = excluded.from_addr,
        subject         = excluded.subject,
        body_text       = excluded.body_text,
        body_html       = excluded.body_html,
        category        = excluded.category,
        manual_category = COALESCE(excluded.manual_category, message.manual_category),
        from_domain     = excluded.from_domain,
        urgency         = excluded.urgency,
        language        = excluded.language,
        has_attachment  = excluded.has_attachment,
        thread_id       = excluded.thread_id,
        to_addresses    = excluded.to_addresses,
        cc_addresses    = excluded.cc_addresses,
        entities        = excluded.entities,
        updated_ts      = datetime('now')
    """, row)
  con.commit()


# ---------- Attachment upsert ----------
def upsert_attachment(con, row):
  """
  row keys: id, message_id, name, content_type, size_bytes, path
  """
  with closing(con.cursor()) as cur:
    cur.execute("""
      INSERT INTO attachment(id, message_id, name, content_type, size_bytes, path)
      VALUES(:id, :message_id, :name, :content_type, :size_bytes, :path)
      ON CONFLICT(id) DO UPDATE SET
        message_id   = excluded.message_id,
        name         = excluded.name,
        content_type = excluded.content_type,
        size_bytes   = excluded.size_bytes,
        path         = excluded.path
    """, row)
  con.commit()

# --------------- new upsert for mailbox entries ------- 
# avoid duplication: 
def upsert_mailbox_email(con, row):
    """
    row keys: mailbox_id, mailbox_type, canonical_key, raw_id
    """
    with closing(con.cursor()) as cur:
        cur.execute("""
          INSERT INTO mailbox_emails(mailbox_id, mailbox_type, canonical_key, raw_id)
          VALUES(:mailbox_id, :mailbox_type, :canonical_key, :raw_id)
          ON CONFLICT(mailbox_id, canonical_key) DO UPDATE SET
            raw_id = excluded.raw_id
        """, row)
    con.commit()


# ---------- Idea insert (returns rowid) ----------
def insert_idea(con, row):
  """
  row keys: message_id, product, ccy, tenor, direction,
            entry_level, target_level, stop_level, horizon,
            status, owner, confidence, tags, extracted_by
  """
  with closing(con.cursor()) as cur:
    cur.execute("""
      INSERT INTO idea(message_id, product, ccy, tenor, direction,
                       entry_level, target_level, stop_level, horizon,
                       status, owner, confidence, tags, extracted_by)
      VALUES(:message_id, :product, :ccy, :tenor, :direction,
             :entry_level, :target_level, :stop_level, :horizon,
             :status, :owner, :confidence, :tags, COALESCE(:extracted_by,'rules_v1'))
    """, row)
    new_id = cur.lastrowid
  con.commit()
  return new_id

# ---------- Classification event log ----------
def log_classification_event(con, message_id, category_auto, rule_name=None, confidence=None):
  with closing(con.cursor()) as cur:
    cur.execute("""
      INSERT INTO classification_event(message_id, category_auto, rule_name, confidence)
      VALUES(?, ?, ?, ?)
    """, (message_id, category_auto, rule_name, confidence))
  con.commit()



# RUN
if __name__ == "__main__":
    con = connect()
    print("DB initialized at:", con.execute("PRAGMA database_list;").fetchone()[2])

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "data", "mail.db")
DB_PATH    = os.environ.get("DB_PATH", DEFAULT_DB)
