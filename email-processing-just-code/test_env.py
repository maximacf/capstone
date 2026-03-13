import os

from dotenv import load_dotenv

load_dotenv()
print("Email user:", os.getenv("MAIL_USER"))
print("IMAP host:", os.getenv("IMAP_HOST"))
