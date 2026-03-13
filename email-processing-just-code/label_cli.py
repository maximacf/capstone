"""
Command-line helper to label emails without the Streamlit UI.

Usage:
    python label_cli.py
"""

from __future__ import annotations

import argparse
import os
import textwrap
from typing import Optional

from classification import CANONICAL_LABELS
from store_db import connect


def get_connection(db_path: Optional[str] = None):
    """Connect to database. Uses DATABASE_URL (PostgreSQL). db_path is ignored."""
    return connect()


def fetch_next_unlabeled(con) -> Optional[tuple]:
    row = con.execute(
        """
        SELECT id, received_dt, from_addr, subject, body_text, category
        FROM message
        WHERE manual_category IS NULL
        ORDER BY received_dt DESC NULLS LAST
        LIMIT 1
        """
    ).fetchone()
    return row


def display_message(row: tuple) -> None:
    msg_id, received_dt, from_addr, subject, body_text, auto_category = row
    print("\n" + "=" * 80)
    print(f"ID: {msg_id}")
    print(f"Received: {received_dt}")
    print(f"From: {from_addr}")
    print(f"Subject: {subject}")
    print(f"Auto category: {auto_category}")
    print("-" * 80)
    preview = (body_text or "").strip()
    if not preview:
        print("[No body text]")
    else:
        print(textwrap.fill(preview, width=100, replace_whitespace=False))
    print("=" * 80)


def prompt_label() -> Optional[str]:
    print("\nLabels:")
    for idx, label in enumerate(CANONICAL_LABELS, start=1):
        print(f"  {idx}. {label}")
    print("  s. skip   q. quit")

    choice = input("Select label (number or name): ").strip()
    if not choice:
        return None
    low = choice.lower()
    if low in {"q", "quit"}:
        return "QUIT"
    if low in {"s", "skip"}:
        return None
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(CANONICAL_LABELS):
            return CANONICAL_LABELS[idx]
    # match by name ignoring case
    for label in CANONICAL_LABELS:
        if label.lower() == low:
            return label
    print("Invalid choice.")
    return prompt_label()


def apply_label(con, msg_id: str, label: str) -> None:
    con.execute(
        "UPDATE message SET manual_category = ?, updated_ts = CURRENT_TIMESTAMP WHERE id = ?",
        (label, msg_id),
    )
    con.commit()
    print(f"Saved label: {label}")


def loop(db_path: Optional[str] = None) -> None:
    con = get_connection(db_path)
    try:
        while True:
            row = fetch_next_unlabeled(con)
            if not row:
                print("All messages are labeled 🎉")
                return
            display_message(row)
            label = prompt_label()
            if label == "QUIT":
                print("Stopping without labeling current message.")
                return
            if label is None:
                print("Skipping...")
                continue
            apply_label(con, row[0], label)
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description="Label emails via CLI.")
    parser.add_argument("--db", help="Ignored. Use DATABASE_URL env for PostgreSQL.")
    args = parser.parse_args()
    loop(args.db)


if __name__ == "__main__":
    main()
