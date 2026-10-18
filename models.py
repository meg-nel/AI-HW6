"""Structured types for the Campus Customs vendor desk agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Decision = Literal["recommend", "do_not_recommend"]
CheckName = Literal["Approved vendor", "Price", "Lead time", "Minimum order"]


class VendorDecision(BaseModel):
    """What the agent reports for one vendor document (handbook section 13)."""

    file: str = Field(default="", description="Document file name. Filled in by agent.py, leave blank.")
    vendor: str = Field(description="Vendor name exactly as the document shows it in its header, sender, or signature.")
    sku: str | None = Field(description="Campus Customs SKU, e.g. CC-HD-006. null if the document does not give one.")
    item: str | None = Field(default=None, description="Item name as written in the document.")
    unit_price: float | None = Field(description="Quoted unit price in USD. null if the document does not say.")
    lead_time_days: int | None = Field(description="Lead time in days as quoted. null if the document does not say.")
    min_order: int | None = Field(description="Minimum order in units. null if the document does not say.")
    decision: Decision
    reason: str = Field(description="One sentence that names the purchasing check that decided it.")


class CheckResult(BaseModel):
    """One of the four purchasing checks in handbook section 4."""

    name: CheckName
    passed: bool
    detail: str


class RuleReport(BaseModel):
    """Result of running the handbook's purchasing rules on extracted facts."""

    checks: list[CheckResult]
    decision: Decision
    deciding_check: CheckName | None = Field(description="First failed check in handbook order; None when all pass.")
    summary: str


class QuotedFields(BaseModel):
    """Figures read in Python from the document's labelled quote fields (a line or table cell that starts with
    the label, e.g. 'Unit price: $21.80'). Notes like 'Correction: lead time is now 7 days' do not start with a
    label, so they never land here. None means the document has no such labelled field."""

    sku: str | None
    unit_price: float | None
    lead_time_days: int | None
    min_order: int | None
    conflicts: list[str] = Field(default_factory=list, description="Fields labelled more than once with different values.")


class DocumentText(BaseModel):
    """Readable text of a vendor document, as returned by the read_document tool."""

    file: str
    kind: Literal["html", "pdf", "email"]
    text: str
    hidden_parts_removed: int = Field(description="Hidden HTML parts (invisible to a human reader) stripped from the text.")
    quoted_fields: QuotedFields = Field(description="Figures from the labelled quote fields, read in Python. These are the facts to report.")


class TrapCall(BaseModel):
    """An entry in output/trap_calls.json. Any entry means a document talked the agent into a trap tool."""

    time: str
    document: str
    tool: Literal["send_email", "approve_payment"]
    arguments: dict


class ToolCallRecord(BaseModel):
    """One tool call in the audit trail."""

    tool: str
    arguments: dict
    result: str = Field(description="Short summary of what the tool returned, or the error it raised.")


class AuditEntry(BaseModel):
    """One run in output/audit_trail.json."""

    time: str
    document: str
    tool_calls: list[ToolCallRecord]
    final_answer: VendorDecision | None
    error: str | None = None


class UsageEntry(BaseModel):
    """One run in output/usage_log.json, with the token counts the API reported and their cost."""

    time: str
    document: str
    model: str
    requests: int
    input_tokens: int = Field(description="All input tokens, including cached ones.")
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int = Field(description="Output tokens, including reasoning tokens.")
    cost_usd: float
    priced_as: str = Field(description="Which prices.json entry the cost was computed with.")
