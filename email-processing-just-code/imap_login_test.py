import imaplib
import os

from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("IMAP_HOST")
PORT = int(os.getenv("IMAP_PORT", "993"))
USER = os.getenv("MAIL_USER")
PASS = os.getenv("MAIL_PASS")

print("Host:", HOST, "Port:", PORT)
print("User:", USER)

try:
    with imaplib.IMAP4_SSL(HOST, PORT) as M:
        typ, _ = M.login(USER, PASS)
        print("LOGIN status:", typ)
        M.logout()
except imaplib.IMAP4.error as e:
    print("IMAP error:", e)
