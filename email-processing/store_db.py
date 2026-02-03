### Foundation layer
## STORAGE
# This Script creates + manages a local database (with SQLite)


import glob
import hashlib
import os
import re
import sqlite3
from contextlib import closing

# Foundation layer — creates & manages the local SQLite database (idempotent)

# DB_PATH: canonical database location (env override supported)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "data", "mail.db")
DB_PATH = os.environ.get("DB_PATH", DEFAULT_DB)
MIGRATIONS_DIR = os.path.join(BASE_DIR, "migrations")


# ---- Migration system (DB-first, explicit SQL) ----


def _column_missing(con, table, column):
    """Check if a column exists in a table."""
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    return column not in cols


def _get_applied_versions(con):
    """Get list of migration versions that have been applied."""
    try:
        rows = con.execute(
            "SELECT version FROM schema_version ORDER BY version"
        ).fetchall()
        return {row[0] for row in rows}
    except sqlite3.OperationalError:
        # schema_version table doesn't exist yet
        return set()


def _get_migration_files():
    """Get migration SQL files in order (000, 001, 002, ...)."""
    pattern = os.path.join(MIGRATIONS_DIR, "*.sql")
    files = glob.glob(pattern)
    # Extract version number from filename (e.g., "001_initial_schema.sql" -> 1)
    migrations = []
    for f in files:
        basename = os.path.basename(f)
        match = re.match(r"^(\d+)_", basename)
        if match:
            version = int(match.group(1))
            migrations.append((version, f))
    migrations.sort(key=lambda x: x[0])
    return migrations


def _apply_migration(con, version, sql_file):
    """Apply a single migration file. Handles special cases for ALTER TABLE."""
    cur = con.cursor()

    # Read SQL file
    with open(sql_file, "r") as f:
        sql_content = f.read()

    # Special handling for migration 002 (needs column existence checks)
    # SQLite doesn't support IF NOT EXISTS for ALTER TABLE ADD COLUMN
    if version == 2:
        # Add columns only if they don't exist
        column_additions = [
            (
                "urgency",
                "ALTER TABLE message ADD COLUMN urgency TEXT CHECK (urgency IN ('high','medium','low','none')) DEFAULT 'none'",
            ),
            ("language", "ALTER TABLE message ADD COLUMN language TEXT"),
            (
                "has_attachment",
                "ALTER TABLE message ADD COLUMN has_attachment INTEGER DEFAULT 0",
            ),
            ("thread_id", "ALTER TABLE message ADD COLUMN thread_id TEXT"),
            ("to_addresses", "ALTER TABLE message ADD COLUMN to_addresses TEXT"),
            ("cc_addresses", "ALTER TABLE message ADD COLUMN cc_addresses TEXT"),
            ("entities", "ALTER TABLE message ADD COLUMN entities TEXT"),
        ]
        for col_name, alter_sql in column_additions:
            if _column_missing(con, "message", col_name):
                cur.execute(alter_sql)

        # Execute the rest of the migration (indexes, FTS, triggers)
        # The SQL file contains CREATE INDEX/CREATE VIRTUAL TABLE which are idempotent
        cur.executescript(sql_content)

    # Special handling for migration 003 (needs column existence checks)
    elif version == 3:
        column_additions = [
            (
                "mailbox_id",
                "ALTER TABLE raw_message ADD COLUMN mailbox_id TEXT DEFAULT 'me'",
            ),
            (
                "mailbox_type",
                "ALTER TABLE raw_message ADD COLUMN mailbox_type TEXT CHECK (mailbox_type IN ('personal','shared')) DEFAULT 'personal'",
            ),
        ]
        for col_name, alter_sql in column_additions:
            if _column_missing(con, "raw_message", col_name):
                cur.execute(alter_sql)

        # Execute the rest (indexes, mailbox_emails table - all use IF NOT EXISTS)
        cur.executescript(sql_content)

    else:
        # Standard migration: execute SQL as-is (uses IF NOT EXISTS)
        cur.executescript(sql_content)

    # Record migration in schema_version
    description = (
        os.path.basename(sql_file).replace(".sql", "").replace("_", " ").title()
    )
    cur.execute(
        "INSERT INTO schema_version (version, description) VALUES (?, ?)",
        (version, description),
    )
    con.commit()


def _run_migrations(con):
    """Run all unapplied migrations in order."""
    applied = _get_applied_versions(con)
    migrations = _get_migration_files()

    for version, sql_file in migrations:
        if version not in applied:
            _apply_migration(con, version, sql_file)


def connect():
    """
    Connect to database and ensure schema is up-to-date.
    Idempotent: runs migrations only if needed.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    # durability + concurrency
    con.execute("PRAGMA journal_mode=WAL;")

    # Ensure schema_version table exists (migration 000)
    try:
        con.execute("SELECT 1 FROM schema_version LIMIT 1")
    except sqlite3.OperationalError:
        # Run migration 000 first
        migration_000 = os.path.join(MIGRATIONS_DIR, "000_schema_version.sql")
        if os.path.exists(migration_000):
            with open(migration_000, "r") as f:
                con.executescript(f.read())

    # Run all migrations
    _run_migrations(con)

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
    for cat, n in cur.execute(
        "SELECT COALESCE(manual_category, category) AS cat, COUNT(*) FROM message GROUP BY cat ORDER BY COUNT(*) DESC"
    ):
        print(f"{cat or '(null)'} : {n}")

    print("\n== message counts by urgency ==")
    for urg, n in cur.execute(
        "SELECT urgency, COUNT(*) FROM message GROUP BY urgency ORDER BY COUNT(*) DESC"
    ):
        print(f"{urg} : {n}")

    print(f"\n== latest {limit} messages ==")
    rows = cur.execute(
        """
        SELECT received_dt, from_addr, subject, COALESCE(manual_category, category) AS cat, urgency
        FROM message
        ORDER BY datetime(received_dt) DESC
        LIMIT ?
    """,
        (limit,),
    ).fetchall()
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
        cur.execute(
            """
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
    """,
            row,
        )

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
        cur.execute(
            """
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
    """,
            row,
        )
    con.commit()


# ---------- Attachment upsert ----------
def upsert_attachment(con, row):
    """
    row keys: id, message_id, name, content_type, size_bytes, path
    """
    with closing(con.cursor()) as cur:
        cur.execute(
            """
      INSERT INTO attachment(id, message_id, name, content_type, size_bytes, path)
      VALUES(:id, :message_id, :name, :content_type, :size_bytes, :path)
      ON CONFLICT(id) DO UPDATE SET
        message_id   = excluded.message_id,
        name         = excluded.name,
        content_type = excluded.content_type,
        size_bytes   = excluded.size_bytes,
        path         = excluded.path
    """,
            row,
        )
    con.commit()


# --------------- new upsert for mailbox entries -------
# avoid duplication:
def upsert_mailbox_email(con, row):
    """
    row keys: mailbox_id, mailbox_type, canonical_key, raw_id
    """
    with closing(con.cursor()) as cur:
        cur.execute(
            """
          INSERT INTO mailbox_emails(mailbox_id, mailbox_type, canonical_key, raw_id)
          VALUES(:mailbox_id, :mailbox_type, :canonical_key, :raw_id)
          ON CONFLICT(mailbox_id, canonical_key) DO UPDATE SET
            raw_id = excluded.raw_id
        """,
            row,
        )
    con.commit()


# ---------- Enterprise model helpers ----------
def ensure_organization(con, org_id, name=None):
    with closing(con.cursor()) as cur:
        cur.execute(
            """
            INSERT INTO organization(org_id, name)
            VALUES(?, COALESCE(?, 'Default Org'))
            ON CONFLICT(org_id) DO UPDATE SET
              name = COALESCE(excluded.name, organization.name)
            """,
            (org_id, name),
        )
    con.commit()


def ensure_mailbox(
    con, mailbox_id, org_id, mailbox_type, owner_user_id=None, name=None
):
    with closing(con.cursor()) as cur:
        cur.execute(
            """
            INSERT INTO mailbox(mailbox_id, org_id, mailbox_type, owner_user_id, name)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(mailbox_id) DO UPDATE SET
              org_id = excluded.org_id,
              mailbox_type = excluded.mailbox_type,
              owner_user_id = COALESCE(excluded.owner_user_id, mailbox.owner_user_id),
              name = COALESCE(excluded.name, mailbox.name)
            """,
            (mailbox_id, org_id, mailbox_type, owner_user_id, name),
        )
    con.commit()


def upsert_email(con, row):
    """
    row keys: email_id, org_id, provider_msg_id, thread_id, from_addr, to_addrs,
              cc_addrs, subject, received_at, body_text, body_html,
              raw_mime_ptr, content_hash
    """
    with closing(con.cursor()) as cur:
        cur.execute(
            """
            INSERT INTO email(
              email_id, org_id, provider_msg_id, thread_id,
              from_addr, to_addrs, cc_addrs, subject, received_at,
              body_text, body_html, raw_mime_ptr, content_hash
            )
            VALUES(
              :email_id, :org_id, :provider_msg_id, :thread_id,
              :from_addr, :to_addrs, :cc_addrs, :subject, :received_at,
              :body_text, :body_html, :raw_mime_ptr, :content_hash
            )
            ON CONFLICT(email_id) DO UPDATE SET
              org_id = excluded.org_id,
              provider_msg_id = COALESCE(excluded.provider_msg_id, email.provider_msg_id),
              thread_id = COALESCE(excluded.thread_id, email.thread_id),
              from_addr = excluded.from_addr,
              to_addrs = COALESCE(excluded.to_addrs, email.to_addrs),
              cc_addrs = COALESCE(excluded.cc_addrs, email.cc_addrs),
              subject = excluded.subject,
              received_at = excluded.received_at,
              body_text = COALESCE(excluded.body_text, email.body_text),
              body_html = COALESCE(excluded.body_html, email.body_html),
              raw_mime_ptr = COALESCE(excluded.raw_mime_ptr, email.raw_mime_ptr),
              content_hash = COALESCE(excluded.content_hash, email.content_hash)
            """,
            row,
        )
    con.commit()


def upsert_mailbox_email_map(con, row):
    """
    row keys: mailbox_id, email_id, delivered_at, labels_json, read_state, archived_state
    """
    with closing(con.cursor()) as cur:
        cur.execute(
            """
            INSERT INTO mailbox_email(
              mailbox_id, email_id, delivered_at, labels_json, read_state, archived_state
            )
            VALUES(
              :mailbox_id, :email_id, :delivered_at, :labels_json, :read_state, :archived_state
            )
            ON CONFLICT(mailbox_id, email_id) DO UPDATE SET
              delivered_at = COALESCE(excluded.delivered_at, mailbox_email.delivered_at),
              labels_json = COALESCE(excluded.labels_json, mailbox_email.labels_json),
              read_state = COALESCE(excluded.read_state, mailbox_email.read_state),
              archived_state = COALESCE(excluded.archived_state, mailbox_email.archived_state)
            """,
            row,
        )
    con.commit()


# ---------- Automation runs + artifacts ----------
def upsert_automation_run(con, row):
    """
    row keys: run_id, org_id, mailbox_id, email_id, preference_id, action_type,
              status, started_at, finished_at, model_name, params_json,
              input_fingerprint, error_message
    """
    with closing(con.cursor()) as cur:
        cur.execute(
            """
            INSERT INTO automation_run(
              run_id, org_id, mailbox_id, email_id, preference_id,
              action_type, status, started_at, finished_at, model_name,
              params_json, input_fingerprint, error_message
            )
            VALUES(
              :run_id, :org_id, :mailbox_id, :email_id, :preference_id,
              :action_type, :status, :started_at, :finished_at, :model_name,
              :params_json, :input_fingerprint, :error_message
            )
            ON CONFLICT(run_id) DO UPDATE SET
              status = excluded.status,
              finished_at = excluded.finished_at,
              model_name = excluded.model_name,
              params_json = excluded.params_json,
              error_message = excluded.error_message
            """,
            row,
        )
    con.commit()


def upsert_artifact(con, row):
    """
    row keys: artifact_id, run_id, email_id, artifact_type, content_text,
              content_json, language, content_ptr
    """
    with closing(con.cursor()) as cur:
        cur.execute(
            """
            INSERT INTO artifact(
              artifact_id, run_id, email_id, artifact_type,
              content_text, content_json, language, content_ptr
            )
            VALUES(
              :artifact_id, :run_id, :email_id, :artifact_type,
              :content_text, :content_json, :language, :content_ptr
            )
            ON CONFLICT(artifact_id) DO UPDATE SET
              content_text = COALESCE(excluded.content_text, artifact.content_text),
              content_json = COALESCE(excluded.content_json, artifact.content_json),
              language = COALESCE(excluded.language, artifact.language),
              content_ptr = COALESCE(excluded.content_ptr, artifact.content_ptr)
            """,
            row,
        )
    con.commit()


def upsert_email_flag(con, row):
    """
    row keys: mailbox_email_id, has_summary, has_translation, has_extraction,
              last_action_at, last_action_status
    """
    with closing(con.cursor()) as cur:
        cur.execute(
            """
            INSERT INTO email_flag(
              mailbox_email_id, has_summary, has_translation, has_extraction,
              last_action_at, last_action_status
            )
            VALUES(
              :mailbox_email_id, :has_summary, :has_translation, :has_extraction,
              :last_action_at, :last_action_status
            )
            ON CONFLICT(mailbox_email_id) DO UPDATE SET
              has_summary = MAX(excluded.has_summary, email_flag.has_summary),
              has_translation = MAX(excluded.has_translation, email_flag.has_translation),
              has_extraction = MAX(excluded.has_extraction, email_flag.has_extraction),
              last_action_at = excluded.last_action_at,
              last_action_status = excluded.last_action_status
            """,
            row,
        )
    con.commit()


# ---------- Idea insert (returns rowid) ----------
def insert_idea(con, row):
    """
    row keys: message_id, product, ccy, tenor, direction,
              entry_level, target_level, stop_level, horizon,
              status, owner, confidence, tags, extracted_by
    """
    with closing(con.cursor()) as cur:
        cur.execute(
            """
      INSERT INTO idea(message_id, product, ccy, tenor, direction,
                       entry_level, target_level, stop_level, horizon,
                       status, owner, confidence, tags, extracted_by)
      VALUES(:message_id, :product, :ccy, :tenor, :direction,
             :entry_level, :target_level, :stop_level, :horizon,
             :status, :owner, :confidence, :tags, COALESCE(:extracted_by,'rules_v1'))
    """,
            row,
        )
        new_id = cur.lastrowid
    con.commit()
    return new_id


# ---------- Classification event log ----------
def log_classification_event(
    con, message_id, category_auto, rule_name=None, confidence=None
):
    with closing(con.cursor()) as cur:
        cur.execute(
            """
      INSERT INTO classification_event(message_id, category_auto, rule_name, confidence)
      VALUES(?, ?, ?, ?)
    """,
            (message_id, category_auto, rule_name, confidence),
        )
    con.commit()


# Public API exports (for n8n orchestration and other Python scripts)
# - connect() -> sqlite3.Connection
# - upsert_raw_message(con, row: dict) -> None
# - upsert_message(con, row: dict) -> None
# - upsert_mailbox_email(con, row: dict) -> None
# - ensure_organization(con, org_id, name=None) -> None
# - ensure_mailbox(con, mailbox_id, org_id, mailbox_type, owner_user_id=None, name=None) -> None
# - upsert_email(con, row: dict) -> None
# - upsert_mailbox_email_map(con, row: dict) -> None
# - upsert_automation_run(con, row: dict) -> None
# - upsert_artifact(con, row: dict) -> None
# - upsert_email_flag(con, row: dict) -> None
# - upsert_attachment(con, row: dict) -> None
# - insert_idea(con, row: dict) -> int (returns rowid)
# - log_classification_event(con, message_id, category_auto, rule_name=None, confidence=None) -> None
# - source_key(subject, from_addr, received_dt) -> str (hash)

# RUN
if __name__ == "__main__":
    con = connect()
    print("DB initialized at:", con.execute("PRAGMA database_list;").fetchone()[2])
