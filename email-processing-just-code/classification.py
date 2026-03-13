"""
Helpers for classifying emails.

Includes:
  * Rule-based classifier (fast baseline)
  * Optional LLM fallback for low-confidence cases
  * Utilities for text normalization + urgency detection
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Iterable, Optional

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

CANONICAL_LABELS = [
    "Trades",
    "Client",
    "Internal",
    "Market",
    "Materials",
    "Research",
    "Other",
]

CATEGORY_ALIASES = {
    "trade idea": "Trades",
    "trade": "Trades",
    "trade_ideas": "Trades",
    "client": "Client",
    "internal": "Internal",
    "internal_queries": "Internal",
    "internal_operations": "Internal",
    "update": "Market",
    "market": "Market",
    "materials": "Materials",
    "research": "Research",
    "project_and_research": "Research",
    "other": "Other",
    "vendor_management": "Other",
    "regulatory_and_external": "Other",
    # Consolidated categories (Enron)
    "financial": "Financial",
    "financial_transactions": "Financial",
    "financial_and_contracts": "Financial",
    "financial_analysis": "Financial",
    "financial_records": "Financial",
    "general": "General",
    "general_communications": "General",
    "project_updates": "General",
    "meeting_arrangements": "General",
    "meeting_and_scheduling": "General",
    "external": "External",
    "external_communications": "External",
    # Consolidated categories (me)
    "security": "Security",
    "account_security_events": "Security",
    "service_subscription_notifications": "Security",
}

TRADE = re.compile(
    r"\b(buy|sell|long|short|pay|receive|entry|exit|target|stop|tp|sl|rv|curve|spread)\b",
    re.I,
)
TENOR = re.compile(
    r"\b(\d{1,2}y|\d{1,2}m|\d{1,2}w|\d{1,2}d|[23]m|6m|2s10s|5s30s)\b", re.I
)
CLIENT = re.compile(r"\b(client|rfq|enquiry|request|mandate|escalate)\b", re.I)
INTERNAL = re.compile(
    r"\b(internal|rota|shift|coverage|action required|approval|review|handover)\b", re.I
)
MARKET = re.compile(
    r"\b(market update|am bullet|pm bullet|opening bell|futures|headline|color|wrap|snapshot)\b",
    re.I,
)
MATERIALS = re.compile(
    r"\b(attached|attachment|slides|deck|pptx|pdf|chartbook|appendix)\b", re.I
)
RESEARCH = re.compile(
    r"\b(research report|research note|market research|industry analysis|publication|house view|analyst report)\b",
    re.I,
)

URG_HIGH = re.compile(r"\b(urgent|asap|eod|today|now|immediately|deadline)\b", re.I)
URG_MED = re.compile(r"\b(soon|tomorrow|this week|eow)\b", re.I)


def detect_urgency(subject: Optional[str], body: Optional[str]) -> str:
    text = f"{subject or ''}\n{body or ''}"
    if URG_HIGH.search(text):
        return "high"
    if URG_MED.search(text):
        return "medium"
    return "none"


def html_to_text(raw_html: Optional[str]) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for blockquote in soup.select("blockquote"):
        blockquote.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_label(label: Optional[str]) -> str:
    if not label:
        return "Other"
    key = label.strip().lower()
    return CATEGORY_ALIASES.get(key, label if label in CANONICAL_LABELS else "Other")


@dataclass
class ClassificationResult:
    label: str
    confidence: float
    source: str
    detail: Optional[str] = None


class RuleBasedClassifier:
    """Lightweight deterministic classifier."""

    def classify(
        self, subject: str, body: str, from_addr: Optional[str] = None
    ) -> ClassificationResult:
        subject = subject or ""
        body = body or ""
        domain = (
            (from_addr or "").split("@")[-1].lower()
            if from_addr and "@" in from_addr
            else ""
        )

        if TRADE.search(subject) or (TRADE.search(body) and TENOR.search(body)):
            return ClassificationResult("Trades", 0.92, "rules", "trade_keywords")
        if CLIENT.search(subject) or CLIENT.search(body):
            return ClassificationResult("Client", 0.8, "rules", "client_language")
        if (
            domain.endswith(".internal")
            or INTERNAL.search(subject)
            or INTERNAL.search(body)
        ):
            return ClassificationResult("Internal", 0.75, "rules", "internal_terms")
        if MARKET.search(subject) or MARKET.search(body):
            return ClassificationResult("Market", 0.7, "rules", "market_update")
        if MATERIALS.search(subject) or MATERIALS.search(body):
            return ClassificationResult(
                "Materials", 0.65, "rules", "materials_reference"
            )
        if RESEARCH.search(subject) or RESEARCH.search(body):
            return ClassificationResult("Research", 0.6, "rules", "research_terms")
        return ClassificationResult("Other", 0.3, "rules", "fallback_no_match")


class LLMEmailClassifier:
    """
    Calls an LLM endpoint (OpenAI-compatible) to classify emails.
    Requires OPENAI_API_KEY. Only instantiated when explicitly enabled.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
        temperature: float = 0.0,
    ):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("Set OPENAI_API_KEY to enable LLM classification.")
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.endpoint = endpoint or os.getenv(
            "LLM_ENDPOINT", "https://api.openai.com/v1/chat/completions"
        )
        self.temperature = temperature

    def classify(
        self, subject: str, body: str, from_addr: Optional[str] = None
    ) -> ClassificationResult:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You classify emails into exactly one category. "
                        "Categories:\n"
                        "- Research: formal research reports, analyst notes, market analysis publications\n"
                        "- Financial: transactions, contracts, deals, trades, pricing, buyouts\n"
                        "- General: scheduling, general updates, FYI, greetings, courtesy replies\n"
                        "- Internal: company-internal operations, HR, IT, approvals, processes\n"
                        "- External: communication with outside parties, clients, vendors\n"
                        "- Materials: documents, attachments, reference files, slide decks\n"
                        "- Other: personal, spam, or anything not fitting above categories\n"
                        "Short replies, questions, or forwarded messages are NOT Research. "
                        "If unsure, prefer General or Other over Research. "
                        'Respond with JSON: {"label":"...","rationale":"..."}.'
                    ),
                },
                {
                    "role": "user",
                    "content": f"From: {from_addr or 'unknown'}\nSubject: {subject}\nBody:\n{body[:4000]}",
                },
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        try:
            message = data["choices"][0]["message"]["content"]
            parsed = json.loads(message)
        except (KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Failed to parse LLM response: {data}") from exc
        label = normalize_label(parsed.get("label"))
        rationale = parsed.get("rationale")
        return ClassificationResult(label, 0.85, "llm", rationale)


class HybridClassifier:
    """Rule-based baseline with optional LLM fallback for low-confidence results."""

    def __init__(self, enable_llm: Optional[bool] = None, threshold: float = 0.7):
        self.rules = RuleBasedClassifier()
        self.threshold = threshold
        env_flag = os.getenv("USE_LLM_CLASSIFIER", "").lower()
        self.enable_llm = (
            enable_llm if enable_llm is not None else env_flag in {"1", "true", "yes"}
        )
        self._llm: Optional[LLMEmailClassifier] = None

    def _get_llm(self) -> Optional[LLMEmailClassifier]:
        if not self.enable_llm:
            return None
        if not self._llm:
            self._llm = LLMEmailClassifier()
        return self._llm

    def classify(
        self, subject: str, body: str, from_addr: Optional[str] = None
    ) -> ClassificationResult:
        result = self.rules.classify(subject, body, from_addr)
        if result.confidence >= self.threshold:
            return result
        llm = self._get_llm()
        if not llm:
            return result
        try:
            return llm.classify(subject, body, from_addr)
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("LLM classification failed, returning rule result: %s", exc)
            return result


def export_rows(rows: Iterable[dict], path: str) -> None:
    """Utility for downstream scripts that want to dump JSON."""
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
