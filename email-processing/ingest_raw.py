


# INGESTION

# Graph fatcher to load real emails into raw messages

import os, requests, msal
from store_db import connect, upsert_raw_message, upsert_mailbox_email

#NEW SINCE THE SHARED vs PE§RSONAL IMPLEMENTATION: 
MAILBOX_ID = os.getenv("MAILBOX_ID", "me")  # "me" or an email like sharedbox@company.com
# USE MAILBOX_ID="shared_demo" AND MAILBOX_TYPE="shared" FOR SIMULATION 
MAILBOX_TYPE = os.getenv("MAILBOX_TYPE", "personal")  # personal|shared


CLIENT_ID = os.getenv("CLIENT_ID", "32388b43-8fc8-443b-b36d-365f3b418a20")  # your app id
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Mail.Read"]
GRAPH = "https://graph.microsoft.com/v1.0"

def get_token():
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError("Device flow failed")
    print("\n Sign in:  Microsoft")
    print("URL :", flow.get("verification_uri") or flow.get("verification_uri_complete"))
    print("CODE:", flow["user_code"])
    print("................................\n")
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description"))
    return result["access_token"]

def fetch_messages(token, pages=1, top=100):
    select = "$select=id,internetMessageId,receivedDateTime,from,subject,body"
    order = "$orderby=receivedDateTime desc"
    #BEFORE:
    #url = f"{GRAPH}/me/messages?{select}&{order}&$top={top}"
    #NEW
    base = f"{GRAPH}/me" if MAILBOX_ID == "me" else f"{GRAPH}/users/{MAILBOX_ID}"
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

def main():
    token = get_token()
    con = connect()
    pages = int(os.getenv("PAGES", "2"))  # ~200 messages by default
    for m in fetch_messages(token, pages=pages):
        raw_id = m["id"]
        internet_id = m.get("internetMessageId")

        upsert_raw_message(con, {
            "id": raw_id,
            "internet_id": internet_id,
            "received_dt": m.get("receivedDateTime"),
            "from_addr": (m.get("from") or {}).get("emailAddress", {}).get("address"),
            "subject": m.get("subject"),
            "body_html": (m.get("body") or {}).get("content"),
            "body_type": (m.get("body") or {}).get("contentType","html").lower(),
            "json_path": None,

            # NEW:
            "mailbox_id": MAILBOX_ID,
            "mailbox_type": MAILBOX_TYPE,
        })

    canonical_key = internet_id or raw_id  # prefer RFC Message-ID, fallback to Graph id

    upsert_mailbox_email(con, {
        "mailbox_id": MAILBOX_ID,
        "mailbox_type": MAILBOX_TYPE,
        "canonical_key": canonical_key,
        "raw_id": raw_id,
    })

    print("Raw ingest complete.")

if __name__ == "__main__":
    main()
