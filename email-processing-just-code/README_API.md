# Just-Code API (FastAPI)

This is the API-first backend for Mailgine (thesis model).

## Install

From repo root:

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r email-processing-just-code/requirements_api.txt
```

## Database (PostgreSQL + SQLAlchemy ORM)

The app uses **PostgreSQL only**. Set `DATABASE_URL` before running:

```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/maildb"
uvicorn api_server:app --app-dir email-processing-just-code --reload --port 8001
```

**Migrations:** Use Alembic for schema changes:

```bash
cd email-processing-just-code
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## Run

```
export OPENAI_API_KEY="..."
uvicorn api_server:app --app-dir email-processing-just-code --reload --port 8001
```

## Endpoints

- `POST /config/compile`
- `POST /config/apply-preferences`
- `POST /taxonomy/discover`
- `POST /taxonomy/apply`
- `POST /mailbox/map`
- `GET /mailbox/{mailbox_id}/inbox`
- `POST /pipeline/ingest`
- `POST /pipeline/automate`

All endpoints accept `db_path` if you want to override the default DB file.

## Minimal Demo UI (Streamlit)

```
cd "/Users/ifc/SynologyDrive/Year 5/Thesis/Data"
API_BASE="http://127.0.0.1:8001" streamlit run email-processing-just-code/ui_dashboard.py
```

## Taxonomy Discovery + Apply Flow (Per User)

This is the recommended flow for every new user. Discovery is exploratory and
read-only. Apply writes the user-approved taxonomy to `classifications_json`.

### 1) Discover taxonomy (read-only)

```
curl -X POST http://127.0.0.1:8001/taxonomy/discover \
  -H "Content-Type: application/json" \
  -d '{"mailbox_id":"me","sample_limit":50,"window_days":90}'
```

Response contains `proposed_taxonomy` (5–8 categories + catch-all). The client
should allow users to rename/merge/delete categories.

### 2) Apply edited taxonomy (write)

```
curl -X POST http://127.0.0.1:8001/taxonomy/apply \
  -H "Content-Type: application/json" \
  -d '{
    "user_id":"user_1",
    "org_id":"org_1",
    "proposal_id": null,
    "proposed_taxonomy":[
      {"classification_id":"research_analysis","name":"Research & Market Analysis","description":"..."},
      {"classification_id":"client_communication","name":"Client Communication","description":"..."},
      {"classification_id":"transactions_operations","name":"Transactions & Operations","description":"..."},
      {"classification_id":"business_development","name":"Business Development & Introductions","description":"..."},
      {"classification_id":"marketing_updates","name":"Marketing & Product Updates","description":"..."},
      {"classification_id":"other","name":"Other / Noise","description":"..."}
    ]
  }'
```

After apply, runtime classification in `/pipeline/automate` will choose from
the approved taxonomy only (no new labels invented at runtime).
