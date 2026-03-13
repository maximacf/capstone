"""
SQLAlchemy ORM models for Adaptive Email Intelligence.
PostgreSQL only. Set DATABASE_URL (e.g. postgresql://user:pass@localhost:5432/maildb).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


# ---- Schema version (migration tracking) ----
class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[Optional[str]] = mapped_column(Text, default=None)
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)


# ---- Bronze: raw Graph payload ----
class RawMessage(Base):
    __tablename__ = "raw_message"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    internet_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    received_dt: Mapped[str] = mapped_column(Text, nullable=False)
    from_addr: Mapped[Optional[str]] = mapped_column(Text, default=None)
    subject: Mapped[Optional[str]] = mapped_column(Text, default=None)
    body_html: Mapped[Optional[str]] = mapped_column(Text, default=None)
    body_type: Mapped[Optional[str]] = mapped_column(
        Text, CheckConstraint("body_type IN ('html','text')"), default="html"
    )
    json_path: Mapped[Optional[str]] = mapped_column(Text, default=None)
    mailbox_id: Mapped[str] = mapped_column(Text, default="me")
    mailbox_type: Mapped[str] = mapped_column(
        Text,
        CheckConstraint("mailbox_type IN ('personal','shared')"),
        default="personal",
    )
    created_ts: Mapped[Optional[str]] = mapped_column(Text, default=None)


# ---- Silver: normalized message ----
class Message(Base):
    __tablename__ = "message"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    internet_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    received_dt: Mapped[Optional[str]] = mapped_column(Text, default=None)
    from_addr: Mapped[Optional[str]] = mapped_column(Text, default=None)
    from_domain: Mapped[Optional[str]] = mapped_column(Text, default=None)
    subject: Mapped[Optional[str]] = mapped_column(Text, default=None)
    body_text: Mapped[Optional[str]] = mapped_column(Text, default=None)
    body_html: Mapped[Optional[str]] = mapped_column(Text, default=None)
    category: Mapped[Optional[str]] = mapped_column(Text, default=None)
    source_hash: Mapped[Optional[str]] = mapped_column(Text, default=None)
    manual_category: Mapped[Optional[str]] = mapped_column(Text, default=None)
    urgency: Mapped[str] = mapped_column(
        Text,
        CheckConstraint("urgency IN ('high','medium','low','none')"),
        default="none",
    )
    language: Mapped[Optional[str]] = mapped_column(Text, default=None)
    has_attachment: Mapped[int] = mapped_column(Integer, default=0)
    thread_id: Mapped[Optional[str]] = mapped_column(Text, default=None)
    to_addresses: Mapped[Optional[str]] = mapped_column(Text, default=None)
    cc_addresses: Mapped[Optional[str]] = mapped_column(Text, default=None)
    entities: Mapped[Optional[str]] = mapped_column(Text, default=None)
    updated_ts: Mapped[Optional[str]] = mapped_column(Text, default=None)


# ---- Attachments ----
class Attachment(Base):
    __tablename__ = "attachment"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        Text, ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[Optional[str]] = mapped_column(Text, default=None)
    content_type: Mapped[Optional[str]] = mapped_column(Text, default=None)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    path: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_ts: Mapped[Optional[str]] = mapped_column(Text, default=None)


# ---- Ideas (Gold) ----
class Idea(Base):
    __tablename__ = "idea"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(
        Text, ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    product: Mapped[Optional[str]] = mapped_column(Text, default=None)
    ccy: Mapped[Optional[str]] = mapped_column(Text, default=None)
    tenor: Mapped[Optional[str]] = mapped_column(Text, default=None)
    direction: Mapped[Optional[str]] = mapped_column(Text, default=None)
    entry_level: Mapped[Optional[float]] = mapped_column(Float, default=None)
    target_level: Mapped[Optional[float]] = mapped_column(Float, default=None)
    stop_level: Mapped[Optional[float]] = mapped_column(Float, default=None)
    horizon: Mapped[Optional[str]] = mapped_column(Text, default=None)
    status: Mapped[Optional[str]] = mapped_column(Text, default=None)
    owner: Mapped[Optional[str]] = mapped_column(Text, default=None)
    confidence: Mapped[Optional[str]] = mapped_column(Text, default=None)
    tags: Mapped[Optional[str]] = mapped_column(Text, default=None)
    extracted_by: Mapped[str] = mapped_column(Text, default="rules_v1")
    extracted_ts: Mapped[Optional[str]] = mapped_column(Text, default=None)


# ---- Classification provenance ----
class ClassificationEvent(Base):
    __tablename__ = "classification_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(
        Text, ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    category_auto: Mapped[str] = mapped_column(Text, nullable=False)
    rule_name: Mapped[Optional[str]] = mapped_column(Text, default=None)
    confidence: Mapped[Optional[float]] = mapped_column(Float, default=None)
    created_ts: Mapped[Optional[str]] = mapped_column(Text, default=None)


# ---- Legacy mailbox_emails (003: mailbox_id, canonical_key, raw_id) ----
class MailboxEmails(Base):
    __tablename__ = "mailbox_emails"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mailbox_id: Mapped[str] = mapped_column(Text, nullable=False)
    mailbox_type: Mapped[str] = mapped_column(
        Text,
        CheckConstraint("mailbox_type IN ('personal','shared')"),
        nullable=False,
    )
    canonical_key: Mapped[str] = mapped_column(Text, nullable=False)
    raw_id: Mapped[str] = mapped_column(Text, nullable=False)
    seen: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    created_ts: Mapped[Optional[str]] = mapped_column(Text, default=None)
    __table_args__ = (
        UniqueConstraint("mailbox_id", "canonical_key", name="uq_mbe_mb_canonical"),
    )


# ---- Enterprise: orgs, users, mailboxes ----
class Organization(Base):
    __tablename__ = "organization"
    org_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_ts: Mapped[Optional[str]] = mapped_column(Text, default=None)


class User(Base):
    __tablename__ = "user"  # reserved word, must quote
    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organization.org_id"), nullable=False
    )
    email: Mapped[Optional[str]] = mapped_column(Text, default=None)
    name: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_ts: Mapped[Optional[str]] = mapped_column(Text, default=None)


class Mailbox(Base):
    __tablename__ = "mailbox"
    mailbox_id: Mapped[str] = mapped_column(Text, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organization.org_id"), nullable=False
    )
    mailbox_type: Mapped[str] = mapped_column(
        Text,
        CheckConstraint("mailbox_type IN ('personal','shared_team')"),
        nullable=False,
    )
    owner_user_id: Mapped[Optional[str]] = mapped_column(
        Text, ForeignKey("user.user_id"), default=None
    )
    name: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_ts: Mapped[Optional[str]] = mapped_column(Text, default=None)


# ---- Canonical emails ----
class Email(Base):
    __tablename__ = "email"
    email_id: Mapped[str] = mapped_column(Text, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organization.org_id"), nullable=False
    )
    provider_msg_id: Mapped[Optional[str]] = mapped_column(Text, default=None)
    thread_id: Mapped[Optional[str]] = mapped_column(Text, default=None)
    from_addr: Mapped[Optional[str]] = mapped_column(Text, default=None)
    to_addrs: Mapped[Optional[str]] = mapped_column(Text, default=None)
    cc_addrs: Mapped[Optional[str]] = mapped_column(Text, default=None)
    subject: Mapped[Optional[str]] = mapped_column(Text, default=None)
    received_at: Mapped[Optional[str]] = mapped_column(Text, default=None)
    body_text: Mapped[Optional[str]] = mapped_column(Text, default=None)
    body_html: Mapped[Optional[str]] = mapped_column(Text, default=None)
    raw_mime_ptr: Mapped[Optional[str]] = mapped_column(Text, default=None)
    content_hash: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_ts: Mapped[Optional[str]] = mapped_column(Text, default=None)


# ---- Enterprise mailbox_email (004: mailbox_id, email_id mapping) ----
class MailboxEmail(Base):
    __tablename__ = "mailbox_email"
    mailbox_email_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    mailbox_id: Mapped[str] = mapped_column(
        Text, ForeignKey("mailbox.mailbox_id"), nullable=False
    )
    email_id: Mapped[str] = mapped_column(
        Text, ForeignKey("email.email_id"), nullable=False
    )
    delivered_at: Mapped[Optional[str]] = mapped_column(Text, default=None)
    labels_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    read_state: Mapped[Optional[str]] = mapped_column(Text, default=None)
    archived_state: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_ts: Mapped[Optional[str]] = mapped_column(Text, default=None)
    __table_args__ = (
        UniqueConstraint("mailbox_id", "email_id", name="uq_me_mb_email"),
    )


# ---- User config (versioned) ----
class UserConfig(Base):
    __tablename__ = "user_config"
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("user.user_id"), primary_key=True
    )
    classifications_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    preferences_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    last_updated_at: Mapped[Optional[str]] = mapped_column(Text, default=None)


class UserConfigVersion(Base):
    __tablename__ = "user_config_versions"
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("user.user_id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    classifications_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    preferences_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[Optional[str]] = mapped_column(Text, default=None)


class UserConfigAudit(Base):
    __tablename__ = "user_config_audit"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("user.user_id"), nullable=False
    )
    diff_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[Optional[str]] = mapped_column(Text, default=None)
    actor: Mapped[Optional[str]] = mapped_column(Text, default=None)


# ---- Automation runs + artifacts ----
class AutomationRun(Base):
    __tablename__ = "automation_run"
    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organization.org_id"), nullable=False
    )
    mailbox_id: Mapped[str] = mapped_column(
        Text, ForeignKey("mailbox.mailbox_id"), nullable=False
    )
    email_id: Mapped[str] = mapped_column(
        Text, ForeignKey("email.email_id"), nullable=False
    )
    preference_id: Mapped[Optional[str]] = mapped_column(Text, default=None)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[Optional[str]] = mapped_column(Text, default=None)
    finished_at: Mapped[Optional[str]] = mapped_column(Text, default=None)
    model_name: Mapped[Optional[str]] = mapped_column(Text, default=None)
    params_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    input_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    __table_args__ = (
        UniqueConstraint(
            "mailbox_id",
            "email_id",
            "action_type",
            "input_fingerprint",
            name="uq_run_mb_email_action_fp",
        ),
    )


class Artifact(Base):
    __tablename__ = "artifact"
    artifact_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        Text, ForeignKey("automation_run.run_id"), nullable=False
    )
    email_id: Mapped[str] = mapped_column(
        Text, ForeignKey("email.email_id"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[Optional[str]] = mapped_column(Text, default=None)
    content_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    language: Mapped[Optional[str]] = mapped_column(Text, default=None)
    content_ptr: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[Optional[str]] = mapped_column(Text, default=None)


# ---- Email flags (inbox badges) ----
class EmailFlag(Base):
    __tablename__ = "email_flag"
    mailbox_email_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mailbox_email.mailbox_email_id"),
        primary_key=True,
    )
    has_summary: Mapped[int] = mapped_column(Integer, default=0)
    has_translation: Mapped[int] = mapped_column(Integer, default=0)
    has_extraction: Mapped[int] = mapped_column(Integer, default=0)
    last_action_at: Mapped[Optional[str]] = mapped_column(Text, default=None)
    last_action_status: Mapped[Optional[str]] = mapped_column(Text, default=None)
