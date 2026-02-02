# For Attachtments
# fetch_attachments.py
import os, base64, requests, msal
from pathlib import Path
from store_db import connect, upsert_attachment

CLIENT_ID = os.getenv("CLIENT_ID", "32388b43-8fc8-443b-b36d-365f3b418a20")
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Mail.Read"]
GRAPH = "https://graph.microsoft.com/v1.0"

ATT_DIR = Path("data/attachments")

def get_token():
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise SystemExit("Device flow failed.")
    print("URL : https://microsoft.com/devicelogin")
    print("CODE:", flow["user_code"])
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise SystemExit(result)
    return result["access_token"]

def list_messages_without_attachments(con):
    # simple: process all messages; Graph tells us if they have attachments
    rows = con.execute("SELECT id, subject FROM message ORDER BY received_dt DESC").fetchall()
    return rows

def fetch_and_save_for_message(con, token, msg_id):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH}/me/messages/{msg_id}/attachments?$top=50"
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        for a in data.get("value", []):
            atype = a.get("@odata.type", "")
            aid   = a.get("id")
            name  = a.get("name") or "unnamed"
            ctype = a.get("contentType") or "application/octet-stream"

            # handle only FileAttachment v1 (skip ItemAttachment for now)
            if "fileAttachment" in atype.lower():
                content_b64 = a.get("contentBytes")
                if not content_b64:
                    # skip weird/large cases for v1
                    print(f"  - skip (no contentBytes): {name}")
                    continue
                ATT_DIR.mkdir(parents=True, exist_ok=True)
                safe = name.replace("/", "_")
                path = ATT_DIR / f"{msg_id}_{safe}"
                data_bytes = base64.b64decode(content_b64)
                path.write_bytes(data_bytes)
                size = path.stat().st_size

                upsert_attachment(con, {
                    "id": aid,
                    "message_id": msg_id,
                    "name": name,
                    "content_type": ctype,
                    "size_bytes": size,
                    "path": path.as_posix(),
                })
                print(f"  - saved {name} ({size} bytes)")
            else:
                print(f"  - skip (non-file attachment): {name} [{atype}]")

        url = data.get("@odata.nextLink")

def main():
    token = get_token()
    con = connect()
    msgs = list_messages_without_attachments(con)
    print(f"Checking attachments for {len(msgs)} messages...")
    for msg_id, subj in msgs:
        print(f"* {subj[:60]}")
        try:
            fetch_and_save_for_message(con, token, msg_id)
        except requests.HTTPError as e:
            print("  ! HTTP error:", e)

if __name__ == "__main__":
    main()

