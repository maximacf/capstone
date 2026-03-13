#!/usr/bin/env python3
"""
Send ENRON emails from emails.csv to your Outlook inbox via Office 365 SMTP.

The Kaggle ENRON emails.csv can have different structures. This script handles:
  - Raw format: "file" + "message" (full RFC 5322 email text)
  - Structured: "sender", "recipients"/"tos", "date", "subject", "body" (or similar)

Prerequisites:
  1. emails.csv from Kaggle (e.g. wcukierski/enron-email-dataset)
  2. .env: OUTLOOK_EMAIL, OUTLOOK_PASSWORD
"""

import argparse
import csv
import itertools
import os
import sys
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
USERNAME = os.getenv("OUTLOOK_EMAIL") or os.getenv("SMTP_USERNAME")
PASSWORD = os.getenv("OUTLOOK_PASSWORD") or os.getenv("SMTP_PASSWORD")


def detect_columns(reader) -> tuple[dict[str, str], dict | None]:
    """Inspect first row and map to our expected fields. Returns (col_map, first_row)."""
    row = next(reader, None)
    if not row:
        return {}, None
    cols_lower = {k.lower().strip(): k for k in row.keys()}
    mapping = {}
    for our_name, candidates in [
        ("message", ["message", "content", "raw", "text"]),
        ("file", ["file", "filename", "path"]),
        ("sender", ["sender", "from", "from_addr", "fromaddress"]),
        ("recipients", ["recipients", "tos", "to", "to_addr", "receiver"]),
        ("date", ["date", "datetime", "timestamp", "sent_date"]),
        ("subject", ["subject", "subj"]),
        ("body", ["body", "content", "text"]),
    ]:
        for c in candidates:
            if c in cols_lower:
                mapping[our_name] = cols_lower[c]
                break
    return mapping, row


def row_to_message(row: dict, col_map: dict, idx: int) -> EmailMessage | None:
    """Convert CSV row to EmailMessage. Handles raw 'message' or structured columns."""
    if "message" in col_map:
        raw = row.get(col_map["message"], "")
        if not raw or not isinstance(raw, str):
            return None
        raw = raw.strip()
        if len(raw) < 10:
            return None
        try:
            from email import policy
            from email.parser import Parser

            msg = Parser(policy=policy.default).parsestr(raw)
            return msg if isinstance(msg, EmailMessage) else None
        except Exception:
            pass

    # Structured columns
    sender = row.get(col_map.get("sender", ""), "unknown@enron.com")
    subject = row.get(col_map.get("subject", ""), "(no subject)")
    body = row.get(col_map.get("body", ""), "") or row.get(
        col_map.get("message", ""), ""
    )

    if not body and not subject:
        return None

    em = EmailMessage()
    em["From"] = sender if sender else "unknown@enron.com"
    em["To"] = USERNAME
    em["Subject"] = (subject or "(no subject)")[:500]
    em["Date"] = formatdate(localtime=True)
    em.set_content((body or "(no body)")[:100000])
    return em


def send_message(msg: EmailMessage) -> bool:
    """Send EmailMessage to our Outlook inbox."""
    import smtplib

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(USERNAME, PASSWORD)
            server.sendmail(
                from_addr=USERNAME,
                to_addrs=[USERNAME],
                msg=msg.as_bytes(),
            )
    except Exception as e:
        print(f"  FAIL: {e}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Send ENRON emails from emails.csv to your Outlook inbox"
    )
    parser.add_argument(
        "csv_path",
        type=Path,
        help="Path to emails.csv",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max emails to send (default 100)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds between sends (default 2)",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Skip first N rows (for resuming)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only inspect CSV, show columns and sample",
    )
    args = parser.parse_args()

    if not args.csv_path.exists():
        print(f"Error: file not found: {args.csv_path}", file=sys.stderr)
        sys.exit(1)

    if not USERNAME or not PASSWORD:
        if not args.dry_run:
            print("Set OUTLOOK_EMAIL and OUTLOOK_PASSWORD in .env", file=sys.stderr)
            sys.exit(1)

    # Keep file open for entire iteration (row_iter reads from reader which needs open file)
    with open(args.csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        col_map, first_row = detect_columns(reader)
        if not col_map:
            print(
                "Could not detect columns. First row keys:",
                list(first_row.keys()) if first_row else "empty",
            )
            sys.exit(1)
        print(f"Detected columns: {col_map}")

        if args.dry_run:
            print("\nFirst row sample:")
            for k, v in list(first_row.items())[:5]:
                val = str(v)[:80] + "..." if len(str(v)) > 80 else str(v)
                print(f"  {k}: {val}")
            return

        sent = 0
        failed = 0
        skipped = 0
        rows_iter = iter([first_row]) if first_row else iter([])
        rows_iter = itertools.chain(rows_iter, reader)

        for i, row in enumerate(rows_iter):
            if i < args.skip:
                skipped += 1
                continue
            if sent >= args.limit:
                break

            msg = row_to_message(row, col_map, i)
            if not msg:
                continue

            if send_message(msg):
                sent += 1
                print(f"  [{sent}/{args.limit}] Sent row {i+1}")
            else:
                failed += 1

            if args.delay > 0:
                time.sleep(args.delay)

        print(f"\nDone. Sent {sent}, failed {failed}, skipped {skipped}")


if __name__ == "__main__":
    main()
