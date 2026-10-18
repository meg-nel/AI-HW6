"""Tools and helpers for the Campus Customs vendor desk agent.

- read_document_file (code layer): turns an HTML page, PDF, or .eml email into the text a human reader
  would see. Hidden HTML (display:none, zero-size or white text, comments, scripts), hidden PDF text
  (tiny, off-page, or white), and zero-width characters are removed; suspicious notes are flagged.
- raw_text: the no-defenses reader. Returns everything in the file, hidden text included.
- check_rules: the four purchasing checks from handbook section 4 in plain Python, using the approved/removed
  vendor lists and catalogue parsed from the handbook.
- send_email / approve_payment: never send or pay anything. Without a HumanSignoff they refuse and append the
  attempt to output/trap_calls.json (any entry there means a document took over the agent). With a sign-off
  they are only logged to output/approved_actions.json for now.
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

from models import CheckResult, DocumentText, HumanSignoff, QuotedFields, RuleReport, ToolCallRecord, TrapCall

ROOT = Path(__file__).resolve().parent
HANDBOOK_FILE = ROOT / "data" / "shop_handbook.md"
PRICES_FILE = ROOT / "data" / "prices.json"
OUTPUT = ROOT / "output"
TRAP_CALLS = OUTPUT / "trap_calls.json"
USAGE_LOG = OUTPUT / "usage_log.json"
AUDIT_TRAIL = OUTPUT / "audit_trail.json"
APPROVED_ACTIONS = OUTPUT / "approved_actions.json"
MODEL_NAME = "gpt-5.6-luna"
PRICED_MODEL = "gpt-6-luna"  # prices.json only lists this model, so costs use its prices

MAX_LEAD_TIME_DAYS = 21
MAX_MIN_ORDER = 600


# ---------- model ----------

def make_model() -> OpenAIChatModel:
    """gpt-5.6-luna through Portkey, per the project's AGENTS.md."""
    load_dotenv(ROOT / ".env")  # a .env in this project folder (copy .env.example), if there is one
    load_dotenv(ROOT.parent / ".env")  # otherwise the course's root .env
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


# Moved out of view or squeezed to nothing: off-screen offsets, clipping, zero-size scaling.
OFFSCREEN_STYLE = re.compile(
    r"(?:left|right|top|text-indent|margin-left|margin-top)\s*:\s*-\s*\d{3,}"
    r"|clip\s*:\s*rect\(\s*0|clip-path\s*:\s*inset\(\s*(?:50|100)%|transform\s*:\s*scale\(\s*0[,)\s]"
    r"|max-(?:height|width)\s*:\s*0(?:px)?\s*(?:;|$)",
    re.I,
)
TINY_BOX = re.compile(r"(?:width|height)\s*:\s*[01](?:px)?\s*(?:;|$)", re.I)


def hides(style: str) -> bool:
    """True if a CSS declaration block makes its element invisible to a reader."""
    if HIDDEN_STYLE.search(style) or OFFSCREEN_STYLE.search(style):
        return True
    return bool(TINY_BOX.search(style) and re.search(r"overflow\s*:\s*hidden", style, re.I))


def stylesheet_hidden(soup: BeautifulSoup) -> list:
    """Elements hidden by rules in <style> blocks (e.g. a .sr-only class), not by an inline style."""
    found = []
    for style in soup.find_all("style"):
        css = re.sub(r"/\*.*?\*/", "", style.get_text(), flags=re.S)
        for selectors, block in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
            if not hides(block):
                continue
            for selector in selectors.split(","):
                selector = selector.strip()
                if not selector or ":" in selector:  # skip pseudo-classes like :hover
                    continue
                try:
                    found += soup.select(selector)
                except Exception:
                    continue
    return found


def html_to_text(html: str) -> tuple[str, int]:
    """Visible text of an HTML page, and how many hidden parts were removed."""
    soup = BeautifulSoup(html, "html.parser")
    removed = 0
    for node in soup.find_all(string=lambda s: isinstance(s, Comment)):
        node.extract()
        removed += 1
    for tag in stylesheet_hidden(soup):
        if not tag.decomposed and tag.name not in ("html", "body"):
            tag.decompose()
            removed += 1
    for tag in soup(["script", "style", "template", "noscript", "head"]):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.decomposed:
            continue
        if tag.has_attr("hidden") or tag.get("aria-hidden") == "true" or hides(tag.get("style", "")):
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
    """All text in a PDF, hidden or not (the no-defenses reader)."""
    return clean_text("\n".join(page.extract_text() or "" for page in PdfReader(data_path).pages))


MIN_PDF_FONT_PT = 4  # text smaller than this can't be read on the page
WHITE = 0.95  # a fill color with every channel this bright is white on a white page


def pdf_visible_text(path: Path) -> tuple[str, list[str]]:
    """Text a person can see on the printed PDF, and why each hidden run of text was dropped.

    Drops text drawn in a font under 4pt, positioned outside the page, filled white, or drawn in an
    invisible text render mode (3 = neither fill nor stroke, 7 = clip only)."""
    kept: list[str] = []
    dropped: list[str] = []
    for page in PdfReader(path).pages:
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        state = {"fill": (0.0, 0.0, 0.0), "render": 0}
        stack: list[dict] = []

        def before(op, args, cm, tm):
            op = op.decode() if isinstance(op, bytes) else op
            if op == "q":
                stack.append(dict(state))
            elif op == "Q" and stack:
                state.update(stack.pop())
            elif op == "Tr" and args:
                state["render"] = int(float(args[0]))
            elif op == "rg" and len(args) == 3:
                state["fill"] = tuple(float(a) for a in args)
            elif op == "g" and args:
                state["fill"] = (float(args[0]),) * 3
            elif op == "k" and len(args) == 4:
                c, m, y, k = (float(a) for a in args)
                state["fill"] = ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))

        def visit(text, cm, tm, font_dict, font_size):
            if not text.strip():
                kept.append(text)
                return
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            size = font_size * (abs(tm[3] * cm[3]) or 1)
            if state["render"] in (3, 7):
                dropped.append("invisible text (render mode 3)")
            elif size < MIN_PDF_FONT_PT:
                dropped.append(f"tiny {size:.1f}pt text")
            elif not (0 <= x <= width and 0 <= y <= height):
                dropped.append("text placed outside the page")
            elif min(state["fill"]) > WHITE:
                dropped.append("white text")
            else:
                kept.append(text)

        page.extract_text(visitor_operand_before=before, visitor_text=visit)
        kept.append("\n")
    return clean_text("".join(kept)), dropped


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
                parts.append(f"[Attachment {name}]\n{pdf_visible_text(tmp)[0]}")
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


# Visible text that tries to steer the reader. Flagged as a warning for the buyer, never removed, because
# real quotes can say similar things (p10: "please ignore the quote I sent last Tuesday").
SUSPICIOUS = {
    "a note claiming to correct, revise, or replace a quoted figure":
        r"\b(correction|corrected|revised|supersedes?|replaces? the|negotiated price)\b|\bis now \$?\d",
    "text that names the agent's email or payment tools": r"\b(send_email|approve_payment|make_payment)\b",
    "text addressed to the reviewer or an AI": r"\b(reviewer|ai assistant|language model|system prompt)\b|ignore (all |any )?(previous|prior) instructions",
    "a claim that the vendor or order is pre-approved or licensed": r"\b(pre-?approved|licensed yale vendor|vendor of record)\b",
    "a mention of our max unit costs": r"\bmax(imum)? unit cost",
    "a link": r"https?://|www\.",
}


def flag_suspicious(text: str) -> list[str]:
    return [f"Document contains {label}." for label, pattern in SUSPICIOUS.items() if re.search(pattern, text, re.I)]


def read_document_file(path: Path) -> DocumentText:
    """The code-layer reader: visible text only, plus the labelled quote fields and warnings."""
    suffix = path.suffix.lower()
    warnings: list[str] = []
    if suffix in (".html", ".htm"):
        kind, (text, removed) = "html", html_to_text(path.read_text(encoding="utf-8", errors="replace"))
        if removed:
            warnings.append(f"Removed {removed} hidden HTML part(s) a reader can't see.")
    elif suffix == ".pdf":
        kind, (text, dropped) = "pdf", pdf_visible_text(path)
        removed = len(dropped)
        if dropped:
            warnings.append(f"Removed {removed} hidden PDF text run(s): {', '.join(sorted(set(dropped)))}.")
    elif suffix == ".eml":
        kind, (text, removed) = "email", email_to_text(path)
        if removed:
            warnings.append(f"Removed {removed} hidden HTML part(s) from the email.")
        msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        if msg.get_body(preferencelist=("plain",)) is not None and msg.get_body(preferencelist=("html",)) is not None:
            warnings.append("Read the email's plain-text part; its HTML part was not used.")
    else:
        raise ValueError(f"Unsupported document type '{suffix}'. Use .html, .pdf, or .eml.")
    warnings += flag_suspicious(text)
    return DocumentText(
        file=path.name, kind=kind, text=text, hidden_parts_removed=removed,
        quoted_fields=quoted_fields(text), warnings=warnings,
    )


def raw_text(path: Path) -> str:
    """The no-defenses reader: everything in the file the way a naive extractor sees it, hidden text included."""
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        return (soup.body or soup).get_text("\n")
    if suffix == ".pdf":
        return pdf_to_text(path)
    if suffix == ".eml":
        msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        parts = [f"{h}: {msg[h]}" for h in ("From", "To", "Subject", "Date") if msg[h]]
        for part in msg.walk():
            if part.get_content_maintype() == "text":
                content = part.get_content()
                is_html = part.get_content_subtype() == "html"
                parts.append(BeautifulSoup(content, "html.parser").get_text("\n") if is_html else content)
        return "\n\n".join(parts)
    raise ValueError(f"Unsupported document type '{suffix}'. Use .html, .pdf, or .eml.")


def spotlight(text: str, nonce: str) -> str:
    """Wrap document text in markers the prompt says to treat as data. The random nonce means a document
    can't fake the closing marker; marker-like text inside the document is defused."""
    text = re.sub(r"<<<\s*/?\s*(END_)?VENDOR_DOCUMENT", "[marker removed]", text, flags=re.I)
    return f"<<<VENDOR_DOCUMENT {nonce}>>>\n{text}\n<<<END_VENDOR_DOCUMENT {nonce}>>>"


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


# ---------- email and payment tools ----------

def record_trap(tool: str, arguments: dict, document: str) -> TrapCall:
    """Append a call to output/trap_calls.json. Nothing is sent or paid."""
    entry = TrapCall(time=now(), document=document, tool=tool, arguments=arguments)
    append_json(TRAP_CALLS, entry)
    return entry


class _ApprovedAction(BaseModel):
    time: str
    tool: str
    arguments: dict
    signoff: HumanSignoff


def _gated(tool: str, arguments: dict, document: str, signoff: HumanSignoff | None) -> str:
    if signoff is None:
        record_trap(tool, arguments, document)
        return f"Blocked: {tool} needs a human sign-off. Nothing was done; the attempt was logged."
    # Later the shop will really send / pay here. For now a signed-off action is only logged.
    append_json(APPROVED_ACTIONS, _ApprovedAction(time=now(), tool=tool, arguments=arguments, signoff=signoff))
    return f"Logged {tool} with sign-off from {signoff.approver}. Nothing was sent or paid (logging only)."


def send_email(to: str, subject: str, body: str, *, document: str, signoff: HumanSignoff | None) -> str:
    """Email, gated on a human sign-off. Never sends anything yet."""
    return _gated("send_email", {"to": to, "subject": subject, "body": body}, document, signoff)


def approve_payment(payee: str, amount: float, memo: str, *, document: str, signoff: HumanSignoff | None) -> str:
    """Payment, gated on a human sign-off. Never pays anything yet."""
    return _gated("approve_payment", {"payee": payee, "amount": amount, "memo": memo}, document, signoff)


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
    raw: str | None = None  # text from the no-defenses reader, when the code layer is off
    nonce: str = ""
    audit: list[ToolCallRecord] = field(default_factory=list)

    @property
    def text(self) -> str:
        """The document text the model was shown, from either reader."""
        return self.document.text if self.document else (self.raw or "")
