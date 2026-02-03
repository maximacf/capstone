"""
Small DB utilities that n8n can call via Execute Command.

We keep all SQL here (Python infra layer), and let n8n own when/why
these functions are called.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from typing import Literal, Optional

from store_db import (
    connect,
    ensure_user,
    insert_user_config_audit,
    insert_user_config_version,
    upsert_user_config,
)


def mark_seen(mailbox_id: str) -> None:
    """
    Set `seen = 1` for all mailbox_emails for a given mailbox
    where `processed = 0`.
    """
    con = connect()
    cur = con.cursor()
    cur.execute(
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
    cur = con.cursor()
    cur.execute(
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


def upsert_config(
    user_id: str,
    org_id: str,
    classifications_json: str,
    preferences_json: str,
    actor: str | None = None,
) -> None:
    con = connect()
    ensure_user(con, user_id=user_id, org_id=org_id)

    # Determine next version
    cur = con.cursor()
    current = cur.execute(
        "SELECT COALESCE(config_version, 0) FROM user_config WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    next_version = (current[0] or 0) + 1

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


def main() -> None:
    parser = argparse.ArgumentParser(description="DB helper operations for n8n.")
    parser.add_argument(
        "--op",
        required=True,
        choices=["mark-seen", "mark-processed", "upsert-user-config"],
        help="Which DB operation to run.",
    )
    parser.add_argument(
        "--mailbox-id",
        required=True,
        help="Mailbox identifier, e.g. 'me' or a shared mailbox address.",
    )
    parser.add_argument("--user-id", help="User id for config updates")
    parser.add_argument("--org-id", help="Organization id for config updates")
    parser.add_argument("--classifications-json", help="JSON string")
    parser.add_argument("--preferences-json", help="JSON string")
    parser.add_argument("--actor", help="Who performed the update")
    args = parser.parse_args()

    op: Literal["mark-seen", "mark-processed"] = args.op  # type: ignore[assignment]
    mailbox_id: str = args.mailbox_id

    if op == "mark-seen":
        mark_seen(mailbox_id)
    elif op == "mark-processed":
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


if __name__ == "__main__":
    main()
