# Getting Badges to Show in the Demo Dashboard

The badges (Summary, Draft Reply, etc.) only appear after the automation pipeline has run successfully. Follow these steps in order.

## Prerequisites
- API running (`uvicorn api_server:app --port 8001`)
- `OPENAI_API_KEY` set
- Emails already ingested (inbox has data)

---

## Step 1: Apply taxonomy (required first)

The pipeline needs a taxonomy before it can classify emails. Run:

```bash
curl -X POST http://127.0.0.1:8001/taxonomy/apply \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_1",
    "org_id": "default_org",
    "proposed_taxonomy": [
      {"classification_id": "trades", "name": "Trades", "description": "Trade ideas and execution"},
      {"classification_id": "client", "name": "Client", "description": "Client communication"},
      {"classification_id": "internal", "name": "Internal", "description": "Internal collaboration"},
      {"classification_id": "market", "name": "Market", "description": "Market updates"},
      {"classification_id": "research", "name": "Research", "description": "Research and analysis"},
      {"classification_id": "other", "name": "Other", "description": "Catch-all"}
    ]
  }'
```

---

## Step 2: Apply preferences

Use **empty** `summarize_on_labels` so summaries run for all emails, regardless of category:

```bash
curl -X POST http://127.0.0.1:8001/config/apply-preferences \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_1",
    "org_id": "default_org",
    "preferences": {
      "summarize": true,
      "summarize_on_labels": [],
      "summary_style": "concise",
      "summary_length": "short"
    }
  }'
```

**Why empty?** If you pass specific labels like `["Trades","Client"]`, the pipeline only runs for emails classified as those exact labels. An empty list means "run for all."

---

## Step 3: Run the automation pipeline

```bash
curl -X POST http://127.0.0.1:8001/pipeline/automate \
  -H "Content-Type: application/json" \
  -d '{
    "mailbox_id": "me",
    "user_id": "user_1",
    "org_id": "default_org",
    "limit": 10
  }'
```

---

## Step 4: Refresh the Streamlit dashboard

Reload the page. Emails that were summarised should now show the **Summary** badge.

---

## If it still does not work

1. **Check the automate response** – Look for `"status": "skipped"` on every item. That usually means no actions were built (taxonomy/label mismatch).
2. **Check `OPENAI_API_KEY`** – The pipeline calls the LLM for classification and summarisation.
3. **Check `select_llm_candidates`** – The pipeline only processes emails that appear in both `message` and `mailbox_email`. Re-run `POST /pipeline/ingest` to ensure parse has run and the tables are populated.
