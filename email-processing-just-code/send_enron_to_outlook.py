#!/usr/bin/env python3
"""
Send ENRON .eml files to your Outlook mailbox via Office 365 SMTP.

This populates your Inbox with diverse emails so you can then ingest them
into Mailgine via the existing Graph API pipeline.

Prerequisites:
  1. Download the ENRON dataset from Kaggle (e.g. wcukierski/enron-email-dataset)
  2. Extract to a folder of .eml files
  3. Set env vars or .env: OUTLOOK_EMAIL, OUTLOOK_PASSWORD (or app password)

Office 365 SMTP requires sending FROM your authenticated account.
We forward each email: original content is preserved in body/subject.
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
USERNAME = os.getenv("OUTLOOK_EMAIL") or os.getenv("SMTP_USERNAME")
PASSWORD = os.getenv("OUTLOOK_PASSWORD") or os.getenv("SMTP_PASSWORD")


def collect_eml_files(directory: Path, limit: int | None) -> list[Path]:
    """Recursively find .eml files, return up to `limit`."""
    files: list[Path] = []
    for path in directory.rglob("*.eml"):
        if path.is_file():
            files.append(path)
        if limit and len(files) >= limit:
            break
    return files[:limit] if limit else files


def send_eml_to_self(eml_path: Path, delay_seconds: float = 1.0) -> bool:
    """Send one .eml file to our own Outlook inbox. Returns True on success."""
    import smtplib
    from email import policy
    from email.parser import BytesParser

    if not USERNAME or not PASSWORD:
        raise RuntimeError(
            "Set OUTLOOK_EMAIL and OUTLOOK_PASSWORD (or SMTP_USERNAME/SMTP_PASSWORD) in .env"
        )

    with open(eml_path, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)

    # Office 365 requires envelope FROM = authenticated user.
    # We send to self; original From/Subject/Body are in the message.
    to_addr = USERNAME
    from_addr = USERNAME

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(USERNAME, PASSWORD)
            server.sendmail(
                from_addr=from_addr,
                to_addrs=[to_addr],
                msg=msg.as_bytes(),
            )
    except Exception as e:
        print(f"  FAIL {eml_path.name}: {e}", file=sys.stderr)
        return False

    if delay_seconds > 0:
        time.sleep(delay_seconds)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Send ENRON .eml files to your Outlook inbox for Mailgine ingestion"
    )
    parser.add_argument(
        "eml_dir",
        type=Path,
        help="Directory containing .eml files (searched recursively)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max number of emails to send (default 100)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds between sends to avoid throttling (default 2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list files, don't send",
    )
    args = parser.parse_args()

    if not args.eml_dir.exists():
        print(f"Error: directory not found: {args.eml_dir}", file=sys.stderr)
        sys.exit(1)

    files = collect_eml_files(args.eml_dir, args.limit)
    print(f"Found {len(files)} .eml files")

    if not files:
        print(
            "No .eml files found. Download ENRON from Kaggle and extract to a folder.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.dry_run:
        for p in files[:10]:
            print(f"  {p}")
        if len(files) > 10:
            print(f"  ... and {len(files) - 10} more")
        return

    if not USERNAME or not PASSWORD:
        print(
            "Set OUTLOOK_EMAIL and OUTLOOK_PASSWORD in .env or environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    ok = 0
    fail = 0
    for i, path in enumerate(files):
        if send_eml_to_self(path, args.delay):
            ok += 1
            print(f"  [{i+1}/{len(files)}] Sent: {path.name}")
        else:
            fail += 1

    print(f"\nDone. Sent {ok}, failed {fail}")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
