from dotenv import load_dotenv
import os, smtplib, imaplib

load_dotenv()
USER = os.getenv("MAIL_USER")
PASS = os.getenv("MAIL_PASS")
IMAP_HOST = os.getenv("IMAP_HOST")
SMTP_HOST = os.getenv("SMTP_HOST")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

print("USER repr:", repr(USER))
print("PASS length:", len(PASS) if PASS else 0)

# quick IMAP login attempt (no headers, just status)
try:
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as M:
        typ, _ = M.login(USER, PASS)
        print("IMAP:", typ)
except imaplib.IMAP4.error as e:
    print("IMAP error:", e)

# quick SMTP login attempt
try:
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as S:
        S.ehlo(); S.starttls(); S.login(USER, PASS)
        print("SMTP: OK")
except smtplib.SMTPAuthenticationError as e:
    print("SMTP auth error:", e.smtp_code, e.smtp_error)
except Exception as e:
    print("SMTP error:", e)
