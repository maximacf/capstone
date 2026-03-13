import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

# Load environment variables from .env if present.
# Try cwd, this package dir, and repo root (one level up).
_cwd_env = os.path.join(os.getcwd(), ".env")
_local_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
_repo_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
for _env_path in (_cwd_env, _local_env, _repo_env):
    if os.path.exists(_env_path):
        load_dotenv(_env_path)

# Allow running via uvicorn --app-dir with a hyphenated folder name
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import database
import db_ops
import ingest_raw
import parse_load
import store_db
from classification import html_to_text

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

app = FastAPI(title="Mailgine API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    """Redirect root to API docs."""
    return RedirectResponse(url="/docs")


def _set_db_path(db_path: Optional[str]) -> None:
    if db_path:
        from database import set_db_path

        set_db_path(db_path)


def _openai_json(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set")
    url = f"{OPENAI_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=resp.text)
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="LLM did not return valid JSON")


def _load_message_samples(
    mailbox_id: Optional[str], limit: int
) -> List[Dict[str, Any]]:
    con = store_db.connect()
    cur = con.cursor()
    params: List[Any] = []
    mailbox_join = ""
    mailbox_where = ""
    if mailbox_id:
        mailbox_join = "JOIN mailbox_emails me ON me.raw_id = m.id"
        mailbox_where = "AND me.mailbox_id = ?"
        params.append(mailbox_id)
    params.append(limit)
    rows = cur.execute(
        f"""
        SELECT m.id, m.from_addr, m.subject, LEFT(COALESCE(m.body_text, ''), 500) AS body_text
        FROM message m
        {mailbox_join}
        WHERE 1=1
        {mailbox_where}
        ORDER BY m.received_dt DESC NULLS LAST
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "id": row[0],
            "from_addr": row[1],
            "subject": row[2],
            "body_text": row[3],
        }
        for row in rows
    ]


def _normalize_subject(subject: Optional[str]) -> str:
    if not subject:
        return ""
    cleaned = re.sub(r"^(re|fw|fwd)\s*:\s*", "", subject.strip(), flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.lower()


def _sample_discovery_emails(
    mailbox_id: Optional[str],
    sample_limit: int,
    window_days: int = 90,
) -> List[Dict[str, Any]]:
    con = store_db.connect()
    params: List[Any] = []
    mailbox_join = ""
    mailbox_where = ""
    if mailbox_id:
        # Support both legacy (mailbox_emails) and enterprise (mailbox_email + email)
        mailbox_join = """
            LEFT JOIN mailbox_emails me_legacy ON me_legacy.raw_id = m.id AND me_legacy.mailbox_id = ?
            LEFT JOIN email e ON e.provider_msg_id = m.id
            LEFT JOIN mailbox_email me ON me.email_id = e.email_id AND me.mailbox_id = ?
            """
        # Match if in either table
        mailbox_where = (
            "AND (me_legacy.raw_id IS NOT NULL OR me.mailbox_id IS NOT NULL)"
        )
        params.extend([mailbox_id, mailbox_id])
    params.append(sample_limit * 5)

    # For enron_import and other historical mailboxes, skip date filter (window_days=0 means no filter)
    date_filter = (
        f"AND (m.received_dt::timestamptz) >= (CURRENT_DATE - INTERVAL '{window_days} days')"
        if window_days > 0
        else ""
    )

    sql = f"""
        SELECT m.id, m.from_addr, m.subject, m.received_dt,
               LEFT(COALESCE(m.body_text, ''), 400) AS body_text, m.thread_id
        FROM message m {mailbox_join}
        WHERE 1=1 {date_filter} {mailbox_where}
        ORDER BY random() LIMIT ?
        """
    rows = con.execute(sql, tuple(params)).fetchall()

    seen_keys: set[str] = set()
    samples: List[Dict[str, Any]] = []
    for row in rows:
        subject_key = _normalize_subject(row[2])
        thread_key = row[5] or ""
        dedupe_key = f"{thread_key}|{subject_key}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        samples.append(
            {
                "id": row[0],
                "from_addr": row[1],
                "subject": row[2],
                "received_ts": row[3],
                "body_text": row[4],
            }
        )
        if len(samples) >= sample_limit:
            break
    return samples


def _build_actions(
    preferences: Dict[str, Any],
    classification: Dict[str, Any],
    config_version: Optional[int],
) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []

    def _add_action(action_type: str, params: Dict[str, Any]) -> None:
        actions.append(
            {
                "type": action_type,
                "params": params,
                "params_json": json.dumps(params),
                "input_json": json.dumps(
                    {
                        "classification_id": classification.get("classification_id"),
                        "classification_label": classification.get("label"),
                        "classification_confidence": classification.get("confidence"),
                        "params": params,
                        "preference_version": config_version,
                        "action_type": action_type,
                    }
                ),
            }
        )

    def _should_trigger(on_labels: List[str]) -> bool:
        if not on_labels:
            return True
        return classification.get("label") in on_labels

    if isinstance(preferences.get("actions"), list):
        for action in preferences.get("actions") or []:
            action_type = str(action.get("type", "")).strip()
            if not action_type:
                continue
            on_labels = action.get("on_labels") or []
            if not _should_trigger(on_labels):
                continue
            params = action.get("params") or {}
            _add_action(action_type, params)
        return actions

    summarize_enabled = bool(preferences.get("summarize"))
    summarize_labels = preferences.get("summarize_on_labels") or []
    if summarize_enabled and _should_trigger(summarize_labels):
        params = {
            "style": preferences.get("summary_style", "client_friendly"),
            "length": preferences.get("summary_length", "short"),
        }
        if preferences.get("summary_max_bullets") is not None:
            params["max_bullets"] = preferences["summary_max_bullets"]
        if preferences.get("summary_format"):
            params["format"] = preferences["summary_format"]
        _add_action("summarize", params)

    draft_enabled = bool(preferences.get("draft_reply"))
    draft_labels = preferences.get("draft_reply_on_labels") or []
    if draft_enabled and _should_trigger(draft_labels):
        params = {
            "tone": preferences.get("draft_reply_tone", "professional"),
            "instructions": preferences.get("draft_reply_instructions", ""),
        }
        _add_action("draft_reply", params)

    translate_enabled = bool(preferences.get("translate"))
    translate_labels = preferences.get("translate_on_labels") or []
    if translate_enabled and _should_trigger(translate_labels):
        params = {
            "target_language": preferences.get("translate_target_language", "English"),
        }
        _add_action("translate", params)

    extract_enabled = bool(preferences.get("extract"))
    extract_labels = preferences.get("extract_on_labels") or []
    if extract_enabled and _should_trigger(extract_labels):
        # Per-label schema hint takes priority over the global one
        per_label_hints = preferences.get("extract_schema_hints") or {}
        label = classification.get("label", "")
        schema_hint = per_label_hints.get(label) or preferences.get(
            "extract_schema_hint", ""
        )
        params = {
            "schema_hint": schema_hint,
        }
        _add_action("extract", params)
    return actions


class CompileConfigRequest(BaseModel):
    user_id: str
    org_id: str
    natural_language: str
    actor: Optional[str] = None
    db_path: Optional[str] = None


@app.post("/config/compile")
def compile_config(req: CompileConfigRequest) -> Dict[str, Any]:
    _set_db_path(req.db_path)
    system_prompt = (
        "You are an assistant that converts natural-language preferences into JSON. "
        "Return JSON only with keys: classifications (object) and preferences (object)."
    )
    user_prompt = f"Preferences:\n{req.natural_language}"
    result = _openai_json(system_prompt, user_prompt)
    classifications_json = json.dumps(result.get("classifications", {}))
    preferences_json = json.dumps(result.get("preferences", {}))
    db_ops.upsert_config(
        user_id=req.user_id,
        org_id=req.org_id,
        classifications_json=classifications_json,
        preferences_json=preferences_json,
        actor=req.actor,
    )
    cfg = db_ops.get_user_config(req.user_id)
    return {
        "status": "ok",
        "user_id": req.user_id,
        "config_version": cfg.get("config_version"),
    }


class CompilePreferencesRequest(BaseModel):
    natural_language: str
    user_id: str = "user_1"
    org_id: str = "org_1"
    db_path: Optional[str] = None


PREFERENCES_SCHEMA_HINT = """
Output a JSON object with these keys (use empty arrays for "all categories"):
- summarize: bool
- summarize_on_labels: list of category names (empty = all)
- summary_style: "client_friendly" | "technical" | "executive"
- summary_length: "short" | "medium" | "long"
- summary_max_bullets: number (optional, e.g. 5 for "max 5 bullet points")
- summary_format: "paragraph" | "bullets" (optional)
- translate: bool
- translate_on_labels: list
- translate_target_language: string
- extract: bool
- extract_on_labels: list
- extract_schema_hint: string (optional, e.g. "entities, dates")
- draft_reply: bool
- draft_reply_on_labels: list
"""


@app.post("/config/compile-preferences")
def compile_preferences(req: CompilePreferencesRequest) -> Dict[str, Any]:
    """Convert natural-language automation preferences to JSON. Does not save."""
    _set_db_path(req.db_path)
    cfg = db_ops.get_user_config(req.user_id)
    classifications = json.loads(cfg.get("classifications_json") or "{}")
    label_list = ", ".join(classifications.keys()) if classifications else "any"
    system_prompt = (
        "You convert natural-language automation preferences into a JSON object. "
        "Return JSON only. Do not include classifications. "
        "Only include the preferences object. "
        + PREFERENCES_SCHEMA_HINT
        + "\nAvailable category labels for on_labels: "
        + label_list
    )
    user_prompt = f"User request:\n{req.natural_language}"
    result = _openai_json(system_prompt, user_prompt)
    prefs = result if isinstance(result, dict) else result.get("preferences", result)
    return {"status": "ok", "preferences": prefs}


class SuggestLabelsRequest(BaseModel):
    user_id: str
    org_id: str
    mailbox_id: Optional[str] = None
    sample_limit: int = 20
    actor: Optional[str] = None
    db_path: Optional[str] = None


@app.post("/config/suggest-labels")
def suggest_labels(req: SuggestLabelsRequest) -> Dict[str, Any]:
    _set_db_path(req.db_path)
    samples = _load_message_samples(req.mailbox_id, req.sample_limit)
    if not samples:
        raise HTTPException(
            status_code=400, detail="No messages available to suggest labels"
        )

    system_prompt = (
        "You propose email classification categories for an inbox based on examples. "
        "Return JSON only with schema: "
        '{"labels":[{"name":"...", "description":"..."}]}. '
        "Use 5-8 labels. Names should be short."
    )
    sample_text = "\n\n".join(
        [
            f"From: {s.get('from_addr')}\nSubject: {s.get('subject')}\nBody: {s.get('body_text')}"
            for s in samples
        ]
    )
    user_prompt = f"Email samples:\n{sample_text}"
    result = _openai_json(system_prompt, user_prompt)
    labels = result.get("labels") or []
    if not labels:
        raise HTTPException(status_code=502, detail="LLM did not return labels")

    classifications = {
        lbl.get("name"): lbl.get("description") for lbl in labels if lbl.get("name")
    }
    if not classifications:
        raise HTTPException(status_code=502, detail="LLM returned empty label names")

    existing = db_ops.get_user_config(req.user_id)
    preferences_json = (
        existing.get("preferences_json") if existing.get("status") == "ok" else "{}"
    )
    db_ops.upsert_config(
        user_id=req.user_id,
        org_id=req.org_id,
        classifications_json=json.dumps(classifications),
        preferences_json=preferences_json or "{}",
        actor=req.actor,
    )
    cfg = db_ops.get_user_config(req.user_id)
    return {
        "status": "ok",
        "user_id": req.user_id,
        "config_version": cfg.get("config_version"),
        "label_count": len(classifications),
    }


class DiscoverTaxonomyRequest(BaseModel):
    mailbox_id: Optional[str] = None
    sample_limit: int = 50
    window_days: int = 90
    db_path: Optional[str] = None


@app.post("/taxonomy/discover")
def taxonomy_discover(req: DiscoverTaxonomyRequest) -> Dict[str, Any]:
    _set_db_path(req.db_path)
    # enron_import and other historical mailboxes: no date filter
    window_days = 0 if req.mailbox_id == "enron_import" else req.window_days
    samples = _sample_discovery_emails(
        mailbox_id=req.mailbox_id,
        sample_limit=req.sample_limit,
        window_days=window_days,
    )
    if not samples:
        raise HTTPException(
            status_code=400, detail="No messages available to discover taxonomy"
        )

    system_prompt = (
        "You are a taxonomy discovery assistant. You propose a mailbox-specific set of "
        "email categories based on examples. "
        "Return JSON only with schema: "
        '{"proposed_taxonomy":[{"classification_id":"...", "name":"...", "description":"..."}]}. '
        "\n\n**MECE principle (Mutually Exclusive, Collectively Exhaustive):**\n"
        "- **Mutually Exclusive:** Categories must NOT overlap. Each email should fit into at most one category. "
        "If two categories could both apply to the same email, merge them or refine their boundaries. "
        "Avoid overlapping descriptions (e.g. 'marketing' vs 'promotions'—pick one).\n"
        "- **Collectively Exhaustive:** Together the categories must cover ALL emails in the mailbox. "
        "Include an 'other' or 'general' catch-all for items that do not fit elsewhere.\n\n"
        "Rules: propose 5-8 categories; classification_id must be snake_case; include short, precise descriptions; "
        "do NOT classify individual emails."
    )
    sample_text = "\n\n".join(
        [
            "From: {from_addr}\nSubject: {subject}\nReceived: {received_ts}\nBody: {body_text}".format(
                **sample
            )
            for sample in samples
        ]
    )
    user_prompt = f"Email samples:\n{sample_text}"
    result = _openai_json(system_prompt, user_prompt)
    proposed = result.get("proposed_taxonomy") or []
    if not proposed:
        raise HTTPException(status_code=502, detail="LLM did not return taxonomy")

    has_catch_all = any(
        item.get("classification_id") in {"other", "noise_newsletters"}
        for item in proposed
    )
    if not has_catch_all:
        proposed.append(
            {
                "classification_id": "other",
                "name": "Other",
                "description": "Catch-all for items that do not fit other categories",
            }
        )

    return {
        "status": "ok",
        "sampled_count": len(samples),
        "proposal_id": None,
        "proposed_taxonomy": proposed,
    }


class ApplyTaxonomyRequest(BaseModel):
    user_id: str
    org_id: str
    proposed_taxonomy: List[Dict[str, Any]]
    proposal_id: Optional[str] = None
    actor: Optional[str] = None
    db_path: Optional[str] = None


@app.post("/taxonomy/apply")
def taxonomy_apply(req: ApplyTaxonomyRequest) -> Dict[str, Any]:
    _set_db_path(req.db_path)
    if not req.proposed_taxonomy:
        raise HTTPException(status_code=400, detail="proposed_taxonomy is required")

    invalid = []
    classifications: Dict[str, str] = {}
    seen_ids: set[str] = set()
    invalid_ids: list[str] = []
    for item in req.proposed_taxonomy:
        cid = str(item.get("classification_id", "")).strip()
        desc = str(item.get("description", "")).strip()
        if not cid:
            invalid.append(item)
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]*", cid):
            invalid_ids.append(cid)
            continue
        if cid in seen_ids:
            invalid_ids.append(cid)
            continue
        seen_ids.add(cid)
        classifications[cid] = desc
    if not classifications:
        raise HTTPException(
            status_code=400, detail="No valid classification_id values found"
        )
    if invalid:
        raise HTTPException(
            status_code=400,
            detail="One or more taxonomy items missing classification_id",
        )
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail="Invalid or duplicate classification_id values (must be snake_case and unique)",
        )
    if "other" not in classifications:
        raise HTTPException(
            status_code=400, detail="Catch-all classification_id 'other' is required"
        )

    existing = db_ops.get_user_config(req.user_id)
    preferences_json = (
        existing.get("preferences_json") if existing.get("status") == "ok" else "{}"
    )
    db_ops.upsert_config(
        user_id=req.user_id,
        org_id=req.org_id,
        classifications_json=json.dumps(classifications),
        preferences_json=preferences_json or "{}",
        actor=req.actor,
    )
    cfg = db_ops.get_user_config(req.user_id)
    return {
        "status": "ok",
        "user_id": req.user_id,
        "config_version": cfg.get("config_version"),
        "proposal_id": req.proposal_id,
        "classification_count": len(classifications),
    }


class ApplyPreferencesRequest(BaseModel):
    user_id: str
    org_id: str
    preferences: Dict[str, Any]
    actor: Optional[str] = None
    db_path: Optional[str] = None


@app.post("/config/apply-preferences")
def apply_preferences(req: ApplyPreferencesRequest) -> Dict[str, Any]:
    _set_db_path(req.db_path)
    if not req.preferences:
        raise HTTPException(status_code=400, detail="preferences is required")

    existing = db_ops.get_user_config(req.user_id)
    classifications_json = (
        existing.get("classifications_json") if existing.get("status") == "ok" else "{}"
    )
    db_ops.upsert_config(
        user_id=req.user_id,
        org_id=req.org_id,
        classifications_json=classifications_json or "{}",
        preferences_json=json.dumps(req.preferences),
        actor=req.actor,
    )
    cfg = db_ops.get_user_config(req.user_id)
    return {
        "status": "ok",
        "user_id": req.user_id,
        "config_version": cfg.get("config_version"),
    }


@app.get("/config")
def get_config(
    user_id: str = "user_1",
    mailbox_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Return saved taxonomy and preferences for the Taxonomy page."""
    _set_db_path(db_path)
    cfg = db_ops.get_user_config(user_id)
    classifications: Dict[str, str] = {}
    preferences: Dict[str, Any] = {}
    if cfg.get("status") == "ok":
        classifications = json.loads(cfg.get("classifications_json") or "{}")
        preferences = json.loads(cfg.get("preferences_json") or "{}")

    # Merge actual categories from DB so stale user_config doesn't hide them
    con = store_db.connect()
    if mailbox_id:
        db_cats = con.execute(
            """SELECT DISTINCT COALESCE(m.manual_category, m.category) AS cat
               FROM message m
               JOIN email e ON e.provider_msg_id = m.id
               JOIN mailbox_email me ON me.email_id = e.email_id
               WHERE me.mailbox_id = ? AND COALESCE(m.manual_category, m.category) IS NOT NULL""",
            (mailbox_id,),
        ).fetchall()
    else:
        db_cats = con.execute(
            "SELECT DISTINCT category FROM message WHERE category IS NOT NULL"
        ).fetchall()
    for row in db_cats:
        cat = row[0]
        if cat and cat not in classifications:
            classifications[cat] = f"Emails classified as {cat}"

    taxonomy = [
        {"classification_id": k, "name": k, "description": v}
        for k, v in classifications.items()
    ]
    return {
        "status": "ok",
        "classifications": classifications,
        "taxonomy": taxonomy,
        "preferences": preferences,
    }


@app.get("/config/labels")
def get_config_labels(
    user_id: str = "user_1",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Return taxonomy labels — merges user config with categories actually present in the DB."""
    _set_db_path(db_path)
    labels: set = set()
    # From user config
    cfg = db_ops.get_user_config(user_id)
    if cfg.get("status") == "ok":
        classifications = json.loads(cfg.get("classifications_json") or "{}")
        labels.update(classifications.keys())
    # From actual data (covers consolidated categories not yet in user_config)
    con = store_db.connect()
    rows = con.execute(
        "SELECT DISTINCT category FROM message WHERE category IS NOT NULL"
    ).fetchall()
    labels.update(row[0] for row in rows if row[0])
    if not labels:
        labels = {"Other", "Internal", "Client", "Research"}
    return {"status": "ok", "labels": sorted(labels)}


class MailboxMapRequest(BaseModel):
    mailbox_id: str
    org_id: str
    mailbox_type: str = "shared_team"
    owner_user_id: Optional[str] = None
    mailbox_name: Optional[str] = None
    message_id: Optional[str] = None
    email_id: Optional[str] = None
    delivered_at: Optional[str] = None
    labels_json: Optional[str] = None
    read_state: Optional[str] = None
    archived_state: Optional[str] = None
    db_path: Optional[str] = None


@app.post("/mailbox/map")
def mailbox_map(req: MailboxMapRequest) -> Dict[str, Any]:
    _set_db_path(req.db_path)
    if not req.email_id and not req.message_id:
        raise HTTPException(
            status_code=400, detail="email_id or message_id is required"
        )

    mailbox_type = "shared_team" if req.mailbox_type == "shared" else req.mailbox_type
    con = store_db.connect()
    store_db.ensure_organization(con, req.org_id)
    store_db.ensure_mailbox(
        con,
        mailbox_id=req.mailbox_id,
        org_id=req.org_id,
        mailbox_type=mailbox_type,
        owner_user_id=req.owner_user_id if mailbox_type == "personal" else None,
        name=req.mailbox_name or req.mailbox_id,
    )

    canonical_email_id = req.email_id
    delivered_at = req.delivered_at
    if not canonical_email_id:
        row = con.execute(
            "SELECT internet_id, received_dt, from_addr, subject, body_text, body_html FROM message WHERE id = ?",
            (req.message_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="message_id not found")
        canonical_email_id = row[0] or req.message_id
        delivered_at = delivered_at or row[1]
        existing_email = con.execute(
            "SELECT email_id FROM email WHERE email_id = ?",
            (canonical_email_id,),
        ).fetchone()
        if not existing_email:
            store_db.upsert_email(
                con,
                {
                    "email_id": canonical_email_id,
                    "org_id": req.org_id,
                    "provider_msg_id": req.message_id,
                    "thread_id": None,
                    "from_addr": row[2],
                    "to_addrs": None,
                    "cc_addrs": None,
                    "subject": row[3],
                    "received_at": row[1],
                    "body_text": row[4],
                    "body_html": row[5],
                    "raw_mime_ptr": None,
                    "content_hash": None,
                },
            )

    store_db.upsert_mailbox_email_map(
        con,
        {
            "mailbox_id": req.mailbox_id,
            "email_id": canonical_email_id,
            "delivered_at": delivered_at,
            "labels_json": req.labels_json,
            "read_state": req.read_state,
            "archived_state": req.archived_state,
        },
    )
    return {
        "status": "ok",
        "mailbox_id": req.mailbox_id,
        "email_id": canonical_email_id,
    }


@app.get("/mailbox/{mailbox_id}/inbox")
def mailbox_inbox(
    mailbox_id: str,
    limit: int = 50,
    offset: int = 0,
    include_body: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    _set_db_path(db_path)
    con = store_db.connect()
    if include_body:
        body_col = "LEFT(COALESCE(m.body_text, ''), 4000) AS body_text, LEFT(COALESCE(e.body_html, ''), 8000) AS body_html"
    else:
        body_col = "NULL AS body_text, NULL AS body_html"
    rows = con.execute(
        f"""
        SELECT
          me.mailbox_email_id,
          me.email_id,
          e.subject,
          e.from_addr,
          e.received_at,
          COALESCE(m.manual_category, m.category) AS category,
          m.category AS auto_category,
          m.manual_category,
          {body_col},
          ef.has_summary,
          ef.last_action_status,
          ef.last_action_at,
          CASE
            WHEN EXISTS (
              SELECT 1 FROM automation_run ar
              JOIN artifact a ON a.run_id = ar.run_id
              WHERE ar.mailbox_id = me.mailbox_id
                AND ar.email_id = me.email_id
                AND a.artifact_type = 'summary'
                AND ar.status = 'success'
            ) THEN 1 ELSE 0
          END AS has_summary_calc,
          CASE
            WHEN EXISTS (
              SELECT 1 FROM automation_run ar
              JOIN artifact a ON a.run_id = ar.run_id
              WHERE ar.mailbox_id = me.mailbox_id
                AND ar.email_id = me.email_id
                AND a.artifact_type = 'draft_reply'
                AND ar.status = 'success'
            ) THEN 1 ELSE 0
          END AS has_draft_reply,
          CASE
            WHEN EXISTS (
              SELECT 1 FROM automation_run ar
              JOIN artifact a ON a.run_id = ar.run_id
              WHERE ar.mailbox_id = me.mailbox_id
                AND ar.email_id = me.email_id
                AND a.artifact_type = 'translation'
                AND ar.status = 'success'
            ) THEN 1 ELSE 0
          END AS has_translation,
          CASE
            WHEN EXISTS (
              SELECT 1 FROM automation_run ar
              JOIN artifact a ON a.run_id = ar.run_id
              WHERE ar.mailbox_id = me.mailbox_id
                AND ar.email_id = me.email_id
                AND a.artifact_type = 'extracted_fields'
                AND ar.status = 'success'
            ) THEN 1 ELSE 0
          END AS has_extraction,
          CASE
            WHEN EXISTS (
              SELECT 1 FROM automation_run ar
              JOIN artifact a ON a.run_id = ar.run_id
              WHERE ar.mailbox_id = me.mailbox_id
                AND ar.email_id = me.email_id
                AND ar.status = 'success'
            ) THEN 0 ELSE 1
          END AS sort_has_artifact
        FROM mailbox_email me
        JOIN email e ON e.email_id = me.email_id
        LEFT JOIN message m ON m.id = e.provider_msg_id
        LEFT JOIN email_flag ef ON ef.mailbox_email_id = me.mailbox_email_id
        WHERE me.mailbox_id = ?
        ORDER BY sort_has_artifact, e.received_at DESC NULLS LAST
        LIMIT ? OFFSET ?
        """,
        (mailbox_id, limit, offset),
    ).fetchall()

    def _body(row):
        if not include_body:
            return None
        txt = (row[8] or "").strip()
        if txt:
            return txt[:4000] if len(txt) > 4000 else txt
        html = (row[9] or "").strip()
        if html:
            return html_to_text(html)[:4000]
        return None

    items = [
        {
            "mailbox_email_id": row[0],
            "email_id": row[1],
            "subject": row[2],
            "from_addr": row[3],
            "received_at": row[4],
            "category": row[5],
            "auto_category": row[6],
            "manual_category": row[7],
            "body_text": _body(row),
            "has_summary": row[10] or row[13],
            "last_action_status": row[11],
            "last_action_at": row[12],
            "has_draft_reply": row[14],
            "has_translation": row[15],
            "has_extraction": row[16],
        }
        for row in rows
    ]
    return {"status": "ok", "mailbox_id": mailbox_id, "items": items}


@app.get("/mailbox/{mailbox_id}/email/{email_id}")
def mailbox_email_detail(
    mailbox_id: str,
    email_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Return full email details: body, classification, classification history."""
    _set_db_path(db_path)
    con = store_db.connect()
    row = con.execute(
        """
        SELECT
          e.email_id,
          e.subject,
          e.from_addr,
          e.to_addrs,
          e.cc_addrs,
          e.received_at,
          e.body_text,
          e.body_html,
          m.id AS message_id,
          COALESCE(m.manual_category, m.category) AS category,
          m.urgency,
          m.updated_ts
        FROM mailbox_email me
        JOIN email e ON e.email_id = me.email_id
        LEFT JOIN message m ON m.id = e.provider_msg_id
        WHERE me.mailbox_id = ? AND me.email_id = ?
        """,
        (mailbox_id, email_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Email not found")
    message_id = row[8]
    body_text, body_html = row[6], row[7]
    if message_id:
        msg_row = con.execute(
            "SELECT body_text, body_html FROM message WHERE id = ?",
            (message_id,),
        ).fetchone()
        if msg_row and (msg_row[0] or msg_row[1]):
            body_text, body_html = msg_row[0], msg_row[1]
    classification_events = []
    if message_id:
        classification_events = con.execute(
            """
            SELECT category_auto, rule_name, confidence, created_ts
            FROM classification_event
            WHERE message_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (message_id,),
        ).fetchall()
    return {
        "status": "ok",
        "mailbox_id": mailbox_id,
        "email_id": row[0],
        "subject": row[1],
        "from_addr": row[2],
        "to_addrs": row[3],
        "cc_addrs": row[4],
        "received_at": row[5],
        "body_text": body_text,
        "body_html": body_html,
        "category": row[9],
        "urgency": row[10],
        "updated_ts": row[11],
        "classification_history": [
            {
                "category": r[0],
                "rule_name": r[1],
                "confidence": r[2],
                "created_ts": r[3],
            }
            for r in classification_events
        ],
    }


@app.get("/mailbox/{mailbox_id}/email/{email_id}/artifacts")
def mailbox_email_artifacts(
    mailbox_id: str,
    email_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    _set_db_path(db_path)
    con = store_db.connect()
    rows = con.execute(
        """
        SELECT DISTINCT ON (a.artifact_type)
          a.artifact_id,
          a.artifact_type,
          a.content_text,
          a.content_json,
          a.language,
          a.created_at,
          ar.run_id,
          ar.status,
          ar.params_json
        FROM artifact a
        JOIN automation_run ar ON ar.run_id = a.run_id
        WHERE ar.mailbox_id = ?
          AND ar.email_id = ?
          AND ar.status = 'success'
        ORDER BY a.artifact_type, a.created_at DESC NULLS LAST
        """,
        (mailbox_id, email_id),
    ).fetchall()
    items = [
        {
            "artifact_id": row[0],
            "artifact_type": row[1],
            "content_text": row[2],
            "content_json": row[3],
            "language": row[4],
            "created_at": row[5],
            "run_id": row[6],
            "run_status": row[7],
            "params_json": row[8],
        }
        for row in rows
    ]
    return {
        "status": "ok",
        "mailbox_id": mailbox_id,
        "email_id": email_id,
        "items": items,
    }


@app.get("/dataset/summary")
def dataset_summary(db_path: Optional[str] = None) -> Dict[str, Any]:
    _set_db_path(db_path)
    con = store_db.connect()

    def _table_has_column(table: str, column: str) -> bool:
        try:
            r = con.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = :t AND column_name = :c
                """,
                {"t": table, "c": column},
            ).fetchone()
            return r is not None
        except Exception:
            return False

    totals = {
        "raw_messages": con.execute("SELECT COUNT(*) FROM raw_message").fetchone()[0],
        "canonical_emails": con.execute("SELECT COUNT(*) FROM email").fetchone()[0],
        "mailbox_mappings": con.execute(
            "SELECT COUNT(*) FROM mailbox_email"
        ).fetchone()[0],
    }

    mailbox_counts = con.execute(
        "SELECT mailbox_id, COUNT(*) FROM mailbox_email GROUP BY mailbox_id"
    ).fetchall()
    mailbox_totals = [{"mailbox_id": row[0], "count": row[1]} for row in mailbox_counts]

    msg_window = con.execute(
        "SELECT MIN(received_dt), MAX(received_dt) FROM message"
    ).fetchone()
    email_window = con.execute(
        "SELECT MIN(received_at), MAX(received_at) FROM email"
    ).fetchone()

    attachment_total = con.execute("SELECT COUNT(*) FROM attachment").fetchone()[0]

    message_categories = con.execute(
        "SELECT COALESCE(category, 'unknown') AS category, COUNT(*) FROM message GROUP BY category"
    ).fetchall()
    classification_categories = con.execute(
        "SELECT category_auto, COUNT(*) FROM classification_event GROUP BY category_auto"
    ).fetchall()

    action_coverage = con.execute(
        "SELECT action_type, COUNT(*) FROM automation_run GROUP BY action_type"
    ).fetchall()
    artifact_types = con.execute(
        "SELECT artifact_type, COUNT(*) FROM artifact GROUP BY artifact_type"
    ).fetchall()

    language_distribution = []
    if _table_has_column("message", "language"):
        language_distribution = con.execute(
            "SELECT COALESCE(language, 'unknown') AS language, COUNT(*) FROM message GROUP BY language"
        ).fetchall()

    return {
        "status": "ok",
        "totals": totals,
        "mailbox_totals": mailbox_totals,
        "date_coverage": {
            "message_received_dt": {"min": msg_window[0], "max": msg_window[1]},
            "email_received_at": {"min": email_window[0], "max": email_window[1]},
        },
        "language_distribution": [
            {"language": row[0], "count": row[1]} for row in language_distribution
        ],
        "attachment_total": attachment_total,
        "category_distribution": {
            "message_category": [
                {"category": row[0], "count": row[1]} for row in message_categories
            ],
            "classification_event": [
                {"category": row[0], "count": row[1]}
                for row in classification_categories
            ],
        },
        "action_coverage": [
            {"action_type": row[0], "count": row[1]} for row in action_coverage
        ],
        "artifact_coverage": [
            {"artifact_type": row[0], "count": row[1]} for row in artifact_types
        ],
    }


class ManualLabelRequest(BaseModel):
    manual_category: str


@app.patch("/mailbox/{mailbox_id}/email/{email_id}/manual-category")
def set_manual_category(
    mailbox_id: str,
    email_id: str,
    req: ManualLabelRequest,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Set ground-truth label for evaluation. Use in Evaluation page for manual labeling."""
    _set_db_path(db_path)
    con = store_db.connect()
    # Resolve message via email.provider_msg_id
    msg_row = con.execute(
        """
        SELECT m.id FROM message m
        JOIN email e ON e.provider_msg_id = m.id
        JOIN mailbox_email me ON me.email_id = e.email_id
        WHERE me.mailbox_id = ? AND me.email_id = ?
        """,
        (mailbox_id, email_id),
    ).fetchone()
    if not msg_row:
        raise HTTPException(status_code=404, detail="Email not found in mailbox")
    msg_id = msg_row[0]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute(
        "UPDATE message SET manual_category = ?, updated_ts = ? WHERE id = ?",
        (req.manual_category, now, msg_id),
    )
    con.commit()
    return {
        "status": "ok",
        "message_id": msg_id,
        "manual_category": req.manual_category,
    }


@app.get("/evaluation/labeling-samples")
def labeling_samples(
    mailbox_id: str,
    limit: int = 50,
    per_category: int = 8,
    unlabeled_only: bool = True,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Stratified sample for manual labeling: up to per_category emails per auto_category."""
    _set_db_path(db_path)
    con = store_db.connect()
    unlabeled_clause = "AND m.manual_category IS NULL" if unlabeled_only else ""
    rows = con.execute(
        f"""
        WITH ranked AS (
            SELECT
                me.email_id,
                e.subject,
                e.from_addr,
                LEFT(COALESCE(m.body_text, ''), 600) AS body_text,
                m.category AS auto_category,
                m.manual_category,
                ROW_NUMBER() OVER (
                    PARTITION BY m.category
                    ORDER BY e.received_at DESC NULLS LAST
                ) AS rn
            FROM mailbox_email me
            JOIN email e ON e.email_id = me.email_id
            JOIN message m ON m.id = e.provider_msg_id
            WHERE me.mailbox_id = ?
              AND m.category IS NOT NULL
              {unlabeled_clause}
        )
        SELECT email_id, subject, from_addr, body_text, auto_category, manual_category
        FROM ranked
        WHERE rn <= ?
        ORDER BY auto_category, rn
        LIMIT ?
        """,
        (mailbox_id, per_category, limit),
    ).fetchall()
    items = [
        {
            "email_id": r[0],
            "subject": r[1],
            "from_addr": r[2],
            "body_text": r[3],
            "auto_category": r[4],
            "manual_category": r[5],
        }
        for r in rows
    ]
    # Count total labeled/unlabeled for progress
    counts = con.execute(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(m.manual_category) AS labeled
        FROM mailbox_email me
        JOIN email e ON e.email_id = me.email_id
        JOIN message m ON m.id = e.provider_msg_id
        WHERE me.mailbox_id = ?
        """,
        (mailbox_id,),
    ).fetchone()
    return {
        "status": "ok",
        "mailbox_id": mailbox_id,
        "items": items,
        "total_emails": counts[0] if counts else 0,
        "labeled_count": counts[1] if counts else 0,
    }


@app.get("/evaluation/classification-metrics")
def classification_metrics(
    mailbox_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Classification quality metrics: precision, recall, F1, confusion matrix.
    Only includes messages with manual_category (ground truth) set."""
    _set_db_path(db_path)
    con = store_db.connect()
    where = "WHERE m.manual_category IS NOT NULL"
    params: List[Any] = []
    if mailbox_id:
        where += """
            AND EXISTS (
                SELECT 1 FROM email e
                JOIN mailbox_email me ON me.email_id = e.email_id
                WHERE e.provider_msg_id = m.id AND me.mailbox_id = ?
            )
        """
        params.append(mailbox_id)
    rows = con.execute(
        f"""
        SELECT m.category AS predicted, m.manual_category AS actual
        FROM message m
        {where}
        """,
        tuple(params),
    ).fetchall()
    # Build confusion matrix: actual -> predicted -> count
    from collections import defaultdict

    cm = defaultdict(lambda: defaultdict(int))
    for pred, actual in rows:
        p = (pred or "unknown").strip()
        a = (actual or "unknown").strip()
        cm[a][p] += 1
    # Per-class metrics
    all_classes = set()
    for a in cm:
        all_classes.add(a)
        for p in cm[a]:
            all_classes.add(p)
    all_classes = sorted(all_classes)
    per_class = {}
    for c in all_classes:
        tp = cm.get(c, {}).get(c, 0)
        pred_total = sum(
            cm.get(x, {}).get(c, 0) for x in all_classes
        )  # all predicted as c
        actual_total = sum(cm.get(c, {}).values())  # all actually c
        prec = tp / pred_total if pred_total > 0 else 0
        rec = tp / actual_total if actual_total > 0 else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
        per_class[c] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
        }
    # Macro averages (standard: average of per-class scores)
    n = len(per_class)
    macro_prec = sum(p["precision"] for p in per_class.values()) / n if n else 0
    macro_rec = sum(p["recall"] for p in per_class.values()) / n if n else 0
    macro_f1 = sum(p["f1"] for p in per_class.values()) / n if n else 0
    # Flatten confusion matrix for JSON
    cm_flat = [
        {"actual": a, "predicted": p, "count": cnt}
        for a in sorted(cm.keys())
        for p, cnt in sorted(cm[a].items())
    ]
    return {
        "status": "ok",
        "labeled_count": len(rows),
        "macro": {
            "precision": round(macro_prec, 4),
            "recall": round(macro_rec, 4),
            "f1": round(macro_f1, 4),
        },
        "per_class": per_class,
        "confusion_matrix": cm_flat,
    }


@app.get("/audit/runs")
def audit_runs(
    mailbox_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Return execution history (automation runs) for evaluation and traceability."""
    _set_db_path(db_path)
    con = store_db.connect()
    where = "WHERE 1=1"
    params: List[Any] = []
    if mailbox_id:
        where += " AND ar.mailbox_id = ?"
        params.append(mailbox_id)
    params.extend([limit, offset])
    rows = con.execute(
        f"""
        SELECT ar.run_id, ar.mailbox_id, ar.email_id, ar.action_type, ar.status,
               ar.started_at, ar.finished_at, ar.model_name, ar.error_message,
               e.subject
        FROM automation_run ar
        LEFT JOIN email e ON e.email_id = ar.email_id
        {where}
        ORDER BY ar.started_at DESC NULLS LAST
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()
    total_runs = con.execute("SELECT COUNT(*) FROM automation_run").fetchone()[0]
    success_count = con.execute(
        "SELECT COUNT(*) FROM automation_run WHERE status = 'success'"
    ).fetchone()[0]
    failed_count = con.execute(
        "SELECT COUNT(*) FROM automation_run WHERE status = 'failed'"
    ).fetchone()[0]
    return {
        "status": "ok",
        "items": [
            {
                "run_id": r[0],
                "mailbox_id": r[1],
                "email_id": r[2],
                "action_type": r[3],
                "status": r[4],
                "started_at": r[5],
                "finished_at": r[6],
                "model_name": r[7],
                "error_message": r[8],
                "subject": r[9],
            }
            for r in rows
        ],
        "total_runs": total_runs,
        "success_count": success_count,
        "failed_count": failed_count,
    }


class IngestRequest(BaseModel):
    mailbox_id: str
    mailbox_type: str = Field(default="personal")
    pages: int = 1
    top: int = 100
    parse_limit: int = 250
    db_path: Optional[str] = None


@app.post("/pipeline/ingest")
def pipeline_ingest(req: IngestRequest) -> Dict[str, Any]:
    _set_db_path(req.db_path)
    # enron_import: skip Graph fetch (data comes from CSV import)
    if req.mailbox_id == "enron_import":
        ingest_result = {"status": "skipped", "ingested_count": 0, "dry_run": False}
    else:
        ingest_result = ingest_raw.ingest_graph_messages(
            mailbox_id=req.mailbox_id,
            mailbox_type=req.mailbox_type,
            pages=req.pages,
            top=req.top,
            dry_run=False,
        )
    parse_result = parse_load.process_new_raw_messages(
        limit=req.parse_limit,
        mailbox_id=req.mailbox_id,
        dry_run=False,
    )
    # Corpus snapshot: reference for evaluation (size + time coverage at retrieval)
    from datetime import datetime, timezone

    corpus = dataset_summary()
    corpus_snapshot = {
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ingest_params": {
            "mailbox_id": req.mailbox_id,
            "pages": req.pages,
            "top": req.top,
        },
        "totals": corpus.get("totals", {}),
        "date_coverage": corpus.get("date_coverage", {}),
    }
    return {
        "status": "ok",
        "ingest": ingest_result,
        "parse": parse_result,
        "corpus_snapshot": corpus_snapshot,
    }


class AutomateRequest(BaseModel):
    mailbox_id: str
    user_id: str
    org_id: str
    limit: int = 25
    min_confidence: float = 0.7
    classify_all: bool = False
    update_message_category: bool = True
    db_path: Optional[str] = None


@app.post("/pipeline/automate")
def pipeline_automate(req: AutomateRequest) -> Dict[str, Any]:
    _set_db_path(req.db_path)
    cfg = db_ops.get_user_config(req.user_id)
    if cfg.get("status") != "ok":
        raise HTTPException(status_code=400, detail="User config not found")
    preferences = json.loads(cfg.get("preferences_json") or "{}")
    classifications = json.loads(cfg.get("classifications_json") or "{}")
    candidates = db_ops.select_llm_candidates(
        mailbox_id=req.mailbox_id,
        limit=req.limit,
        min_confidence=None if req.classify_all else req.min_confidence,
    )
    allowed_labels = set(classifications.keys())

    processed: List[Dict[str, Any]] = []
    for item in candidates:
        label_descriptions = "\n".join(
            f"- {k}: {v}" for k, v in classifications.items()
        )
        class_prompt = (
            "You classify emails into exactly one category. "
            'Return JSON only: {"label":"...", "confidence":0.0-1.0}. '
            "Pick the single best category based on the PRIMARY purpose of the email. "
            "Research = only formal research reports, analyst notes, or market analysis publications. "
            "Short replies, questions, scheduling, or forwarded messages are NOT Research. "
            "If unsure, prefer General or Other over Research."
        )
        user_prompt = (
            f"Categories:\n{label_descriptions}\n\n"
            f"From: {item.get('from_addr')}\n"
            f"Subject: {item.get('subject')}\n"
            f"Body: {item.get('body_text')}"
        )
        classification = _openai_json(class_prompt, user_prompt)
        raw_label = str(classification.get("label") or "").strip()
        if raw_label not in allowed_labels:
            raw_label = (
                "other"
                if "other" in allowed_labels
                else (next(iter(allowed_labels), "other"))
            )
        classification["label"] = raw_label
        classification["classification_id"] = raw_label
        event_id = db_ops.insert_llm_classification(
            message_id=item["id"],
            label=classification.get("label", "other"),
            confidence=float(classification.get("confidence", 0.85)),
            rule_name="llm_class_v1",
            update_message=req.update_message_category,
        )
        classification["classification_id"] = event_id

        actions = _build_actions(
            preferences=preferences,
            classification=classification,
            config_version=cfg.get("config_version"),
        )
        if not actions:
            processed.append({"message_id": item["id"], "status": "skipped"})
            continue

        for action in actions:
            canonical_email_id = item.get("email_id") or item["id"]
            start = db_ops.start_automation_run(
                org_id=req.org_id,
                mailbox_id=req.mailbox_id,
                email_id=canonical_email_id,
                action_type=action["type"],
                input_json=action["input_json"],
                preference_id=req.user_id,
                model_name=OPENAI_MODEL,
                params_json=action["params_json"],
            )
            if start.get("status") == "duplicate":
                processed.append(
                    {
                        "message_id": item["id"],
                        "status": "duplicate",
                        "run_id": start.get("run_id"),
                    }
                )
                continue

            try:
                action_type = action["type"]
                if action_type == "summarize":
                    params = action.get("params") or {}
                    instr = "Summarize the email. "
                    if params.get("max_bullets"):
                        instr += f"Use at most {params['max_bullets']} bullet points. "
                    if params.get("format") == "bullets":
                        instr += "Format as bullet points. "
                    elif params.get("format") == "paragraph":
                        instr += "Format as a short paragraph. "
                    instr += f"Style: {params.get('style', 'client_friendly')}. Length: {params.get('length', 'short')}."
                    system_prompt = (
                        'Return JSON only. Output schema: {"summary_text":"..."}'
                    )
                    user_prompt = (
                        f"{instr}\n\n"
                        f"From: {item.get('from_addr')}\n"
                        f"Subject: {item.get('subject')}\n"
                        f"Body: {item.get('body_text')}"
                    )
                    summary = _openai_json(system_prompt, user_prompt)
                    db_ops.insert_action_artifact(
                        run_id=start["run_id"],
                        email_id=canonical_email_id,
                        artifact_type="summary",
                        content_text=summary.get("summary_text"),
                        content_json=None,
                        language=None,
                        content_ptr=None,
                        artifact_id=None,
                    )
                elif action_type == "draft_reply":
                    system_prompt = (
                        "Return JSON only. Output schema: " '{"draft_reply":"..."}'
                    )
                    user_prompt = (
                        f"From: {item.get('from_addr')}\n"
                        f"Subject: {item.get('subject')}\n"
                        f"Body: {item.get('body_text')}\n"
                        f"Params: {action.get('params')}"
                    )
                    draft = _openai_json(system_prompt, user_prompt)
                    db_ops.insert_action_artifact(
                        run_id=start["run_id"],
                        email_id=canonical_email_id,
                        artifact_type="draft_reply",
                        content_text=draft.get("draft_reply"),
                        content_json=None,
                        language=None,
                        content_ptr=None,
                        artifact_id=None,
                    )
                elif action_type == "translate":
                    system_prompt = (
                        "Return JSON only. Output schema: "
                        '{"translated_text":"...", "language":"..."}'
                    )
                    user_prompt = (
                        f"Target language: {action.get('params', {}).get('target_language')}\n"
                        f"From: {item.get('from_addr')}\n"
                        f"Subject: {item.get('subject')}\n"
                        f"Body: {item.get('body_text')}"
                    )
                    translated = _openai_json(system_prompt, user_prompt)
                    db_ops.insert_action_artifact(
                        run_id=start["run_id"],
                        email_id=canonical_email_id,
                        artifact_type="translation",
                        content_text=translated.get("translated_text"),
                        content_json=None,
                        language=translated.get("language"),
                        content_ptr=None,
                        artifact_id=None,
                    )
                elif action_type == "extract":
                    schema_hint = action.get("params", {}).get("schema_hint") or ""
                    system_prompt = (
                        "You are a structured data extractor. "
                        'Return JSON only, with this exact shape: {"extracted_fields": {"<field>": <value or null>}}. '
                        "Extract ONLY the fields listed in the schema hint from the email body. "
                        "Use null for any field not found. "
                        "Never include metadata fields like 'from', 'subject', or 'body' unless explicitly listed in the schema hint. "
                        "Values must come from the email content, not be invented."
                    )
                    user_prompt = (
                        f"Extract these fields: {schema_hint}\n\n"
                        f"Subject: {item.get('subject')}\n"
                        f"Body:\n{item.get('body_text')}"
                    )
                    extracted = _openai_json(system_prompt, user_prompt)
                    db_ops.insert_action_artifact(
                        run_id=start["run_id"],
                        email_id=canonical_email_id,
                        artifact_type="extracted_fields",
                        content_text=None,
                        content_json=json.dumps(extracted.get("extracted_fields")),
                        language=None,
                        content_ptr=None,
                        artifact_id=None,
                    )
                else:
                    raise HTTPException(
                        status_code=400, detail=f"Unknown action type: {action_type}"
                    )

                db_ops.finish_automation_run(
                    run_id=start["run_id"],
                    status="success",
                    error_message=None,
                    model_name=OPENAI_MODEL,
                    params_json=action["params_json"],
                )
                db_ops.update_email_flag_for_action(
                    mailbox_id=req.mailbox_id,
                    email_id=canonical_email_id,
                    action_type=action_type,
                    status="success",
                )
                processed.append(
                    {
                        "message_id": item["id"],
                        "status": "success",
                        "run_id": start["run_id"],
                    }
                )
            except HTTPException as exc:
                db_ops.finish_automation_run(
                    run_id=start["run_id"],
                    status="failed",
                    error_message=str(exc.detail),
                    model_name=OPENAI_MODEL,
                    params_json=action["params_json"],
                )
                db_ops.update_email_flag_for_action(
                    mailbox_id=req.mailbox_id,
                    email_id=item["id"],
                    action_type=action["type"],
                    status="failed",
                )
                raise
            except Exception as exc:
                db_ops.finish_automation_run(
                    run_id=start["run_id"],
                    status="failed",
                    error_message=str(exc),
                    model_name=OPENAI_MODEL,
                    params_json=action["params_json"],
                )
                db_ops.update_email_flag_for_action(
                    mailbox_id=req.mailbox_id,
                    email_id=item["id"],
                    action_type=action["type"],
                    status="failed",
                )
                processed.append(
                    {
                        "message_id": item["id"],
                        "status": "failed",
                        "run_id": start["run_id"],
                        "error": str(exc),
                    }
                )

    return {"status": "ok", "processed": processed}
