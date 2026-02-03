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

## Step 3: (Optional) SQLite Node

You *tried* the community SQLite node, but on macOS the Linux build caused
`better_sqlite3.node (not a mach-o file)` errors. To keep things simple and
portable, we will:

- **Skip the SQLite community node**, and
- Use **Python + Execute Command** for all DB mutations.

This respects the boundary: Python owns the DB layer; n8n orchestrates.

---

## Step 4: Build Workflow A (Ingest → Parse → Mark Processed)

### Node 1: Manual Trigger (for testing)
- **Type**: Manual Trigger
- **Name**: "Start Workflow"
- Just click **Add Node** → **Manual Trigger**

### Node 2: Set Configuration
- **Type**: Set
- **Name**: "Set Config"
- **What this does**: This node sets variables that every downstream node will use. It’s a single place to configure paths, mailbox, and limits so you don’t hardcode them in each node.
- **Add these fields** (click "Add Value" for each). Use the **type** shown so n8n passes them correctly:
y
| Name | Type | Value | Why |
|------|------|-------|-----|
| `db_path` | **String** | `/Users/ifc/SynologyDrive/Year 5/Thesis/Data/email-processing/data/mail.db` | Full path to the SQLite DB file (must end in `mail.db`). |
| `mailbox_id` | **String** | `me` | Your personal inbox; use a shared address for shared mailbox. |
| `mailbox_type` | **String** | `personal` | Use `shared` for shared team mailboxes. |
| `ingest_pages` | **Number** | `1` | One “page” of Graph API results. 1 page = up to `ingest_top` emails. Start with 1 for testing; increase (e.g. 2–5) for more emails per run. |
| `ingest_top` | **Number** | `100` | Emails per page from Microsoft Graph (max 1000). |
| `parse_limit` | **Number** | `250` | Max raw emails to parse per run (rules-only). Keeps runs bounded. |
| `batch_size` | **Number** | `50` | How many mailbox_emails to consider “in batch” when checking backlog. |

- **Types matter**: `db_path`, `mailbox_id`, `mailbox_type` = **String**. `ingest_pages`, `ingest_top`, `parse_limit`, `batch_size` = **Number** (so downstream nodes get numbers, not strings).

### Node 3: Ingest Raw Emails
- **Type**: Execute Command
- **Name**: "Ingest Emails"
- **Command**:
```bash
cd "/Users/ifc/SynologyDrive/Year 5/Thesis/Data" && \
DB_PATH="{{$json.db_path}}" \
MAILBOX_ID="{{$json.mailbox_id}}" \
MAILBOX_TYPE="{{$json.mailbox_type}}" \
MSAL_CACHE_PATH="/Users/ifc/.msal_token_cache.json" \
"/Users/ifc/SynologyDrive/Year 5/Thesis/Data/email-processing/.venv/bin/python" \
email-processing/ingest_raw.py \
  --mailbox-id "{{$json.mailbox_id}}" \
  --mailbox-type "{{$json.mailbox_type}}" \
  --pages {{$json.ingest_pages}} \
  --top {{$json.ingest_top}}
```

- **Why MSAL_CACHE_PATH**: persists the device login token so future runs don’t hang.

- **Options** → **Retry**:
  - Enable retry: ✅
  - Max attempts: `3`
  - Wait between attempts: `5` seconds (exponential backoff)

- **Error handling**: Connect to a "Log Error" node (we'll add this later)

### Node 4: Mark Seen (Python)
- **Type**: Execute Command
- **Name**: "Mark Seen"
- **Command**:
```bash
cd "/Users/ifc/SynologyDrive/Year 5/Thesis/Data" && \
DB_PATH="{{$json.db_path}}" \
python3 email-processing/db_ops.py \
  --op mark-seen \
  --mailbox-id "{{$json.mailbox_id}}"
```

This flips `seen` from `0 → 1` in `mailbox_emails` for this mailbox.

### Node 5: Fetch Backlog (Python helper, optional)
For now you can **skip this node** and let `parse_load.py` select on its own:
it already queries `raw_message` rows that are not yet in `message`.

Later, if you want mailbox-specific backlog selection, we can add another
small helper to `db_ops.py` and call it from Execute Command.

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

### Node 8: Mark Processed (Python)
- **Type**: Execute Command
- **Name**: "Mark Processed"
- **Command**:
```bash
cd "/Users/ifc/SynologyDrive/Year 5/Thesis/Data" && \
DB_PATH="{{$json.db_path}}" \
python3 email-processing/db_ops.py \
  --op mark-processed \
  --mailbox-id "{{$json.mailbox_id}}"
```

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

### Docker: "The container name '/n8n' is already in use"
- Another n8n container is still there. Remove it, then run again:
  ```bash
  docker rm -f n8n
  docker run -it --rm --name n8n -p 5678:5678 -v ~/.n8n:/home/node/.n8n n8nio/n8n
  ```

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
