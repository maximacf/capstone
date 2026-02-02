# INGESTION
# Graph fetcher to load real emails into raw messages
# Infrastructure layer: Graph API → raw_message + mailbox_emails tables

import json
import os
import sys

import msal
import requests
from store_db import connect, upsert_mailbox_email, upsert_raw_message

CLIENT_ID = os.getenv("CLIENT_ID", "32388b43-8fc8-443b-b36d-365f3b418a20")
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Mail.Read"]
GRAPH = "https://graph.microsoft.com/v1.0"


def get_token():
    """Acquire OAuth token via device flow. Prints auth instructions to stderr."""
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError("Device flow failed")
    print("\n Sign in:  Microsoft", file=sys.stderr)
    print(
        "URL :",
        flow.get("verification_uri") or flow.get("verification_uri_complete"),
        file=sys.stderr,
    )
    print("CODE:", flow["user_code"], file=sys.stderr)
    print("................................\n", file=sys.stderr)
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description"))
    return result["access_token"]


def fetch_messages(token, mailbox_id, pages=1, top=100):
    """Generator: fetch messages from Graph API for given mailbox."""
    select = "$select=id,internetMessageId,receivedDateTime,from,subject,body"
    order = "$orderby=receivedDateTime desc"
    base = f"{GRAPH}/me" if mailbox_id == "me" else f"{GRAPH}/users/{mailbox_id}"
    url = f"{base}/messages?{select}&{order}&$top={top}"
    headers = {"Authorization": f"Bearer {token}"}
    while url and pages > 0:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        for m in data.get("value", []):
            yield m
        url = data.get("@odata.nextLink")
        pages -= 1


def ingest_graph_messages(mailbox_id, mailbox_type, pages=1, top=100, dry_run=False):
    """
    Ingest messages from Microsoft Graph into raw_message and mailbox_emails tables.

    Args:
        mailbox_id: "me" or email address like "sharedbox@company.com"
        mailbox_type: "personal" or "shared"
        pages: Number of pages to fetch (default 1)
        top: Messages per page (default 100)
        dry_run: If True, fetch but don't write to DB

    Returns:
        dict: JSON-serializable summary with counts, last_received_dt, etc.
    """
    token = get_token()

    if dry_run:
        con = None
    else:
        con = connect()

    ingested_count = 0
    last_received_dt = None
    first_received_dt = None

    for m in fetch_messages(token, mailbox_id, pages=pages, top=top):
        raw_id = m["id"]
        internet_id = m.get("internetMessageId")
        received_dt = m.get("receivedDateTime")

        if not dry_run:
            upsert_raw_message(
                con,
                {
                    "id": raw_id,
                    "internet_id": internet_id,
                    "received_dt": received_dt,
                    "from_addr": (m.get("from") or {})
                    .get("emailAddress", {})
                    .get("address"),
                    "subject": m.get("subject"),
                    "body_html": (m.get("body") or {}).get("content"),
                    "body_type": (m.get("body") or {})
                    .get("contentType", "html")
                    .lower(),
                    "json_path": None,
                    "mailbox_id": mailbox_id,
                    "mailbox_type": mailbox_type,
                },
            )

            # Fix: create mailbox_email entry for EACH message (not just the last one)
            canonical_key = internet_id or raw_id
            upsert_mailbox_email(
                con,
                {
                    "mailbox_id": mailbox_id,
                    "mailbox_type": mailbox_type,
                    "canonical_key": canonical_key,
                    "raw_id": raw_id,
                },
            )

        ingested_count += 1
        if received_dt:
            if not first_received_dt or received_dt < first_received_dt:
                first_received_dt = received_dt
            if not last_received_dt or received_dt > last_received_dt:
                last_received_dt = received_dt

    return {
        "status": "success",
        "dry_run": dry_run,
        "mailbox_id": mailbox_id,
        "mailbox_type": mailbox_type,
        "ingested_count": ingested_count,
        "first_received_dt": first_received_dt,
        "last_received_dt": last_received_dt,
    }


def main():
    """Legacy main() for backward compatibility. Use ingest_graph_messages() directly."""
    import argparse

    parser = argparse.ArgumentParser(description="Ingest emails from Microsoft Graph")
    parser.add_argument(
        "--mailbox-id",
        default=os.getenv("MAILBOX_ID", "me"),
        help="Mailbox ID: 'me' or email address",
    )
    parser.add_argument(
        "--mailbox-type",
        default=os.getenv("MAILBOX_TYPE", "personal"),
        choices=["personal", "shared"],
        help="Mailbox type",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=int(os.getenv("PAGES", "2")),
        help="Number of pages to fetch",
    )
    parser.add_argument("--top", type=int, default=100, help="Messages per page")
    parser.add_argument(
        "--dry-run", action="store_true", help="Fetch but don't write to DB"
    )
    parser.add_argument(
        "--legacy", action="store_true", help="Use legacy print-based output"
    )

    args = parser.parse_args()

    result = ingest_graph_messages(
        mailbox_id=args.mailbox_id,
        mailbox_type=args.mailbox_type,
        pages=args.pages,
        top=args.top,
        dry_run=args.dry_run,
    )

    if args.legacy:
        print("Raw ingest complete.", file=sys.stderr)
    else:
        # JSON output for n8n orchestration
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
