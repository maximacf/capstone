#!/usr/bin/env python3
"""
Import ENRON emails from emails.csv directly into the Mailgine database.

No Outlook or SMTP needed. Use this when basic auth is disabled.

Prerequisites:
  1. emails.csv from Kaggle (columns: message, file)
  2. DATABASE_URL set (PostgreSQL or SQLite)
  3. Run from email-processing-just-code/ so store_db and parse_load are importable

Usage:
  python3 import_enron_csv_to_db.py /path/to/emails.csv --limit 100 --dry-run
  python3 import_enron_csv_to_db.py /path/to/emails.csv --limit 500
"""

import argparse
import csv
import hashlib
import os
import sys
from email import policy
from email.parser import Parser
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_load import process_new_raw_messages
from store_db import (
    connect,
    ensure_mailbox,
    ensure_organization,
    source_key,
    upsert_email,
    upsert_mailbox_email,
    upsert_mailbox_email_map,
    upsert_raw_message,
)

ORG_ID = os.getenv("ORG_ID", "default_org")
MAILBOX_ID = os.getenv("MAILBOX_ID", "enron_import")
MAILBOX_TYPE = "personal"


def parse_raw_message(raw: str) -> dict | None:
    """Extract id, internet_id, received_dt, from_addr, subject, body_html from raw RFC email."""
    if not raw or len(raw.strip()) < 10:
        return None
    try:
        msg = Parser(policy=policy.default).parsestr(raw.strip())
    except Exception:
        return None
    mid = msg.get("Message-ID", "").strip() or msg.get("Message-Id", "").strip()
    if not mid:
        mid = hashlib.sha256(raw[:500].encode()).hexdigest()[:32]
    internet_id = mid
    date_str = msg.get("Date", "").strip()
    try:
        dt = parsedate_to_datetime(date_str) if date_str else None
        received_dt = (
            dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else "2001-01-01T00:00:00Z"
        )
    except Exception:
        received_dt = "2001-01-01T00:00:00Z"
    from_addr = msg.get("From", "").strip()
    if from_addr and "<" in from_addr:
        from_addr = from_addr.split("<")[-1].split(">")[0].strip()
    subject = (msg.get("Subject") or "").strip() or "(no subject)"
    body = msg.get_body(preferencelist=("html", "plain"))
    body_html = None
    if body:
        body_html = body.get_content()
        if body.get_content_type() == "text/plain":
            body_html = body_html
    if not body_html and msg.get_payload():
        body_html = str(msg.get_payload()) if not msg.is_multipart() else ""
    return {
        "id": mid,
        "internet_id": internet_id,
        "received_dt": received_dt,
        "from_addr": from_addr or "unknown@enron.com",
        "subject": subject[:500],
        "body_html": (body_html or "")[:500000],
        "body_type": (
            "html" if body and body.get_content_type() == "text/html" else "text"
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Import ENRON emails from CSV directly into Mailgine (no Outlook/SMTP)"
    )
    parser.add_argument("csv_path", type=Path, help="Path to emails.csv")
    parser.add_argument(
        "--limit", type=int, default=500, help="Max rows to import (default 500)"
    )
    parser.add_argument("--skip", type=int, default=0, help="Skip first N rows")
    parser.add_argument(
        "--no-parse",
        action="store_true",
        help="Only insert raw, don't run classification",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = parser.parse_args()

    if not args.csv_path.exists():
        print(f"Error: file not found: {args.csv_path}", file=sys.stderr)
        sys.exit(1)

    con = None if args.dry_run else connect()
    if not args.dry_run:
        ensure_organization(con, ORG_ID)
        ensure_mailbox(
            con,
            mailbox_id=MAILBOX_ID,
            org_id=ORG_ID,
            mailbox_type="personal",
            owner_user_id=None,
            name="ENRON Import",
        )

    imported = 0
    with open(args.csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        if "message" not in [k.lower() for k in (reader.fieldnames or [])]:
            print("Error: no 'message' column found", file=sys.stderr)
            sys.exit(1)
        msg_col = next(k for k in reader.fieldnames if k.lower() == "message")

        for i, row in enumerate(reader):
            if i < args.skip:
                continue
            if imported >= args.limit:
                break
            raw = row.get(msg_col, "")
            parsed = parse_raw_message(raw)
            if not parsed:
                continue

            if not args.dry_run:
                canonical_key = parsed["internet_id"] or parsed["id"]
                upsert_raw_message(
                    con,
                    {
                        "id": parsed["id"],
                        "internet_id": parsed["internet_id"],
                        "received_dt": parsed["received_dt"],
                        "from_addr": parsed["from_addr"],
                        "subject": parsed["subject"],
                        "body_html": parsed["body_html"],
                        "body_type": parsed["body_type"],
                        "json_path": None,
                        "mailbox_id": MAILBOX_ID,
                        "mailbox_type": MAILBOX_TYPE,
                    },
                )
                upsert_mailbox_email(
                    con,
                    {
                        "mailbox_id": MAILBOX_ID,
                        "mailbox_type": MAILBOX_TYPE,
                        "canonical_key": canonical_key,
                        "raw_id": parsed["id"],
                    },
                )
                upsert_email(
                    con,
                    {
                        "email_id": canonical_key,
                        "org_id": ORG_ID,
                        "provider_msg_id": parsed["id"],
                        "thread_id": None,
                        "from_addr": parsed["from_addr"],
                        "to_addrs": None,
                        "cc_addrs": None,
                        "subject": parsed["subject"],
                        "received_at": parsed["received_dt"],
                        "body_text": None,
                        "body_html": parsed["body_html"],
                        "raw_mime_ptr": None,
                        "content_hash": source_key(
                            parsed["subject"],
                            parsed["from_addr"],
                            parsed["received_dt"],
                        ),
                    },
                )
                upsert_mailbox_email_map(
                    con,
                    {
                        "mailbox_id": MAILBOX_ID,
                        "email_id": canonical_key,
                        "delivered_at": parsed["received_dt"],
                        "labels_json": None,
                        "read_state": None,
                        "archived_state": None,
                    },
                )

            imported += 1
            if imported % 50 == 0:
                print(f"  Imported {imported}...")

    print(f"\nImported {imported} raw emails into mailbox '{MAILBOX_ID}'")

    if not args.dry_run and not args.no_parse and imported > 0:
        print("Running classification (parse_load)...")
        result = process_new_raw_messages(
            limit=args.limit,
            mailbox_id=MAILBOX_ID,
            dry_run=False,
        )
        print(f"Classified {result.get('processed_count', 0)} messages")
        print(f"Categories: {result.get('category_counts', {})}")

    print(
        "\nTo view in Mailgine: Dashboard → select mailbox 'enron_import' → Ingest (optional, data already there)"
    )


if __name__ == "__main__":
    main()
