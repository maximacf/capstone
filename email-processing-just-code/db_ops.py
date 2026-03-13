"""
Small DB utilities for config, classification, and automation operations.

All SQL is centralized here; the API layer orchestrates when and why to call these operations.
these functions are called.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.exc import IntegrityError
from store_db import (
    connect,
    ensure_organization,
    ensure_user,
    insert_user_config_audit,
    insert_user_config_version,
    log_classification_event,
    upsert_artifact,
    upsert_automation_run,
    upsert_email_flag,
    upsert_user_config,
)


def mark_seen(mailbox_id: str) -> None:
    """
    Set `seen = 1` for all mailbox_emails for a given mailbox
    where `processed = 0`.
    """
    con = connect()
    con.execute(
        """
        UPDATE mailbox_emails
        SET seen = 1
        WHERE mailbox_id = ?
          AND processed = 0
        """,
        (mailbox_id,),
    )
    con.commit()


def mark_processed(mailbox_id: str) -> None:
    """
    Set `processed = 1` for mailbox_emails rows where there is already
    a corresponding row in `message`.
    """
    con = connect()
    con.execute(
        """
        UPDATE mailbox_emails
        SET processed = 1
        WHERE mailbox_id = ?
          AND processed = 0
          AND EXISTS (
            SELECT 1
            FROM message m
            WHERE m.id = mailbox_emails.raw_id
          )
        """,
        (mailbox_id,),
    )
    con.commit()


def _hash_payload(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def upsert_config(
    user_id: str,
    org_id: str,
    classifications_json: str,
    preferences_json: str,
    actor: str | None = None,
) -> None:
    con = connect()
    ensure_organization(con, org_id)
    ensure_user(con, user_id=user_id, org_id=org_id)

    # Determine next version
    current = con.execute(
        "SELECT COALESCE(config_version, 0) FROM user_config WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    current_version = current[0] if current else 0
    next_version = current_version + 1

    upsert_user_config(
        con,
        {
            "user_id": user_id,
            "classifications_json": classifications_json,
            "preferences_json": preferences_json,
            "config_version": next_version,
        },
    )
    insert_user_config_version(
        con,
        {
            "user_id": user_id,
            "version": next_version,
            "classifications_json": classifications_json,
            "preferences_json": preferences_json,
        },
    )
    diff = {
        "user_id": user_id,
        "version": next_version,
        "payload_hash": _hash_payload(
            {
                "classifications_json": classifications_json,
                "preferences_json": preferences_json,
            }
        ),
    }
    insert_user_config_audit(
        con,
        {"user_id": user_id, "diff_json": json.dumps(diff), "actor": actor},
    )


def get_user_config(user_id: str) -> dict:
    con = connect()
    row = con.execute(
        """
        SELECT classifications_json, preferences_json, config_version, last_updated_at
        FROM user_config
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return {"status": "not_found", "user_id": user_id}
    return {
        "status": "ok",
        "user_id": user_id,
        "classifications_json": row[0],
        "preferences_json": row[1],
        "config_version": row[2],
        "last_updated_at": row[3],
    }


def select_llm_candidates(
    mailbox_id: str | None,
    limit: int,
    min_confidence: float | None,
) -> list[dict]:
    con = connect()
    params: list[object] = []
    mailbox_join = ""
    mailbox_where = ""
    confidence_where = ""
    if min_confidence is not None:
        confidence_where = "(latest_ce.confidence IS NULL OR latest_ce.confidence < ?)"
        params.append(min_confidence)
    if mailbox_id:
        mailbox_join = (
            "JOIN mailbox_email me ON me.email_id = COALESCE(m.internet_id, m.id)"
        )
        mailbox_where = "AND me.mailbox_id = ?"
        params.append(mailbox_id)
    params.append(limit)
    body_substr = "LEFT(COALESCE(m.body_text, ''), 4000)"
    select_cols = """m.id,
      COALESCE(m.internet_id, m.id) AS email_id,
      m.subject,
      m.from_addr,
      {body_substr} AS body_text,
      latest_ce.confidence AS last_confidence,
      latest_ce.rule_name AS last_rule,
      m.received_dt"""
    order_clause = "ORDER BY m.received_dt DESC"
    select_cols = select_cols.format(body_substr=body_substr)
    rows = con.execute(
        f"""
        WITH latest AS (
          SELECT message_id, MAX(id) AS max_id
          FROM classification_event
          GROUP BY message_id
        ),
        latest_ce AS (
          SELECT ce.message_id, ce.confidence, ce.rule_name
          FROM classification_event ce
          JOIN latest l ON l.message_id = ce.message_id AND l.max_id = ce.id
        )
        SELECT DISTINCT
          {select_cols}
        FROM message m
        LEFT JOIN latest_ce ON latest_ce.message_id = m.id
        {mailbox_join}
        WHERE {confidence_where or "1=1"}
        {mailbox_where}
        {order_clause}
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "id": row[0],
            "email_id": row[1],
            "subject": row[2],
            "from_addr": row[3],
            "body_text": row[4],
            "last_confidence": row[5],
            "last_rule": row[6],
        }
        for row in rows
    ]


def insert_llm_classification(
    message_id: str,
    label: str,
    confidence: float,
    rule_name: str,
    update_message: bool,
) -> int:
    con = connect()
    event_id = log_classification_event(
        con,
        message_id=message_id,
        category_auto=label,
        rule_name=rule_name,
        confidence=confidence,
    )
    if update_message:
        con.execute(
            """
            UPDATE message
            SET category = ?, updated_ts = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (label, message_id),
        )
    con.commit()
    return event_id


def start_automation_run(
    org_id: str,
    mailbox_id: str,
    email_id: str,
    action_type: str,
    input_json: str,
    preference_id: str | None,
    model_name: str | None,
    params_json: str | None,
) -> dict:
    input_payload = json.loads(input_json) if input_json else {}
    input_fingerprint = _hash_payload(input_payload)
    run_id = _hash_text(f"{mailbox_id}|{email_id}|{action_type}|{input_fingerprint}")
    con = connect()
    row = {
        "run_id": run_id,
        "org_id": org_id,
        "mailbox_id": mailbox_id,
        "email_id": email_id,
        "preference_id": preference_id,
        "action_type": action_type,
        "status": "running",
        "started_at": _now_iso(),
        "finished_at": None,
        "model_name": model_name,
        "params_json": params_json,
        "input_fingerprint": input_fingerprint,
        "error_message": None,
    }
    existing = con.execute(
        """
        SELECT run_id, status
        FROM automation_run
        WHERE mailbox_id = ?
          AND email_id = ?
          AND action_type = ?
          AND input_fingerprint = ?
        """,
        (mailbox_id, email_id, action_type, input_fingerprint),
    ).fetchone()
    if existing:
        return {
            "status": "duplicate",
            "run_id": existing[0],
            "existing_status": existing[1],
            "input_fingerprint": input_fingerprint,
        }
    try:
        upsert_automation_run(con, row)
    except IntegrityError:
        return {
            "status": "duplicate",
            "run_id": run_id,
            "existing_status": "unknown",
            "input_fingerprint": input_fingerprint,
        }
    return {
        "status": "created",
        "run_id": run_id,
        "input_fingerprint": input_fingerprint,
    }


def finish_automation_run(
    run_id: str,
    status: str,
    error_message: str | None,
    model_name: str | None,
    params_json: str | None,
) -> None:
    con = connect()
    con.execute(
        """
        UPDATE automation_run
        SET status = ?,
            finished_at = ?,
            model_name = COALESCE(?, model_name),
            params_json = COALESCE(?, params_json),
            error_message = ?
        WHERE run_id = ?
        """,
        (status, _now_iso(), model_name, params_json, error_message, run_id),
    )
    con.commit()


def insert_action_artifact(
    run_id: str,
    email_id: str,
    artifact_type: str,
    content_text: str | None,
    content_json: str | None,
    language: str | None,
    content_ptr: str | None,
    artifact_id: str | None,
) -> str:
    payload = json.dumps(
        {
            "content_text": content_text,
            "content_json": content_json,
            "language": language,
            "content_ptr": content_ptr,
        },
        sort_keys=True,
    )
    artifact_id = artifact_id or _hash_text(f"{run_id}|{artifact_type}|{payload}")
    con = connect()
    upsert_artifact(
        con,
        {
            "artifact_id": artifact_id,
            "run_id": run_id,
            "email_id": email_id,
            "artifact_type": artifact_type,
            "content_text": content_text,
            "content_json": content_json,
            "language": language,
            "content_ptr": content_ptr,
        },
    )
    return artifact_id


def update_email_flag_for_action(
    mailbox_id: str,
    email_id: str,
    action_type: str,
    status: str,
) -> dict:
    con = connect()
    row = con.execute(
        """
        SELECT mailbox_email_id
        FROM mailbox_email
        WHERE mailbox_id = ? AND email_id = ?
        """,
        (mailbox_id, email_id),
    ).fetchone()
    if not row:
        return {"status": "not_found", "mailbox_id": mailbox_id, "email_id": email_id}
    mailbox_email_id = row[0]
    flags = {
        "has_summary": 1 if action_type == "summarize" else 0,
        "has_translation": 1 if action_type == "translate" else 0,
        "has_extraction": 1 if action_type == "extract" else 0,
    }
    upsert_email_flag(
        con,
        {
            "mailbox_email_id": mailbox_email_id,
            "has_summary": flags["has_summary"],
            "has_translation": flags["has_translation"],
            "has_extraction": flags["has_extraction"],
            "last_action_at": _now_iso(),
            "last_action_status": status,
        },
    )
    return {
        "status": "ok",
        "mailbox_email_id": mailbox_email_id,
        "action_type": action_type,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DB helper operations (config, classification, automation)."
    )
    parser.add_argument(
        "--op",
        required=True,
        choices=[
            "mark-seen",
            "mark-processed",
            "upsert-user-config",
            "get-user-config",
            "select-llm-candidates",
            "insert-llm-classification",
            "start-automation-run",
            "finish-automation-run",
            "insert-artifact",
            "update-email-flag",
        ],
        help="Which DB operation to run.",
    )
    parser.add_argument(
        "--mailbox-id",
        help="Mailbox identifier, e.g. 'me' or a shared mailbox address.",
    )
    parser.add_argument("--user-id", help="User id for config updates")
    parser.add_argument("--org-id", help="Organization id for config updates")
    parser.add_argument("--classifications-json", help="JSON string")
    parser.add_argument("--preferences-json", help="JSON string")
    parser.add_argument("--actor", help="Who performed the update")
    parser.add_argument("--limit", type=int, default=50, help="Limit for selection")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.7,
        help="Minimum confidence threshold",
    )
    parser.add_argument("--message-id", help="Message id for classification insert")
    parser.add_argument("--label", help="Label for classification insert")
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.85,
        help="Confidence for classification insert",
    )
    parser.add_argument(
        "--rule-name",
        default="llm_v1",
        help="Rule name for classification insert",
    )
    parser.add_argument(
        "--update-message",
        action="store_true",
        help="Update message.category with label",
    )
    parser.add_argument("--email-id", help="Email id")
    parser.add_argument(
        "--action-type", help="Action type (summarize/translate/extract)"
    )
    parser.add_argument("--input-json", help="JSON string for input fingerprint")
    parser.add_argument("--preference-id", help="Preference id for run")
    parser.add_argument("--params-json", help="JSON string for action params")
    parser.add_argument("--model-name", help="Model name")
    parser.add_argument("--status", help="Run status (success/failed)")
    parser.add_argument("--error-message", help="Error message for failed runs")
    parser.add_argument("--run-id", help="Automation run id")
    parser.add_argument("--artifact-type", help="Artifact type (summary/translation)")
    parser.add_argument("--content-text", help="Artifact content text")
    parser.add_argument("--content-json", help="Artifact content JSON")
    parser.add_argument("--language", help="Artifact language")
    parser.add_argument("--content-ptr", help="Artifact content pointer")
    parser.add_argument("--artifact-id", help="Artifact id override")
    args = parser.parse_args()

    op: Literal[
        "mark-seen",
        "mark-processed",
        "upsert-user-config",
        "get-user-config",
        "select-llm-candidates",
        "insert-llm-classification",
        "start-automation-run",
        "finish-automation-run",
        "insert-artifact",
        "update-email-flag",
    ] = args.op  # type: ignore[assignment]
    mailbox_id = args.mailbox_id

    if op == "mark-seen":
        if not mailbox_id:
            raise RuntimeError("--mailbox-id is required for mark-seen")
        mark_seen(mailbox_id)
    elif op == "mark-processed":
        if not mailbox_id:
            raise RuntimeError("--mailbox-id is required for mark-processed")
        mark_processed(mailbox_id)
    elif op == "upsert-user-config":
        if not (
            args.user_id
            and args.org_id
            and args.classifications_json
            and args.preferences_json
        ):
            raise RuntimeError(
                "user_id, org_id, classifications_json, preferences_json are required"
            )
        upsert_config(
            user_id=args.user_id,
            org_id=args.org_id,
            classifications_json=args.classifications_json,
            preferences_json=args.preferences_json,
            actor=args.actor,
        )
    elif op == "get-user-config":
        if not args.user_id:
            raise RuntimeError("user_id is required")
        result = get_user_config(args.user_id)
        print(json.dumps(result))
    elif op == "select-llm-candidates":
        result = select_llm_candidates(
            mailbox_id=mailbox_id,
            limit=args.limit,
            min_confidence=args.min_confidence,
        )
        print(json.dumps(result))
    elif op == "insert-llm-classification":
        if not (args.message_id and args.label):
            raise RuntimeError("message_id and label are required")
        event_id = insert_llm_classification(
            message_id=args.message_id,
            label=args.label,
            confidence=args.confidence,
            rule_name=args.rule_name,
            update_message=args.update_message,
        )
        print(json.dumps({"status": "ok", "classification_id": event_id}))
    elif op == "start-automation-run":
        if not (
            args.org_id
            and mailbox_id
            and args.email_id
            and args.action_type
            and args.input_json
        ):
            raise RuntimeError(
                "org_id, mailbox_id, email_id, action_type, input_json are required"
            )
        result = start_automation_run(
            org_id=args.org_id,
            mailbox_id=mailbox_id,
            email_id=args.email_id,
            action_type=args.action_type,
            input_json=args.input_json,
            preference_id=args.preference_id,
            model_name=args.model_name,
            params_json=args.params_json,
        )
        print(json.dumps(result))
    elif op == "finish-automation-run":
        if not (args.run_id and args.status):
            raise RuntimeError("run_id and status are required")
        finish_automation_run(
            run_id=args.run_id,
            status=args.status,
            error_message=args.error_message,
            model_name=args.model_name,
            params_json=args.params_json,
        )
    elif op == "insert-artifact":
        if not (args.run_id and args.email_id and args.artifact_type):
            raise RuntimeError("run_id, email_id, artifact_type are required")
        artifact_id = insert_action_artifact(
            run_id=args.run_id,
            email_id=args.email_id,
            artifact_type=args.artifact_type,
            content_text=args.content_text,
            content_json=args.content_json,
            language=args.language,
            content_ptr=args.content_ptr,
            artifact_id=args.artifact_id,
        )
        print(json.dumps({"status": "ok", "artifact_id": artifact_id}))
    elif op == "update-email-flag":
        if not (mailbox_id and args.email_id and args.action_type and args.status):
            raise RuntimeError("mailbox_id, email_id, action_type, status are required")
        result = update_email_flag_for_action(
            mailbox_id=mailbox_id,
            email_id=args.email_id,
            action_type=args.action_type,
            status=args.status,
        )
        print(json.dumps(result))


if __name__ == "__main__":
    main()
