# Sending ENRON Emails to Your Outlook Inbox

Populate your Outlook inbox with diverse emails from the ENRON dataset so you can ingest them into Mailgine for evaluation.

---

## 1. Download ENRON Dataset

**Kaggle (emails.csv)**
1. Go to [Kaggle – Enron Email Dataset](https://www.kaggle.com/datasets/wcukierski/enron-email-dataset)
2. Download `emails.csv` (～1.4 GB)
3. Use `send_enron_csv_to_outlook.py` (below)

**If you have .eml files instead**
- Use `send_enron_to_outlook.py` with a folder of `.eml` files

---

## 2. Office 365 SMTP Setup

Office 365 requires an **app password** when using SMTP with 2FA.

1. Create an app password: Microsoft 365 → Security → App passwords
2. Put credentials in `.env` in `email-processing-just-code/`:

```
OUTLOOK_EMAIL=your-email@outlook.com
OUTLOOK_PASSWORD=your-app-password
```

Or use regular password if 2FA is disabled.

---

## 3. Run the Script

**For emails.csv:**
```bash
cd email-processing-just-code

# Dry run (inspect CSV structure)
python send_enron_csv_to_outlook.py /path/to/emails.csv --dry-run

# Send 100 emails (default), 2 sec delay
python send_enron_csv_to_outlook.py /path/to/emails.csv

# Send 200 emails, 3 sec delay
python send_enron_csv_to_outlook.py /path/to/emails.csv --limit 200 --delay 3
```

**For .eml files:**
```bash
python send_enron_to_outlook.py /path/to/eml/folder --limit 100
```

---

## 4. Ingest into Mailgine

After emails arrive in your Outlook inbox (may take a few minutes):

1. Open Mailgine Dashboard
2. Choose mailbox **me** and suitable **Pages** / **Per page**
3. Click **Ingest emails**

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Authentication failed" | Use app password, not normal password, if 2FA is on |
| "Relay access denied" | Ensure you are sending TO your own address |
| Throttling / too many sends | Increase `--delay` (e.g. 3 or 5) |
| No .eml files found | Check dataset structure; some ENRON versions use different formats |
