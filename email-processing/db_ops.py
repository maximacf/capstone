"""
Small DB utilities that n8n can call via Execute Command.

We keep all SQL here (Python infra layer), and let n8n own when/why
these functions are called.
"""

from __future__ import annotations

import argparse
from typing import Literal, Optional

from store_db import connect


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


def main() -> None:
    parser = argparse.ArgumentParser(description="DB helper operations for n8n.")
    parser.add_argument(
        "--op",
        required=True,
        choices=["mark-seen", "mark-processed"],
        help="Which DB operation to run.",
    )
    parser.add_argument(
        "--mailbox-id",
        required=True,
        help="Mailbox identifier, e.g. 'me' or a shared mailbox address.",
    )
    args = parser.parse_args()

    op: Literal["mark-seen", "mark-processed"] = args.op  # type: ignore[assignment]
    mailbox_id: str = args.mailbox_id

    if op == "mark-seen":
        mark_seen(mailbox_id)
    elif op == "mark-processed":
        mark_processed(mailbox_id)


if __name__ == "__main__":
    main()
