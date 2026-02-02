# graph_list_inbox.py
# Log in with Microsoft device code + list 5 newest Outlook emails using Graph API

import msal
import requests

CLIENT_ID = "32388b43-8fc8-443b-b36d-365f3b418a20"  #  Client ID of my Azure App 
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Mail.Read"] # from Azure

def get_token():
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise ValueError("Failed to start.")
    print(f"\nGo to {flow['verification_uri']} and enter the code: {flow['user_code']}\n")
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        print("Login successful")
        return result["access_token"]
    else:
        raise ValueError("Login failed:", result)

def list_messages(token):
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?$top=5"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print("Error:", r.status_code, r.text)
        return
    data = r.json()
    for msg in data.get("value", []):
        print(f"From: {msg['from']['emailAddress']['address']}")
        print(f"Subject: {msg['subject']}")
        print(f"Received: {msg['receivedDateTime']}")
        print("-" * 40)

if __name__ == "__main__":
    token = get_token()
    list_messages(token)
