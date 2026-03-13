### Foundation layer
## STORAGE
# SQLAlchemy ORM — creates & manages database (PostgreSQL)


import hashlib
import os
from contextlib import closing
from typing import Any

from database import SessionConnection, get_session_connection, init_db
from models import (
    Artifact,
    Attachment,
    AutomationRun,
    ClassificationEvent,
    Email,
    EmailFlag,
    Idea,
    Mailbox,
    MailboxEmail,
    MailboxEmails,
    Message,
    Organization,
    RawMessage,
    User,
    UserConfig,
    UserConfigAudit,
    UserConfigVersion,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def connect():
    """
    Connect to database and ensure schema exists.
    Returns a SessionConnection (connection-like) for execute/cursor/commit.
    """
    init_db()
    return SessionConnection(get_session_connection())


# -----------------------
# Helpers
# -----------------------
def source_key(subject, from_addr, received_dt):
    """Fallback dedupe when internet_id is missing."""
    h = hashlib.sha256(f"{subject}|{from_addr}|{received_dt}".encode()).hexdigest()
    return h[:16]


# ---------- Quick sanity snapshot ----------
def debug_snapshot(session: Session | SessionConnection, limit: int = 10):
    session = _session(session)
    print("\n== message counts by category ==")
    for row in session.execute(
        text(
            "SELECT COALESCE(manual_category, category) AS cat, COUNT(*) FROM message GROUP BY cat ORDER BY COUNT(*) DESC"
        )
    ).fetchall():
        print(f"{row[0] or '(null)'} : {row[1]}")

    print("\n== message counts by urgency ==")
    for row in session.execute(
        text(
            "SELECT urgency, COUNT(*) FROM message GROUP BY urgency ORDER BY COUNT(*) DESC"
        )
    ).fetchall():
        print(f"{row[0]} : {row[1]}")

    print(f"\n== latest {limit} messages ==")
    stmt = text(
        """
        SELECT received_dt, from_addr, subject, COALESCE(manual_category, category) AS cat, urgency
        FROM message
        ORDER BY received_dt DESC NULLS LAST
        LIMIT :limit
    """
    )
    for r in session.execute(stmt, {"limit": limit}).fetchall():
        subj = (r[2] or "")[:80]
        print(f"{r[0]} | {r[3]}/{r[4]} | {r[1]} | {subj}")


def _session(session_or_conn):
    """Extract Session from SessionConnection or return as-is if already Session."""
    return getattr(session_or_conn, "_session", session_or_conn)


# ---------- Bronze upsert ----------
def upsert_raw_message(
    session: Session | SessionConnection, row: dict[str, Any]
) -> None:
    session = _session(session)
    row = dict(row)
    row.setdefault("mailbox_id", "me")
    row.setdefault("mailbox_type", "personal")
    obj = RawMessage(
        **{k: row.get(k) for k in RawMessage.__table__.c.keys() if k in row}
    )
    session.merge(obj)
    session.commit()


# ---------- Silver upsert ----------
def upsert_message(session: Session | SessionConnection, row: dict[str, Any]) -> None:
    session = _session(session)
    row = dict(row)
    row.setdefault("manual_category", None)
    row.setdefault("from_domain", None)
    row.setdefault("urgency", "none")
    row.setdefault("language", None)
    row.setdefault("has_attachment", 0)
    row.setdefault("thread_id", None)
    row.setdefault("to_addresses", None)
    row.setdefault("cc_addresses", None)
    row.setdefault("entities", None)
    obj = Message(**{k: row.get(k) for k in Message.__table__.c.keys() if k in row})
    session.merge(obj)
    session.commit()


# ---------- Attachment upsert ----------
def upsert_attachment(
    session: Session | SessionConnection, row: dict[str, Any]
) -> None:
    session = _session(session)
    obj = Attachment(
        **{k: row.get(k) for k in Attachment.__table__.c.keys() if k in row}
    )
    session.merge(obj)
    session.commit()


# ---------- Mailbox emails (legacy 003) ----------
def upsert_mailbox_email(
    session: Session | SessionConnection, row: dict[str, Any]
) -> None:
    session = _session(session)
    existing = (
        session.execute(
            select(MailboxEmails).where(
                MailboxEmails.mailbox_id == row["mailbox_id"],
                MailboxEmails.canonical_key == row["canonical_key"],
            )
        )
        .scalars()
        .first()
    )
    if existing:
        existing.raw_id = row["raw_id"]
    else:
        obj = MailboxEmails(
            **{k: row.get(k) for k in MailboxEmails.__table__.c.keys() if k in row}
        )
        session.add(obj)
    session.commit()


# ---------- Enterprise model helpers ----------
def ensure_organization(
    session: Session | SessionConnection, org_id: str, name: str | None = None
) -> None:
    session = _session(session)
    obj = Organization(org_id=org_id, name=name or "Default Org")
    session.merge(obj)
    session.commit()


def ensure_mailbox(
    session: Session | SessionConnection,
    mailbox_id: str,
    org_id: str,
    mailbox_type: str,
    owner_user_id: str | None = None,
    name: str | None = None,
) -> None:
    session = _session(session)
    obj = Mailbox(
        mailbox_id=mailbox_id,
        org_id=org_id,
        mailbox_type=mailbox_type,
        owner_user_id=owner_user_id,
        name=name,
    )
    session.merge(obj)
    session.commit()


def upsert_email(session: Session | SessionConnection, row: dict[str, Any]) -> None:
    session = _session(session)
    obj = Email(**{k: row.get(k) for k in Email.__table__.c.keys() if k in row})
    session.merge(obj)
    session.commit()


def upsert_mailbox_email_map(
    session: Session | SessionConnection, row: dict[str, Any]
) -> None:
    session = _session(session)
    # mailbox_email has composite unique (mailbox_id, email_id); need upsert
    existing = (
        session.execute(
            select(MailboxEmail).where(
                MailboxEmail.mailbox_id == row["mailbox_id"],
                MailboxEmail.email_id == row["email_id"],
            )
        )
        .scalars()
        .first()
    )
    if existing:
        for k, v in row.items():
            if hasattr(existing, k) and v is not None:
                setattr(existing, k, v)
    else:
        obj = MailboxEmail(
            **{k: row.get(k) for k in MailboxEmail.__table__.c.keys() if k in row}
        )
        session.add(obj)
    session.commit()


# ---------- Automation runs + artifacts ----------
def upsert_automation_run(
    session: Session | SessionConnection, row: dict[str, Any]
) -> None:
    session = _session(session)
    obj = AutomationRun(
        **{k: row.get(k) for k in AutomationRun.__table__.c.keys() if k in row}
    )
    session.merge(obj)
    session.commit()


def upsert_artifact(session: Session | SessionConnection, row: dict[str, Any]) -> None:
    session = _session(session)
    obj = Artifact(**{k: row.get(k) for k in Artifact.__table__.c.keys() if k in row})
    session.merge(obj)
    session.commit()


def upsert_email_flag(
    session: Session | SessionConnection, row: dict[str, Any]
) -> None:
    session = _session(session)
    existing = (
        session.execute(
            select(EmailFlag).where(
                EmailFlag.mailbox_email_id == row["mailbox_email_id"]
            )
        )
        .scalars()
        .first()
    )
    if existing:
        existing.has_summary = max(existing.has_summary, row.get("has_summary", 0))
        existing.has_translation = max(
            existing.has_translation, row.get("has_translation", 0)
        )
        existing.has_extraction = max(
            existing.has_extraction, row.get("has_extraction", 0)
        )
        if row.get("last_action_at") is not None:
            existing.last_action_at = row["last_action_at"]
        if row.get("last_action_status") is not None:
            existing.last_action_status = row["last_action_status"]
    else:
        obj = EmailFlag(
            **{k: row.get(k) for k in EmailFlag.__table__.c.keys() if k in row}
        )
        session.add(obj)
    session.commit()


# ---------- User config ----------
def ensure_user(
    session: Session | SessionConnection,
    user_id: str,
    org_id: str,
    email: str | None = None,
    name: str | None = None,
) -> None:
    session = _session(session)
    obj = User(user_id=user_id, org_id=org_id, email=email, name=name)
    session.merge(obj)
    session.commit()


def upsert_user_config(
    session: Session | SessionConnection, row: dict[str, Any]
) -> None:
    session = _session(session)
    obj = UserConfig(
        **{k: row.get(k) for k in UserConfig.__table__.c.keys() if k in row}
    )
    session.merge(obj)
    session.commit()


def insert_user_config_version(
    session: Session | SessionConnection, row: dict[str, Any]
) -> None:
    session = _session(session)
    obj = UserConfigVersion(
        **{k: row.get(k) for k in UserConfigVersion.__table__.c.keys() if k in row}
    )
    session.add(obj)
    session.commit()


def insert_user_config_audit(
    session: Session | SessionConnection, row: dict[str, Any]
) -> None:
    session = _session(session)
    obj = UserConfigAudit(
        **{k: row.get(k) for k in UserConfigAudit.__table__.c.keys() if k in row}
    )
    session.add(obj)
    session.commit()


# ---------- Idea insert (returns id) ----------
def insert_idea(session: Session | SessionConnection, row: dict[str, Any]) -> int:
    session = _session(session)
    extracted_by = row.get("extracted_by") or "rules_v1"
    obj = Idea(**{**row, "extracted_by": extracted_by})
    session.add(obj)
    session.flush()
    session.commit()
    return obj.id


# ---------- Classification event log ----------
def log_classification_event(
    session: Session | SessionConnection,
    message_id: str,
    category_auto: str,
    rule_name: str | None = None,
    confidence: float | None = None,
) -> int:
    """Insert classification event. Returns the new event id."""
    session = _session(session)
    obj = ClassificationEvent(
        message_id=message_id,
        category_auto=category_auto,
        rule_name=rule_name,
        confidence=confidence,
    )
    session.add(obj)
    session.flush()
    event_id = obj.id
    session.commit()
    return event_id


# Public API: connect() returns Session; all upsert/ensure/log take session

if __name__ == "__main__":
    session = connect()
    try:
        print("DB initialized (PostgreSQL)")
    finally:
        session.close()
