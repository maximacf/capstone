"""Re-classify all enron_import emails using LLM with the 7 consolidated categories."""

import json
import os
import sys
import time

import requests

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:mypassword123@localhost:5432/maildb"
)
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

CATEGORIES = {
    "Research": "Formal research reports, analyst notes, market analysis publications",
    "Financial": "Financial transactions, contracts, deals, trades, pricing, buyouts, invoices",
    "General": "Scheduling, general updates, FYI, greetings, courtesy replies, meeting coordination",
    "Internal": "Company-internal operations, HR, IT, approvals, processes, staffing",
    "External": "Communication with outside parties, clients, vendors, partners",
    "Materials": "Documents, attachments, reference files, slide decks, spreadsheets",
    "Other": "Personal emails, spam, or anything not fitting above categories",
}

SYSTEM_PROMPT = (
    "You classify emails into exactly one category. "
    'Return JSON only: {"label":"...", "confidence":0.0-1.0}. '
    "Pick the single best category based on the PRIMARY purpose of the email.\n\n"
    "Categories:\n"
    + "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items())
    + "\n\nClassify based on what the email is primarily about, not just keywords."
)


def classify_one(from_addr, subject, body_text):
    user_prompt = (
        f"From: {from_addr or 'unknown'}\n"
        f"Subject: {subject or '(no subject)'}\n"
        f"Body:\n{(body_text or '')[:3000]}"
    )
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    parsed = json.loads(data["choices"][0]["message"]["content"])
    label = parsed.get("label", "Other").strip()
    if label not in CATEGORIES:
        label = "Other"
    return label, parsed.get("confidence", 0.0)


def main():
    from store_db import connect

    os.environ["DATABASE_URL"] = DATABASE_URL
    con = connect()

    rows = con.execute(
        """
        SELECT m.id, m.subject, m.from_addr, m.body_text, m.category
        FROM message m
        JOIN email e ON e.provider_msg_id = m.id
        JOIN mailbox_email me ON me.email_id = e.email_id
        WHERE me.mailbox_id = ?
        ORDER BY m.id
        """,
        ("enron_import",),
    ).fetchall()

    total = len(rows)
    changed = 0
    errors = 0
    print(f"Re-classifying {total} emails with LLM...")

    for i, row in enumerate(rows):
        msg_id, subject, from_addr, body_text, old_cat = row
        try:
            new_label, confidence = classify_one(from_addr, subject, body_text)
            if new_label != old_cat:
                con.execute(
                    "UPDATE message SET category = ? WHERE id = ?",
                    (new_label, msg_id),
                )
                changed += 1
            if (i + 1) % 25 == 0:
                con.commit()
                print(f"  [{i+1}/{total}] changed={changed} errors={errors}")
        except Exception as e:
            errors += 1
            print(f"  ERROR on {msg_id}: {e}", file=sys.stderr)
            time.sleep(2)

    con.commit()
    print(f"\nDone: {total} emails, {changed} changed, {errors} errors")


if __name__ == "__main__":
    main()
