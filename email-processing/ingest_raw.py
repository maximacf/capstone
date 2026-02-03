# INGESTION
# Graph fetcher to load real emails into raw messages
# Infrastructure layer: Graph API → raw_message + mailbox_emails tables

import json
import os
import sys

import msal
import requests
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

CLIENT_ID = os.getenv("CLIENT_ID", "32388b43-8fc8-443b-b36d-365f3b418a20")
TENANT_ID = os.getenv("TENANT_ID", "common")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["Mail.Read"]
GRAPH = "https://graph.microsoft.com/v1.0"
ORG_ID = os.getenv("ORG_ID", "default_org")
OWNER_USER_ID = os.getenv("OWNER_USER_ID")
MAILBOX_NAME = os.getenv("MAILBOX_NAME")

CACHE_PATH = os.getenv(
    "MSAL_CACHE_PATH", os.path.expanduser("~/.msal_token_cache.json")
)


def load_cache():
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            cache.deserialize(fh.read())
    return cache


def save_cache(cache):
    if cache.has_state_changed:
        with open(CACHE_PATH, "w", encoding="utf-8") as fh:
            fh.write(cache.serialize())


def get_token():
    """Acquire OAuth token via device flow with a persistent MSAL cache."""
    cache = load_cache()
    app = msal.PublicClientApplication(
        CLIENT_ID, authority=AUTHORITY, token_cache=cache
    )

    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Failed to create device flow: {flow}")
        print(flow["message"], flush=True, file=sys.stderr)
        result = app.acquire_token_by_device_flow(flow)

    save_cache(cache)

    if "access_token" not in result:
        raise RuntimeError(f"Auth failed: {result}")
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
        # Enterprise model: ensure org + mailbox exist
        mailbox_type_mapped = "shared_team" if mailbox_type == "shared" else "personal"
        ensure_organization(con, ORG_ID)
        ensure_mailbox(
            con,
            mailbox_id=mailbox_id,
            org_id=ORG_ID,
            mailbox_type=mailbox_type_mapped,
            owner_user_id=OWNER_USER_ID if mailbox_type_mapped == "personal" else None,
            name=MAILBOX_NAME or mailbox_id,
        )

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

            # Enterprise model: canonical email + mailbox mapping
            upsert_email(
                con,
                {
                    "email_id": canonical_key,
                    "org_id": ORG_ID,
                    "provider_msg_id": raw_id,
                    "thread_id": None,
                    "from_addr": (m.get("from") or {})
                    .get("emailAddress", {})
                    .get("address"),
                    "to_addrs": None,
                    "cc_addrs": None,
                    "subject": m.get("subject"),
                    "received_at": received_dt,
                    "body_text": None,
                    "body_html": (m.get("body") or {}).get("content"),
                    "raw_mime_ptr": None,
                    "content_hash": source_key(
                        m.get("subject"),
                        (m.get("from") or {}).get("emailAddress", {}).get("address"),
                        received_dt,
                    ),
                },
            )
            upsert_mailbox_email_map(
                con,
                {
                    "mailbox_id": mailbox_id,
                    "email_id": canonical_key,
                    "delivered_at": received_dt,
                    "labels_json": None,
                    "read_state": None,
                    "archived_state": None,
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
