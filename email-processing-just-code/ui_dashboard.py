import os
from typing import Any, Dict, List

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8001")


def _get(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    resp = requests.get(f"{API_BASE}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


st.set_page_config(page_title="Adaptive Email Intelligence", layout="wide")
st.title("Adaptive Email Intelligence — Demo Dashboard")

with st.sidebar:
    st.subheader("Context")
    user_id = st.selectbox("User", ["user_1", "user_2"])
    mailbox_id = st.selectbox("Mailbox", ["me", "research_team"])
    limit = st.slider("Inbox items", 5, 50, 15)
    st.caption(f"API: {API_BASE}")


inbox = _get(
    f"/mailbox/{mailbox_id}/inbox",
    params={"limit": limit},
)
items: List[Dict[str, Any]] = inbox.get("items", [])

st.subheader("Inbox")
cols = st.columns([3, 2, 2, 2])
cols[0].write("Subject")
cols[1].write("From")
cols[2].write("Received")
cols[3].write("Badges")

selected_email = None
for row in items:
    cols = st.columns([3, 2, 2, 2])
    subject = row.get("subject") or "(no subject)"
    if cols[0].button(subject, key=f"email-{row.get('email_id')}"):
        selected_email = row
    cols[1].write(row.get("from_addr") or "-")
    cols[2].write(row.get("received_at") or "-")
    badges = []
    if row.get("has_summary"):
        badges.append("Summary")
    if row.get("has_draft_reply"):
        badges.append("Draft Reply")
    if row.get("has_translation"):
        badges.append("Translation")
    if row.get("has_extraction"):
        badges.append("Extracted")
    cols[3].write(", ".join(badges) if badges else "-")

st.divider()
st.subheader("Email Artifacts")
if not selected_email and items:
    selected_email = items[0]

if selected_email:
    st.write(
        f"Selected: `{selected_email.get('email_id')}` • "
        f"{selected_email.get('subject') or '(no subject)'}"
    )
    artifacts = _get(
        f"/mailbox/{mailbox_id}/email/{selected_email.get('email_id')}/artifacts",
    ).get("items", [])
    if not artifacts:
        st.info("No artifacts yet.")
    else:
        for art in artifacts:
            st.markdown(f"**{art.get('artifact_type')}** • {art.get('created_at')}")
            if art.get("content_text"):
                st.write(art.get("content_text"))
            elif art.get("content_json"):
                st.json(art.get("content_json"))
            st.caption(f"run_id: {art.get('run_id')} • status: {art.get('run_status')}")
            st.divider()
else:
    st.info("No inbox items found.")
