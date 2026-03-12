# Demo: Shared Mailbox Reuse

This demo proves the shared mailbox boundary:
one email appears in two mailboxes, automation is mailbox-scoped, and a shared
mailbox summary is reused (idempotent).

## 1) Choose an existing message_id

Pick one message_id from your DB:
```
sqlite3 "email-processing/data/mail.db" "SELECT id FROM message ORDER BY received_dt DESC LIMIT 1;"
```
Copy the id and use it below as `MSG_ID`.

## 2) Map the email into a shared mailbox

```
curl -X POST http://127.0.0.1:8001/mailbox/map \
  -H "Content-Type: application/json" \
  -d '{
    "mailbox_id":"research_team",
    "org_id":"org_1",
    "mailbox_type":"shared_team",
    "message_id":"MSG_ID",
    "db_path":"/Users/ifc/SynologyDrive/Year 5/Thesis/Data/email-processing/data/mail.db"
  }'
```

Optionally also map the same email to the personal mailbox:
```
curl -X POST http://127.0.0.1:8001/mailbox/map \
  -H "Content-Type: application/json" \
  -d '{
    "mailbox_id":"me",
    "org_id":"org_1",
    "mailbox_type":"personal",
    "message_id":"MSG_ID",
    "db_path":"/Users/ifc/SynologyDrive/Year 5/Thesis/Data/email-processing/data/mail.db"
  }'
```

## 3) User A runs automation on the shared mailbox

```
curl -X POST http://127.0.0.1:8001/pipeline/automate \
  -H "Content-Type: application/json" \
  -d '{"mailbox_id":"research_team","user_id":"user_1","org_id":"org_1","limit":5,"classify_all":true,"update_message_category":true,"db_path":"/Users/ifc/SynologyDrive/Year 5/Thesis/Data/email-processing/data/mail.db"}'
```

## 4) User B runs automation on the shared mailbox (idempotent)

```
curl -X POST http://127.0.0.1:8001/pipeline/automate \
  -H "Content-Type: application/json" \
  -d '{"mailbox_id":"research_team","user_id":"user_2","org_id":"org_1","limit":5,"classify_all":true,"update_message_category":true,"db_path":"/Users/ifc/SynologyDrive/Year 5/Thesis/Data/email-processing/data/mail.db"}'
```

You should see `duplicate` or already-processed statuses for the same email,
because idempotency is scoped to `(mailbox_id, email_id, action_type, input_fingerprint)`.

## 5) Verify inbox badges

```
curl "http://127.0.0.1:8001/mailbox/research_team/inbox?limit=10&db_path=/Users/ifc/SynologyDrive/Year%205/Thesis/Data/email-processing/data/mail.db"
```

Look for `has_summary = 1` and `last_action_status = success`.
