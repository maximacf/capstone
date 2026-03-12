# Mailgine — Adaptive Email Intelligence

**Architecture:** See [ARCHITECTURE.md](ARCHITECTURE.md) for system design, data flow, and folder hierarchy.

**Backend (source of truth):** `email-processing-just-code/` — FastAPI + PostgreSQL. This is the canonical implementation for the thesis methodology.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

