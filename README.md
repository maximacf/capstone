# MAILGINE — AI-Driven Intelligent Email Processing

**Capstone Project** | IE University — BBA & Data and Business Analytics | 2026

MAILGINE is a full-stack, AI-driven email processing system that classifies incoming emails against a user-defined taxonomy using a hybrid rule-based and LLM approach, executes configurable automation actions (summarisation, draft replies, extraction, translation), and persists every output as a traceable, auditable record.

## Architecture

| Component | Technology | Location |
|-----------|-----------|----------|
| Backend | Python / FastAPI | `email-processing-just-code/` |
| Frontend | React / TypeScript | `frontend/` |
| Database | PostgreSQL | Medallion architecture (Bronze/Silver/Gold) |
| Email API | Microsoft Graph (OAuth 2.0) | |
| LLM | OpenAI GPT-4o-mini | Classification fallback + content generation |

## Key Features

- **Hybrid classification**: deterministic regex rules with LLM fallback (confidence < 0.70)
- **User-defined taxonomies**: version-controlled, configurable via natural language
- **Idempotent execution**: SHA-256 fingerprinting + database-level uniqueness constraints
- **Layered data architecture**: raw emails (Bronze), classifications (Silver), artefacts (Gold)
- **Multi-mailbox support**: connect any Microsoft 365 account at runtime
- **Append-only audit log**: full traceability of all automation decisions

## Repository Structure

```
email-processing-just-code/   # Backend: FastAPI API server, classification, ingestion
frontend/                      # Frontend: React UI (Inbox, Settings, Evaluation, Activity Log)
analyze_survey.py              # TAM survey analysis script
verify_reproducibility.py      # Idempotency and reproducibility verification
import_enron_csv_to_db.py      # Enron corpus import for evaluation
send_enron_csv_to_outlook.py   # Enron-to-Outlook pipeline for testing
evaluation_form.html           # TAM evaluation form
survey_results.csv             # TAM survey data (n=20)
*.json                         # Example system outputs (corpus snapshots, API responses)
```

## Setup

See [SETUP.md](SETUP.md) for full installation instructions (backend, frontend, database, and API keys).

## Evaluation Results

| Metric | Result |
|--------|--------|
| Macro F1 Score | 0.808 (5-category taxonomy) |
| Idempotency | 100% (0 duplicates across 3 runs) |
| F1 Gain from Taxonomy Refinement | +20.2% |
| User Rating (Classification Quality) | 4.80 / 5.00 |
