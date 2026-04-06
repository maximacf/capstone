#!/usr/bin/env python3
"""
Verify Reproducibility: Export a snapshot of classification labels and artifact state
for the enron_import mailbox. Run before and after a pipeline re-run; if outputs match,
reproducibility holds.

Usage:
  export DATABASE_URL="postgresql://postgres:mypassword123@localhost:5432/maildb"
  1. python verify_reproducibility.py --mailbox enron_import -o snapshot_before.json
  2. (optional) Trigger pipeline/automate via UI or: curl -X POST http://localhost:8001/api/pipeline/automate -H "Content-Type: application/json" -d '{"mailbox_id":"enron_import","user_id":"user_1","org_id":"org_1","classify_all":true}'
  3. python verify_reproducibility.py --mailbox enron_import -o snapshot_after.json
  4. diff snapshot_before.json snapshot_after.json
     (should be identical if reproducibility holds)
"""
import argparse
import hashlib
import json
import os
import sys

# Add email-processing-just-code to path
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "email-processing-just-code")
)
os.chdir(os.path.join(os.path.dirname(__file__), "email-processing-just-code"))

from database import get_session_connection, init_db
from store_db import SessionConnection


def get_snapshot(mailbox_id: str = "enron_import") -> dict:
    init_db()
    con = SessionConnection(get_session_connection())

    # 1. Classification: email_id -> category (COALESCE manual, auto)
    rows = con.execute(
        """
        SELECT e.email_id, COALESCE(m.manual_category, m.category) AS cat
        FROM mailbox_email me
        JOIN email e ON e.email_id = me.email_id
        LEFT JOIN message m ON m.id = e.provider_msg_id
        WHERE me.mailbox_id = ?
        ORDER BY e.email_id
        """,
        (mailbox_id,),
    ).fetchall()

    classifications = {r[0]: r[1] for r in rows}

    # 2. Artifacts: from artifact table, joined to automation_run for mailbox scope
    ar_rows = con.execute(
        """
        SELECT a.email_id, a.artifact_type, a.content_text, a.content_json
        FROM artifact a
        JOIN automation_run ar ON ar.run_id = a.run_id
        WHERE ar.mailbox_id = ? AND ar.status = 'success'
        ORDER BY a.email_id, a.artifact_type
        """,
        (mailbox_id,),
    ).fetchall()

    artifacts_by_email = {}
    for r in ar_rows:
        eid, atype, ctext, cjson = r[0], r[1], r[2], r[3]
        if eid not in artifacts_by_email:
            artifacts_by_email[eid] = []
        content = str(ctext or "") + str(cjson or "")
        content_hash = hashlib.sha256(content.encode(errors="replace")).hexdigest()[:16]
        artifacts_by_email[eid].append({"type": atype, "hash": content_hash})

    # Build deterministic snapshot for diffing
    snapshot = {
        "mailbox_id": mailbox_id,
        "classification_count": len(classifications),
        "classifications_sorted": sorted(classifications.items()),
        "artifact_count": sum(len(v) for v in artifacts_by_email.values()),
        "artifacts_by_email": {
            k: sorted(v, key=lambda x: x["type"])
            for k, v in sorted(artifacts_by_email.items())
        },
        "fingerprint": hashlib.sha256(
            json.dumps(
                {"c": classifications, "a": artifacts_by_email},
                sort_keys=True,
            ).encode()
        ).hexdigest()[:32],
    }
    return snapshot


def main():
    ap = argparse.ArgumentParser(description="Export reproducibility snapshot")
    ap.add_argument("--mailbox", default="enron_import", help="Mailbox ID")
    ap.add_argument("-o", "--output", help="Write snapshot to JSON file")
    args = ap.parse_args()

    snapshot = get_snapshot(args.mailbox)
    out = json.dumps(snapshot, indent=2, sort_keys=True)

    if args.output:
        with open(args.output, "w") as f:
            f.write(out)
        print(f"Snapshot written to {args.output}")
        print(f"Fingerprint: {snapshot['fingerprint']}")
        print(
            f"Classifications: {snapshot['classification_count']}, Artifacts: {snapshot['artifact_count']}"
        )
    else:
        print(out)


if __name__ == "__main__":
    main()
