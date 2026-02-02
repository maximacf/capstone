## File: `email-processing/N8N_STEP3_ORCHESTRATION.md`

Enterprise-grade **n8n orchestration design** for the current Python + SQLite foundation.

### Boundary compliance

- **Python owns**: ingestion (`ingest_raw.py`), parsing/normalization (`parse_load.py`), canonical DB writes.
- **n8n owns**: orchestration lifecycle, idempotency checks, retries, error handling, LLM calls.
- **Canonical email content is never overwritten**: `raw_message.body_html` remains immutable. n8n only updates *derived state* flags (`mailbox_emails.seen/processed`) and optionally updates derived labels in `message` (see LLM branch).

---

## Workflow A — Ingest → Parse (rules-only) → Mark processed

### Node A0 — Trigger (Cron / Manual)
- **Type**: Cron (e.g. every 5 min) OR Manual Trigger

### Node A1 — Set config
- **Type**: Set
- **Fields**:
  - `db_path`: `/absolute/path/to/email-processing/data/mail.db` (or leave empty and rely on `DB_PATH` env)
  - `mailbox_id`: `"me"` or `"sharedbox@company.com"`
  - `mailbox_type`: `"personal"` or `"shared"`
  - `ingest_pages`: `1`
  - `ingest_top`: `100`
  - `parse_limit`: `250`
  - `batch_size`: `50`

### Node A2 — Ingest raw emails (Python call)
- **Type**: Execute Command
- **Command** (JSON stdout only):

```bash
DB_PATH="{{$json.db_path}}" \
MAILBOX_ID="{{$json.mailbox_id}}" \
MAILBOX_TYPE="{{$json.mailbox_type}}" \
python3 email-processing/ingest_raw.py \
  --mailbox-id "{{$json.mailbox_id}}" \
  --mailbox-type "{{$json.mailbox_type}}" \
  --pages {{$json.ingest_pages}} \
  --top {{$json.ingest_top}}
```

- **Retry**: 3 attempts, exponential backoff (e.g. 5s, 20s, 60s)
- **Failure path**: on non‑zero exit → Node A_fail_log

### Node A3 — Mark “seen” for this mailbox (DB query)
- **Type**: SQLite
- **Query** (maps to “idempotency at DB level” for ingestion):

```sql
UPDATE mailbox_emails
SET seen = 1
WHERE mailbox_id = :mailbox_id
  AND processed = 0;
```

- **Parameters**:
  - `mailbox_id`: `{{$json.mailbox_id}}`

### Node A4 — Fetch backlog (unprocessed) in batches (DB query)
- **Type**: SQLite
- **Query**:

```sql
SELECT mailbox_id, mailbox_type, canonical_key, raw_id, created_ts
FROM mailbox_emails
WHERE mailbox_id = :mailbox_id
  AND processed = 0
ORDER BY datetime(created_ts) ASC
LIMIT :batch_size;
```

- **Parameters**:
  - `mailbox_id`: `{{$json.mailbox_id}}`
  - `batch_size`: `{{$json.batch_size}}`

### Node A5 — IF: backlog empty?
- **Type**: IF
- **Condition**: `{{$json.length === 0}}`
  - **True** → Node A_done
  - **False** → Node A6

### Node A6 — Parse + normalize + classify (rules-only) (Python call)
- **Type**: Execute Command
- **Command**:

```bash
DB_PATH="{{$json.db_path}}" \
USE_LLM_CLASSIFIER=0 \
python3 email-processing/parse_load.py \
  --mailbox-id "{{$json.mailbox_id}}" \
  --limit {{$json.parse_limit}}
```

- **Retry**: 2 attempts, backoff (10s, 30s)
- **Failure path**: on non‑zero exit → Node A_fail_log

### Node A7 — Mark processed where parsed exists (DB query)
- **Type**: SQLite
- **Query**:

```sql
UPDATE mailbox_emails
SET processed = 1
WHERE mailbox_id = :mailbox_id
  AND processed = 0
  AND EXISTS (
    SELECT 1
    FROM message m
    WHERE m.id = mailbox_emails.raw_id
  );
```

- **Parameters**:
  - `mailbox_id`: `{{$json.mailbox_id}}`

### Node A8 — Loop to drain backlog
- **Type**: NoOp / Merge / Continue
- **Behavior**: connect back to Node A4 to fetch next batch until empty.

### Node A_done — Done
- **Type**: NoOp

### Node A_fail_log — Failure handler
- **Type**: SQLite + optional notification
- **DB insert**: (if you want a run log table later, add it in a future migration; for now, log externally)
- **Recommended**:
  - Send Slack/Email
  - Persist `{{$json}}` + error message as a file artifact (n8n “Write Binary File”)

---

## Workflow B — Optional LLM classification pass (n8n owns LLM calls)

Use this **only after Workflow A**. This keeps parsing/normalization in Python and moves LLM usage fully into n8n.

### Node B0 — Trigger
- Cron / Manual

### Node B1 — Select candidates needing LLM (DB query)
- **Type**: SQLite
- **Query** (example: low-confidence rule classifications):

```sql
SELECT
  m.id,
  m.subject,
  m.from_addr,
  m.body_text,
  ce.confidence,
  ce.rule_name
FROM message m
JOIN classification_event ce
  ON ce.message_id = m.id
WHERE ce.id IN (
  SELECT MAX(id) FROM classification_event GROUP BY message_id
)
  AND ce.confidence < 0.70
ORDER BY datetime(m.received_dt) DESC
LIMIT 50;
```

### Node B2 — Split in Batches
- **Type**: SplitInBatches (size 1 or small N)

### Node B3 — LLM classify (HTTP Request)
- **Type**: HTTP Request (OpenAI/Azure OpenAI)
- **Request**: system prompt + user content:
  - from, subject, body_text (truncate body_text to ~4k chars)
- **Response format**: JSON object: `{"label":"Trades|Client|Internal|Market|Materials|Research|Other","rationale":"..."}`.
- **Retry**: 3 attempts with backoff
- **Failure path**: continue to next item + log artifact

### Node B4 — Persist LLM event (DB query) (append-only)
- **Type**: SQLite
- **Query**:

```sql
INSERT INTO classification_event(message_id, category_auto, rule_name, confidence)
VALUES (:message_id, :label, 'llm_v1', :confidence);
```

- **Parameters**:
  - `message_id`: `{{$json.id}}`
  - `label`: `{{$json.label}}` (from LLM response)
  - `confidence`: `{{$json.confidence || 0.85}}`

### Node B5 — (Optional) Update derived label in `message`
- **Type**: SQLite
- **Query** (updates derived field only; does not touch raw content):

```sql
UPDATE message
SET category = :label,
    updated_ts = datetime('now')
WHERE id = :message_id;
```

If you prefer strictly append-only derived outputs, **skip B5** and treat the latest `classification_event` as the source of truth.

---

## Notes: how this maps to your current tables

- **Idempotency during ingestion**:
  - `mailbox_emails` has `UNIQUE(mailbox_id, canonical_key)` so n8n can safely re-run ingestion without duplicates.
- **Idempotency during parsing**:
  - `parse_load.py` inserts/upserts into `message` keyed by `id` so reruns are safe.
  - n8n “completes” the lifecycle by setting `mailbox_emails.processed=1` once the corresponding `message` row exists.

---

## Minimal environment requirements for n8n Execute Command

- `python3` available
- `DB_PATH` set (recommended) to point at the SQLite DB file.

