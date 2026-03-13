# Mailgine — React Frontend

Full frontend for the thesis system: inbox, taxonomy config, execution history, and evaluation metrics.

## Setup

```bash
cd frontend
npm install
```

## Run

1. Start the API (in another terminal):
   ```bash
   cd email-processing-just-code
   export DATABASE_URL="postgresql://postgres:mypassword123@localhost:5432/maildb"
   export OPENAI_API_KEY="your-key"
   uvicorn api_server:app --port 8001
   ```

2. Start the frontend:
   ```bash
   npm run dev
   ```

3. Open http://localhost:5173

## Pages

| Route | Purpose |
|-------|---------|
| `/` | Dashboard — inbox, Ingest/Automate triggers, email detail, artifacts |
| `/taxonomy` | Discover taxonomy, apply categories, set preferences |
| `/execution` | Execution history (automation runs) for audit |
| `/evaluation` | Dataset summary and evaluation metrics (Section 3.5) |

## Recommended flow (first run)

1. **Taxonomy** → Discover → Apply taxonomy → Apply preferences
2. **Dashboard** → Ingest emails → Run automation
3. **Dashboard** → View emails, classifications, artifacts (summaries, translations)
4. **Execution** → Inspect automation runs
5. **Evaluation** → Check corpus stats and category distribution

## Environment

Create `.env` (optional):
```
VITE_API_BASE=http://127.0.0.1:8001
```

Default is `http://127.0.0.1:8001` if not set.
