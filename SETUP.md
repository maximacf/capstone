# Mailgine setup guide

This guide walks you through setting up the backend (FastAPI) and frontend (React) for Mailgine.

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** and npm
- **PostgreSQL 14+**
- **OpenAI API key**

---

## 1. PostgreSQL database

Create a database for Mailgine:

```bash
# If using local PostgreSQL (macOS with Homebrew):
createdb maildb

# Or via psql:
psql postgres -c "CREATE DATABASE maildb;"
```

The connection string format is:
```
postgresql://USER:PASSWORD@HOST:PORT/DATABASE
```

Example for local PostgreSQL with user `postgres` and password `mypassword123`:
```
postgresql://postgres:mypassword123@localhost:5432/maildb
```

---

## 2. Backend setup

### 2.1 Create virtual environment and install dependencies

From the project root (`/Users/ifc/SynologyDrive/Year 5/Thesis/Data`):

```bash
cd "/Users/ifc/SynologyDrive/Year 5/Thesis/Data"

# Create venv (if not already done)
python -m venv email-processing-just-code/.venv

# Activate venv
source email-processing-just-code/.venv/bin/activate   # macOS/Linux
# or: email-processing-just-code\.venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
pip install -r email-processing-just-code/requirements_api.txt
```

### 2.2 Set environment variables

```bash
export DATABASE_URL="postgresql://postgres:YOUR_PASSWORD@localhost:5432/maildb"
export OPENAI_API_KEY="sk-..."
```

Replace `YOUR_PASSWORD` with your PostgreSQL password and add your OpenAI API key.

### 2.3 Run the backend

```bash
cd email-processing-just-code
uvicorn api_server:app --reload --port 8001
```

The API will be available at **http://localhost:8001**. Tables are created automatically on first request.

- **API docs**: http://localhost:8001/docs
- **Health check**: http://localhost:8001/health (if available)

---

## 3. Frontend setup

Open a **new terminal** (leave the backend running).

### 3.1 Install dependencies

```bash
cd "/Users/ifc/SynologyDrive/Year 5/Thesis/Data/frontend"
npm install
```

### 3.2 (Optional) Configure API URL

Create `frontend/.env` if you need a custom API URL:

```
VITE_API_BASE=http://127.0.0.1:8001
```

Default is `http://127.0.0.1:8001` if not set.

### 3.3 Run the frontend

```bash
npm run dev
```

Open **http://localhost:5173** in your browser.

---

## 4. Quick start checklist

| Step | Command | Port |
|------|---------|------|
| 1. Create DB | `createdb maildb` | — |
| 2. Start backend | `cd email-processing-just-code && uvicorn api_server:app --reload --port 8001` | 8001 |
| 3. Start frontend | `cd frontend && npm run dev` | 5173 |

---

## 5. Import Enron data (optional)

To load the 500-email Enron corpus for evaluation:

```bash
cd email-processing-just-code

# Ensure DATABASE_URL and OPENAI_API_KEY are set, then:
python import_enron_csv_to_db.py /path/to/emails.csv --limit 500
```

Use `emails.csv` from [Kaggle Enron Email Dataset](https://www.kaggle.com/datasets/wcukierski/enron-email-dataset).

---

## 6. Troubleshooting

| Issue | Solution |
|-------|----------|
| `DATABASE_URL is required` | Set `export DATABASE_URL="postgresql://..."` before running uvicorn |
| `OPENAI_API_KEY is not set` | Set your OpenAI key in the same shell as uvicorn |
| `connection refused` (frontend) | Ensure backend is running on port 8001 |
| `relation "message" does not exist` | Tables are created on first API call; hit any endpoint or run a pipeline once |
| `ModuleNotFoundError` | Activate venv and ensure you're in `email-processing-just-code` when running uvicorn |

---

## 7. Recommended first run flow

1. **Settings** (`/taxonomy`) → Discover taxonomy → Apply
2. **Dashboard** (`/`) → Fetch emails (or use Enron if imported) → Run automation
3. **Evaluation** (`/evaluation`) → Label emails → View metrics
