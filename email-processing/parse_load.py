# Normalize and Classify
# Infrastructure layer: raw_message → normalized message + classification_event
# Reads raw emails, cleans/normalizes content, classifies, and stores structured rows

import json
import os
import sys

from classification import HybridClassifier, detect_urgency, html_to_text
from store_db import (connect, log_classification_event, source_key,
                      upsert_message)

CLASSIFIER = HybridClassifier()


def process_new_raw_messages(limit=None, mailbox_id=None, dry_run=False):
    """
    Process new raw emails (ones not yet in the message table).

    Args:
        limit: Maximum number of messages to process (None = all)
        mailbox_id: Filter by mailbox_id (None = all mailboxes)
        dry_run: If True, classify but don't write to DB

    Returns:
        dict: JSON-serializable summary with counts by category, urgency, etc.
    """
    con = connect()
    cur = con.cursor()

    # Build query with optional mailbox filter
    query = """
        SELECT r.id, r.internet_id, r.received_dt, r.from_addr, r.subject, r.body_html
        FROM raw_message r
        LEFT JOIN message m ON m.id = r.id
        WHERE m.id IS NULL
    """
    params = []

    if mailbox_id:
        query += " AND r.mailbox_id = ?"
        params.append(mailbox_id)

    query += " ORDER BY r.received_dt DESC"

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    cur.execute(query, params)

    processed_count = 0
    category_counts = {}
    urgency_counts = {}
    source_counts = {}

    for mid, iid, rdt, frm, subj, body_html in cur.fetchall():
        body_text = html_to_text(body_html)
        result = CLASSIFIER.classify(subj or "", body_text, frm)
        category = result.label
        domain = (frm.split("@", 1)[1].lower()) if frm and "@" in frm else None
        urgency = detect_urgency(subj, body_text)

        if not dry_run:
            upsert_message(
                con,
                {
                    "id": mid,
                    "internet_id": iid,
                    "received_dt": rdt,
                    "from_addr": frm,
                    "subject": subj,
                    "body_text": body_text,
                    "body_html": body_html,
                    "category": category,
                    "source_hash": source_key(subj, frm, rdt),
                    "manual_category": None,
                    "from_domain": domain,
                    "urgency": urgency,
                    "language": None,
                    "has_attachment": 0,
                    "thread_id": None,
                    "to_addresses": None,
                    "cc_addresses": None,
                    "entities": None,
                },
            )

            log_classification_event(
                con,
                message_id=mid,
                category_auto=category,
                rule_name=result.detail or result.source,
                confidence=result.confidence,
            )

        processed_count += 1
        category_counts[category] = category_counts.get(category, 0) + 1
        urgency_counts[urgency] = urgency_counts.get(urgency, 0) + 1
        source_counts[result.source] = source_counts.get(result.source, 0) + 1

    return {
        "status": "success",
        "dry_run": dry_run,
        "mailbox_id": mailbox_id,
        "processed_count": processed_count,
        "category_counts": category_counts,
        "urgency_counts": urgency_counts,
        "source_counts": source_counts,
    }


def main():
    """CLI entrypoint. Use process_new_raw_messages() directly for programmatic access."""
    import argparse

    parser = argparse.ArgumentParser(description="Process and classify raw emails")
    parser.add_argument(
        "--limit", type=int, default=None, help="Maximum number of messages to process"
    )
    parser.add_argument(
        "--mailbox-id",
        default=None,
        help="Filter by mailbox_id (default: all mailboxes)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Classify but don't write to DB"
    )
    parser.add_argument(
        "--legacy", action="store_true", help="Use legacy print-based output"
    )

    args = parser.parse_args()

    result = process_new_raw_messages(
        limit=args.limit, mailbox_id=args.mailbox_id, dry_run=args.dry_run
    )

    if args.legacy:
        print("Parse + load done.", file=sys.stderr)
    else:
        # JSON output for n8n orchestration
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
