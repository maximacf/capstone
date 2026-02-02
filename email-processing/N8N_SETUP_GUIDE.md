# n8n Setup & Workflow Building Guide

## Step 1: Choose Your n8n Setup

You have **two options**:

### Option A: n8n Cloud (Easiest - Free Tier Available)
1. Go to **https://n8n.io**
2. Sign up for free account (or log in)
3. You'll get a cloud workspace immediately
4. **Note**: For Execute Command nodes, you'll need n8n Self-Hosted (see Option B)

### Option B: n8n Self-Hosted (Required for Execute Command)
Since you need to run Python scripts, you need **self-hosted n8n**:

```bash
# Install n8n globally
npm install -g n8n

# Or use Docker
docker run -it --rm \
  --name n8n \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  n8nio/n8n
```

Then open **http://localhost:5678** in your browser.

---

## Step 2: Get Your Project Path

Your project is located at:
```
/Users/ifc/SynologyDrive/Year 5/Thesis/Data
```

Your database path will be:
```
/Users/ifc/SynologyDrive/Year 5/Thesis/Data/email-processing/data/mail.db
```

**Save these paths** - you'll need them in n8n!

---

## Step 3: Install SQLite Node in n8n

1. In n8n, go to **Settings** → **Community Nodes**
2. Search for **"n8n-nodes-sqlite"** or **"SQLite"**
3. Install it (or use the built-in SQLite node if available)

**Alternative**: Use **HTTP Request** node to call a Python script that executes SQL, but the SQLite node is cleaner.

---

## Step 4: Build Workflow A (Ingest → Parse → Mark Processed)

### Node 1: Manual Trigger (for testing)
- **Type**: Manual Trigger
- **Name**: "Start Workflow"
- Just click **Add Node** → **Manual Trigger**

### Node 2: Set Configuration
- **Type**: Set
- **Name**: "Set Config"
- **Add these fields** (click "Add Value" for each):

| Name | Value |
|------|-------|
| `db_path` | `/Users/ifc/SynologyDrive/Year 5/Thesis/Data/email-processing/data/mail.db` |
| `mailbox_id` | `me` |
| `mailbox_type` | `personal` |
| `ingest_pages` | `1` |
| `ingest_top` | `100` |
| `parse_limit` | `250` |
| `batch_size` | `50` |

### Node 3: Ingest Raw Emails
- **Type**: Execute Command
- **Name**: "Ingest Emails"
- **Command**:
```bash
cd "/Users/ifc/SynologyDrive/Year 5/Thesis/Data" && DB_PATH="{{$json.db_path}}" MAILBOX_ID="{{$json.mailbox_id}}" MAILBOX_TYPE="{{$json.mailbox_type}}" python3 email-processing/ingest_raw.py --mailbox-id "{{$json.mailbox_id}}" --mailbox-type "{{$json.mailbox_type}}" --pages {{$json.ingest_pages}} --top {{$json.ingest_top}}
```

- **Options** → **Retry**:
  - Enable retry: ✅
  - Max attempts: `3`
  - Wait between attempts: `5` seconds (exponential backoff)

- **Error handling**: Connect to a "Log Error" node (we'll add this later)

### Node 4: Mark Seen
- **Type**: SQLite (or Code node with SQL)
- **Name**: "Mark Seen"
- **Database File**: `{{$json.db_path}}`
- **Operation**: Execute Query
- **Query**:
```sql
UPDATE mailbox_emails
SET seen = 1
WHERE mailbox_id = ?
  AND processed = 0;
```
- **Parameters**: `{{$json.mailbox_id}}`

### Node 5: Fetch Backlog
- **Type**: SQLite
- **Name**: "Fetch Backlog"
- **Database File**: `{{$json.db_path}}`
- **Operation**: Execute Query
- **Query**:
```sql
SELECT mailbox_id, mailbox_type, canonical_key, raw_id, created_ts
FROM mailbox_emails
WHERE mailbox_id = ?
  AND processed = 0
ORDER BY datetime(created_ts) ASC
LIMIT ?;
```
- **Parameters**: 
  - `{{$json.mailbox_id}}`
  - `{{$json.batch_size}}`

### Node 6: Check If Empty
- **Type**: IF
- **Name**: "Is Backlog Empty?"
- **Condition**: `{{$json.length === 0}}` or `{{$json.length === 0 || !$json.length}}`
- **True** → Connect to "Done" node
- **False** → Connect to "Parse" node

### Node 7: Parse & Classify
- **Type**: Execute Command
- **Name**: "Parse Emails"
- **Command**:
```bash
cd "/Users/ifc/SynologyDrive/Year 5/Thesis/Data" && DB_PATH="{{$json.db_path}}" USE_LLM_CLASSIFIER=0 python3 email-processing/parse_load.py --mailbox-id "{{$json.mailbox_id}}" --limit {{$json.parse_limit}}
```

- **Options** → **Retry**: 2 attempts, 10s backoff

### Node 8: Mark Processed
- **Type**: SQLite
- **Name**: "Mark Processed"
- **Database File**: `{{$json.db_path}}`
- **Query**:
```sql
UPDATE mailbox_emails
SET processed = 1
WHERE mailbox_id = ?
  AND processed = 0
  AND EXISTS (
    SELECT 1
    FROM message m
    WHERE m.id = mailbox_emails.raw_id
  );
```
- **Parameters**: `{{$json.mailbox_id}}`

### Node 9: Loop Back
- **Type**: NoOp (or just connect Node 8 back to Node 5)
- **Name**: "Loop Back"
- Connect Node 8 output back to Node 5 input

### Node 10: Done
- **Type**: NoOp
- **Name**: "Done"

### Node 11: Error Handler
- **Type**: Set (or HTTP Request to send notification)
- **Name**: "Log Error"
- Store error message: `{{$json.error}}`

---

## Step 5: Test Your Workflow

1. Click **"Execute Workflow"** button (top right)
2. Watch each node execute
3. Check the output of each node
4. Verify in your database:
```bash
cd "/Users/ifc/SynologyDrive/Year 5/Thesis/Data/email-processing"
python3 -c "from store_db import connect; con = connect(); cur = con.cursor(); print('Processed:', cur.execute('SELECT COUNT(*) FROM mailbox_emails WHERE processed=1').fetchone()[0])"
```

---

## Troubleshooting

### "Execute Command" node not available?
- You need **n8n Self-Hosted** (not cloud)
- Install via npm or Docker (see Step 1)

### SQLite node not found?
- Use **Code** node with `sqlite3` library
- Or use **HTTP Request** to call a Python SQL endpoint

### Python path issues?
- Use full path: `/usr/local/bin/python3` or `/usr/bin/python3`
- Check with: `which python3`

### Database locked?
- SQLite uses WAL mode (should be fine)
- If issues, add small delays between DB operations

---

## Next Steps

Once Workflow A works:
1. Add **Cron Trigger** (replace Manual Trigger) to run every 5 minutes
2. Build **Workflow B** (LLM classification) - see `N8N_STEP3_ORCHESTRATION.md`
3. Add error notifications (Slack, Email, etc.)
