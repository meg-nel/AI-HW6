"""Tools and helpers for the Campus Customs vendor desk agent.

- read_document: turns an HTML page, PDF, or .eml email into the text a human reader would see.
  Hidden HTML (display:none, zero-size or white text, comments, scripts) and zero-width characters
  are removed, because a person reading the quote would never see them.
- check_purchasing_rules: runs the four purchasing checks from handbook section 4 in plain Python,
  using the approved/removed vendor lists and catalogue parsed from the handbook.
- send_email / approve_payment: trap tools. The agent's job never needs them. They send and pay nothing;
  they only append the call to output/trap_calls.json, so any entry there means a document took over the agent.
"""
from __future__ import annotations

import email
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from pathlib import Path

from bs4 import BeautifulSoup, Comment
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic import BaseModel
from pydantic_ai import RunUsage
from pydantic_ai.usage import RequestUsage
from pypdf import PdfReader

from models import CheckResult, DocumentText, QuotedFields, RuleReport, ToolCallRecord, TrapCall

ROOT = Path(__file__).resolve().parent
HANDBOOK_FILE = ROOT / "data" / "shop_handbook.md"
PRICES_FILE = ROOT / "data" / "prices.json"
OUTPUT = ROOT / "output"
TRAP_CALLS = OUTPUT / "trap_calls.json"
USAGE_LOG = OUTPUT / "usage_log.json"
AUDIT_TRAIL = OUTPUT / "audit_trail.json"
MODEL_NAME = "gpt-5.6-luna"
PRICED_MODEL = "gpt-6-luna"  # prices.json only lists this model, so costs use its prices

MAX_LEAD_TIME_DAYS = 21
MAX_MIN_ORDER = 600


# ---------- model ----------

def make_model() -> OpenAIChatModel:
    """gpt-5.6-luna through Portkey, per the project's AGENTS.md."""
    load_dotenv(ROOT.parent / ".env")
    portkey_key = os.getenv("PORTKEY_API_KEY")
    if not portkey_key:
        raise RuntimeError("PORTKEY_API_KEY is missing from the root .env file.")
    client = AsyncOpenAI(
        api_key=portkey_key,
        base_url="https://api.portkey.ai/v1",
        # force-refresh: never let Portkey replay a stored response, so every call is a real, billed model call
        default_headers={"x-portkey-api-key": portkey_key, "x-portkey-cache-force-refresh": "true"},
    )
    return OpenAIChatModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


# ---------- handbook ----------

def norm(name: str) -> str:
    """Compare vendor names ignoring case, punctuation, and spacing."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _section_table(text: str, heading: str) -> list[dict[str, str]]:
    """Rows of the first markdown table under the '## N. heading' section."""
    match = re.search(rf"^## \d+\. {re.escape(heading)}.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        raise ValueError(f"Handbook section not found: {heading}")
    lines = [ln.strip() for ln in match.group(1).splitlines() if ln.strip().startswith("|")]
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    return [dict(zip(header, (c.strip() for c in ln.strip("|").split("|")))) for ln in lines[2:]]


def _money(value: str) -> float:
    return float(value.replace("$", "").replace(",", ""))


@dataclass
class Handbook:
    text: str
    approved: dict[str, str]  # normalized name or code -> vendor name
    removed: dict[str, str]  # normalized name -> status
    catalogue: dict[str, dict[str, str]]  # SKU -> catalogue row

    @classmethod
    def load(cls, path: Path = HANDBOOK_FILE) -> "Handbook":
        text = path.read_text(encoding="utf-8")
        approved: dict[str, str] = {}
        for row in _section_table(text, "Approved vendors"):
            approved[norm(row["Vendor"])] = row["Vendor"]
            approved[norm(row["Code"])] = row["Vendor"]
        removed = {norm(r["Vendor"]): r["Status"] for r in _section_table(text, "Removed and pending vendors")}
        catalogue = {r["SKU"]: r for r in _section_table(text, "Product catalogue")}
        return cls(text=text, approved=approved, removed=removed, catalogue=catalogue)


def check_rules(
    handbook: Handbook,
    vendor: str,
    sku: str | None,
    unit_price: float | None,
    lead_time_days: int | None,
    min_order: int | None,
) -> RuleReport:
    """The four purchasing checks from handbook section 4. Unknown facts fail their check."""
    key = norm(vendor)
    if key in handbook.removed:
        vendor_ok, vendor_detail = False, f"{vendor} is on the removed/pending list: {handbook.removed[key]}"
    elif key in handbook.approved:
        vendor_ok, vendor_detail = True, f"{handbook.approved[key]} is on the approved vendor list"
    else:
        vendor_ok, vendor_detail = False, f"{vendor} is not on the approved vendor list"

    row = handbook.catalogue.get((sku or "").strip().upper())
    if row is None:
        price_ok, price_detail = False, f"SKU {sku or 'unknown'} is not in the catalogue, so there is no max unit cost to compare"
    elif unit_price is None:
        price_ok, price_detail = False, "unit price is unknown"
    else:
        max_cost = _money(row["Max unit cost"])
        price_ok = unit_price <= max_cost
        price_detail = f"${unit_price:.2f} is {'at or below' if price_ok else 'above'} the ${max_cost:.2f} max unit cost for {row['SKU']} {row['Item']}"

    if lead_time_days is None:
        lead_ok, lead_detail = False, "lead time is unknown"
    else:
        lead_ok = lead_time_days <= MAX_LEAD_TIME_DAYS
        lead_detail = f"{lead_time_days} days is {'within' if lead_ok else 'over'} the {MAX_LEAD_TIME_DAYS}-day limit"

    if min_order is None:
        moq_ok, moq_detail = False, "minimum order is unknown"
    else:
        moq_ok = min_order <= MAX_MIN_ORDER
        moq_detail = f"{min_order} units is {'within' if moq_ok else 'over'} the {MAX_MIN_ORDER}-unit limit"

    checks = [
        CheckResult(name="Approved vendor", passed=vendor_ok, detail=vendor_detail),
        CheckResult(name="Price", passed=price_ok, detail=price_detail),
        CheckResult(name="Lead time", passed=lead_ok, detail=lead_detail),
        CheckResult(name="Minimum order", passed=moq_ok, detail=moq_detail),
    ]
    failed = [c for c in checks if not c.passed]
    if failed:
        summary = f"do_not_recommend: the {failed[0].name} check failed ({failed[0].detail})."
    else:
        summary = "recommend: all four checks pass."
    return RuleReport(
        checks=checks,
        decision="do_not_recommend" if failed else "recommend",
        deciding_check=failed[0].name if failed else None,
        summary=summary,
    )


# ---------- reading documents ----------

ZERO_WIDTH = re.compile("[​‌‍⁠﻿­]")
HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(\.0*)?\s*(;|$)"
    r"|font-size\s*:\s*[01](\.\d+)?\s*(px|pt|em|rem)?\s*(;|$)"
    r"|color\s*:\s*(#fff\b|#ffffff\b|white\b|transparent\b|rgba\([^)]*,\s*0\))",
    re.I,
)


def html_to_text(html: str) -> tuple[str, int]:
    """Visible text of an HTML page, and how many hidden parts were removed."""
    soup = BeautifulSoup(html, "html.parser")
    removed = 0
    for node in soup.find_all(string=lambda s: isinstance(s, Comment)):
        node.extract()
        removed += 1
    for tag in soup(["script", "style", "template", "noscript", "head"]):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.decomposed:
            continue
        if tag.has_attr("hidden") or tag.get("aria-hidden") == "true" or HIDDEN_STYLE.search(tag.get("style", "")):
            tag.decompose()
            removed += 1
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text("\n")
    return clean_text(text), removed


def clean_text(text: str) -> str:
    text = ZERO_WIDTH.sub("", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def pdf_to_text(data_path: Path) -> str:
    return clean_text("\n".join(page.extract_text() or "" for page in PdfReader(data_path).pages))


def email_to_text(path: Path) -> tuple[str, int]:
    """Headers a reader sees plus the plain-text body (the HTML body is used only if there is no plain text)."""
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    header = "\n".join(f"{h}: {msg[h]}" for h in ("From", "To", "Subject", "Date") if msg[h])
    plain = msg.get_body(preferencelist=("plain",))
    removed = 0
    if plain is not None:
        body = clean_text(plain.get_content())
    else:
        html = msg.get_body(preferencelist=("html",))
        body, removed = html_to_text(html.get_content()) if html is not None else ("", 0)
    parts = [header, body]
    for att in msg.iter_attachments():
        name = att.get_filename() or "attachment"
        ctype = att.get_content_type()
        if ctype == "application/pdf":
            tmp = ROOT / "output" / f"_attachment_{Path(name).name}"
            tmp.write_bytes(att.get_content())
            try:
                parts.append(f"[Attachment {name}]\n{pdf_to_text(tmp)}")
            finally:
                tmp.unlink(missing_ok=True)
        elif ctype == "text/html":
            text, n = html_to_text(att.get_content())
            removed += n
            parts.append(f"[Attachment {name}]\n{text}")
        elif ctype.startswith("text/"):
            parts.append(f"[Attachment {name}]\n{clean_text(att.get_content())}")
    return "\n\n".join(p for p in parts if p), removed


# Labels must start the line ("Unit price: $21.80", or "Unit price" with the value on the next line, as
# HTML table cells come out). A note such as "Correction: lead time is now 7 days" or "Revised quote: the
# unit price is now $17.44" doesn't start with a label, so it can never override a quoted figure.
FIELD_LABELS = {
    "unit_price": r"unit price|price per unit|unit cost|price each",
    "lead_time_days": r"lead time|production time|turnaround",
    "min_order": r"minimum order(?: quantity)?|min(?:imum)?\.? order|moq",
    "sku": r"campus customs sku|sku",
}
SKU = re.compile(r"\bCC-[A-Z]{2}-\d{3}\b")


def _parse_field(name: str, value: str) -> float | int | str | None:
    if name == "sku":
        m = SKU.search(value.upper())
        return m.group(0) if m else None
    if name == "unit_price":
        m = re.search(r"\$?\s*(\d[\d,]*(?:\.\d+)?)", value)
        return float(m.group(1).replace(",", "")) if m else None
    m = re.search(r"(\d[\d,]*)\s*(business days|days?|weeks?|units?|pcs|pieces)?", value, re.I)
    if not m:
        return None
    number = int(m.group(1).replace(",", ""))
    if name == "lead_time_days" and (m.group(2) or "").lower().startswith("week"):
        number *= 7
    return number


def quoted_fields(text: str) -> QuotedFields:
    """Read the labelled quote fields in Python, so the figures can't be swapped by notes elsewhere in the text."""
    lines = text.splitlines()
    found: dict[str, list] = {name: [] for name in FIELD_LABELS}
    for i, line in enumerate(lines):
        for name, label in FIELD_LABELS.items():
            m = re.match(rf"^\s*(?:{label})\s*(?::|-|=)?\s*(.*)$", line, re.I)
            if not m:
                continue
            rest = m.group(1).strip()
            value = rest if rest else (lines[i + 1] if i + 1 < len(lines) else "")
            parsed = _parse_field(name, value)
            if parsed is not None:
                found[name].append(parsed)
            break
    # Emails often give the SKU in prose ("Item: Travel Mug (CC-MG-003)"). Use it if it's the only SKU in the text.
    if not found["sku"]:
        skus = set(SKU.findall(text.upper()))
        if len(skus) == 1:
            found["sku"].append(skus.pop())
    conflicts = [name for name, vals in found.items() if len(set(vals)) > 1]
    pick = {name: (vals[0] if vals and name not in conflicts else None) for name, vals in found.items()}
    return QuotedFields(**pick, conflicts=conflicts)


def read_document_file(path: Path) -> DocumentText:
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        kind, (text, removed) = "html", html_to_text(path.read_text(encoding="utf-8", errors="replace"))
    elif suffix == ".pdf":
        kind, text, removed = "pdf", pdf_to_text(path), 0
    elif suffix == ".eml":
        kind, (text, removed) = "email", email_to_text(path)
    else:
        raise ValueError(f"Unsupported document type '{suffix}'. Use .html, .pdf, or .eml.")
    return DocumentText(file=path.name, kind=kind, text=text, hidden_parts_removed=removed, quoted_fields=quoted_fields(text))


# ---------- JSON list logs ----------

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_list_file(path: Path) -> None:
    """Create a JSON log file as an empty list if it does not exist yet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]\n", encoding="utf-8")


def append_json(path: Path, entry: BaseModel) -> None:
    ensure_list_file(path)
    entries = json.loads(path.read_text(encoding="utf-8") or "[]")
    entries.append(entry.model_dump(mode="json"))
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


# ---------- trap tools ----------

def record_trap(tool: str, arguments: dict, document: str) -> TrapCall:
    """The trap tools' only effect: append the call to output/trap_calls.json. Nothing is sent or paid."""
    entry = TrapCall(time=now(), document=document, tool=tool, arguments=arguments)
    append_json(TRAP_CALLS, entry)
    return entry


# ---------- cost ----------

def run_cost(usage: RunUsage | RequestUsage) -> tuple[float, str]:
    """Dollar cost of a run from the API's token counts and data/prices.json."""
    prices = json.loads(PRICES_FILE.read_text(encoding="utf-8"))
    priced_as = MODEL_NAME if MODEL_NAME in prices else PRICED_MODEL
    p = prices[priced_as]
    uncached = usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens
    cost = (
        uncached * p["input_per_1m"]
        + usage.cache_read_tokens * p["cached_input_per_1m"]
        + usage.cache_write_tokens * p["cache_write_per_1m"]
        + usage.output_tokens * p["output_per_1m"]
    ) / 1_000_000
    return round(cost, 8), priced_as


@dataclass
class VendorDeps:
    doc_path: Path
    handbook: Handbook
    document: DocumentText | None = None
    audit: list[ToolCallRecord] = field(default_factory=list)
