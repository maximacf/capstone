# Normalize and Classify
# Infrastructure layer: raw_message → normalized message + classification_event
# Reads raw emails, cleans/normalizes content, classifies, and stores structured rows

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

from classification import HybridClassifier, detect_urgency, html_to_text
from store_db import (
    connect,
    log_classification_event,
    source_key,
    upsert_artifact,
    upsert_automation_run,
    upsert_email_flag,
    upsert_message,
)

CLASSIFIER = HybridClassifier()
ORG_ID = os.getenv("ORG_ID", "default_org")
ENABLE_AUTOMATION_OUTPUTS = os.getenv("ENABLE_AUTOMATION_OUTPUTS", "").lower() in {
    "1",
    "true",
    "yes",
}


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_id(mailbox_id, email_id, action_type, fingerprint):
    key = f"{mailbox_id}|{email_id}|{action_type}|{fingerprint}"
    return hashlib.sha256(key.encode()).hexdigest()


def _artifact_id(run_id, artifact_type):
    return hashlib.sha256(f"{run_id}|{artifact_type}".encode()).hexdigest()


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
        SELECT r.id, r.internet_id, r.received_dt, r.from_addr, r.subject, r.body_html, r.mailbox_id
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

    for mid, iid, rdt, frm, subj, body_html, mb_id in cur.fetchall():
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

            # Enterprise automation outputs (optional)
            if ENABLE_AUTOMATION_OUTPUTS and mb_id:
                email_id = iid or mid
                action_type = "extract"
                fingerprint = hashlib.sha256(
                    f"{email_id}|{category}|{urgency}|{result.source}".encode()
                ).hexdigest()
                run_id = _run_id(mb_id, email_id, action_type, fingerprint)
                now_ts = _now_iso()

                upsert_automation_run(
                    con,
                    {
                        "run_id": run_id,
                        "org_id": ORG_ID,
                        "mailbox_id": mb_id,
                        "email_id": email_id,
                        "preference_id": None,
                        "action_type": action_type,
                        "status": "success",
                        "started_at": now_ts,
                        "finished_at": now_ts,
                        "model_name": "rules_v1",
                        "params_json": json.dumps(
                            {"category": category, "urgency": urgency}
                        ),
                        "input_fingerprint": fingerprint,
                        "error_message": None,
                    },
                )

                artifact_payload = {
                    "category": category,
                    "urgency": urgency,
                    "source": result.source,
                    "rule_name": result.detail or result.source,
                    "confidence": result.confidence,
                }
                upsert_artifact(
                    con,
                    {
                        "artifact_id": _artifact_id(run_id, "extracted_fields"),
                        "run_id": run_id,
                        "email_id": email_id,
                        "artifact_type": "extracted_fields",
                        "content_text": None,
                        "content_json": json.dumps(artifact_payload),
                        "language": None,
                        "content_ptr": None,
                    },
                )

                # Update flags if mailbox_email mapping exists
                mb_row = con.execute(
                    "SELECT mailbox_email_id FROM mailbox_email WHERE mailbox_id = ? AND email_id = ?",
                    (mb_id, email_id),
                ).fetchone()
                if mb_row:
                    upsert_email_flag(
                        con,
                        {
                            "mailbox_email_id": mb_row[0],
                            "has_summary": 0,
                            "has_translation": 0,
                            "has_extraction": 1,
                            "last_action_at": now_ts,
                            "last_action_status": "success",
                        },
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
