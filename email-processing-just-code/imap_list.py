# imap_list.py — list the latest 5 emails (headers only)

import email
import imaplib
import os
from email.header import decode_header

from dotenv import load_dotenv

load_dotenv()
IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
USER = os.getenv("MAIL_USER")
PASS = os.getenv("MAIL_PASS")


def _dec(s):
    if not s:
        return ""
    parts = decode_header(s)
    out = []
    for text, enc in parts:
        out.append(
            text.decode(enc or "utf-8", "replace") if isinstance(text, bytes) else text
        )
    return "".join(out)


with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as M:
    M.login(USER, PASS)
    M.select("INBOX", readonly=True)
    typ, data = M.search(None, "ALL")
    ids = data[0].split()
    if not ids:
        print("No messages in INBOX yet.")
    else:
        for i in reversed(ids[-5:]):
            typ, msg_data = M.fetch(i, "(RFC822.HEADER)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            print(
                f"From: {_dec(msg.get('From'))}\nSubject: {_dec(msg.get('Subject'))}\nDate: {msg.get('Date')}\n---"
            )
