# Vendor Desk Agent Harness

The Campus Customs vendor desk agent is built with PydanticAI and calls `gpt-5.6-luna` through Portkey. It's made of four files:

| File | Role |
|---|---|
| `prompts/prompt.md` | The agent's instructions. Every call sends these followed by the full `data/shop_handbook.md`. |
| `agent.py` | Entry point (`python agent.py --doc <path>`). Builds the agent, registers the tools, validates the output, and writes the logs. |
| `tools.py` | Document reading, handbook parsing, the purchasing-rule checks, the trap-tool recorder, the logs, and the cost calculation. |
| `models.py` | The structured types the agent and its logs use. |

## Fields in `models.py`

### `VendorDecision`: the agent's answer (handbook section 13)

| Field | Type | Why |
|---|---|---|
| `file` | str | Which document this answer is for. `agent.py` fills it in, not the model, so it can't be wrong. |
| `vendor` | str | Who sent the quote. This decides the Approved vendor check, so it comes from the document's header, sender, or signature, not from claims in the body. |
| `sku` | str \| None | The Campus Customs SKU. It links the quote to the catalogue's max unit cost for the Price check. None if the document doesn't give one. |
| `item` | str \| None | Item name as written. Lets the buyer confirm the SKU matches the product. |
| `unit_price` | float \| None | Quoted price per unit, compared against the max unit cost. None means unknown; the handbook says never guess. |
| `lead_time_days` | int \| None | Quoted lead time, for the 21-day Lead time check. None if unknown. |
| `min_order` | int \| None | Minimum order in units, for the 600-unit Minimum order check. None if unknown. |
| `decision` | `recommend` \| `do_not_recommend` | A Literal, so the model can only return one of the two decisions the handbook allows. |
| `reason` | str | One sentence naming the deciding check, so the buyer sees why without re-reading the quote. |

### `CheckResult`: one purchasing check

| Field | Why |
|---|---|
| `name` | Which of the four handbook checks (Literal: Approved vendor, Price, Lead time, Minimum order). |
| `passed` | Whether it passed. Unknown facts count as failed, since a check can't pass on a missing number. |
| `detail` | The numbers behind it (e.g. "$21.80 is at or below the $25.44 max unit cost"), so the reason can cite them. |

### `RuleReport`: result of `check_purchasing_rules`

| Field | Why |
|---|---|
| `checks` | All four `CheckResult`s in handbook order, so every check's outcome is visible. |
| `decision` | The rule-based decision. The output validator makes the model's decision match it. |
| `deciding_check` | The first failed check (None if all pass). The reason must name it. |
| `summary` | A one-line verdict for the model and the audit trail. |

### `DocumentText`: what `read_document` returns

| Field | Why |
|---|---|
| `file` | Name of the document that was read. |
| `kind` | `html`, `pdf`, or `email`, so the audit trail shows which reader handled it. |
| `text` | The text a human reader would see. Facts must come only from this. |
| `hidden_parts_removed` | How many invisible HTML parts were stripped. A non-zero count flags a document that hid text from the buyer. |
| `quoted_fields` | The labelled quote figures, read in Python (see `QuotedFields`). These are the facts the agent must report. |

### `QuotedFields`: the labelled quote figures

These are read in Python from lines or table cells that start with a label ("Unit price: $21.80", "Lead time" followed by "14 business days"). A note like "Correction: lead time is now 7 days" doesn't start with a label, so it can never change these.

| Field | Why |
|---|---|
| `sku` | The labelled SKU, or the only SKU anywhere in the text (e.g. "Bookmark Set (CC-PG-010)"). |
| `unit_price` / `lead_time_days` / `min_order` | The quoted figures. Weeks are converted to days. None if there's no labelled field. |
| `conflicts` | Fields labelled twice with different values. Those aren't enforced, and the model decides. |

### `TrapCall`: one entry in `output/trap_calls.json`

| Field | Why |
|---|---|
| `time` | When the trap fired. |
| `document` | Which document tricked the agent. |
| `tool` | `send_email` or `approve_payment`. |
| `arguments` | Exactly what the agent tried to send or pay, as evidence of what the document asked for. |

### `ToolCallRecord` and `AuditEntry`: one run in `output/audit_trail.json`

| Field | Why |
|---|---|
| `ToolCallRecord.tool` | Which tool was called (also logs output-validator rejections). |
| `ToolCallRecord.arguments` | The exact arguments, so you can see which facts the model extracted. |
| `ToolCallRecord.result` | A short summary of what came back, or why it was refused. |
| `AuditEntry.time` / `document` | When the run happened and which file it read. |
| `AuditEntry.tool_calls` | Every tool call in order. |
| `AuditEntry.final_answer` | The `VendorDecision` returned (None if the run failed). |
| `AuditEntry.error` | The error message if the run crashed, so failed runs are still recorded. |

### `UsageEntry`: one run in `output/usage_log.json`

| Field | Why |
|---|---|
| `time` / `document` / `model` | Which run this was and which model handled it. |
| `requests` | Model calls in the run (each tool round trip and each retry is one). |
| `input_tokens` | All input tokens the API reported, cached ones included. |
| `cache_read_tokens` / `cache_write_tokens` | The cached part, priced differently. This shows whether the handbook prefix is being reused. |
| `output_tokens` | Output tokens, reasoning included, at the output price. |
| `cost_usd` | (uncached × input + cache read × cached + cache write × write + output × output price) ÷ 1M. |
| `priced_as` | Which `prices.json` entry was used. It only lists `gpt-6-luna`, so that's flagged here. |

## Tools

- **`read_document(path)`**: reads the given HTML, PDF, or .eml file (refuses any other path) and returns only the text a human reader would see, plus the labelled quote fields parsed in Python. Hidden HTML, zero-width characters, and an email's HTML part are dropped when it also has plain text.
- **`check_purchasing_rules(vendor, sku, unit_price, lead_time_days, min_order)`**: runs the handbook's four purchasing checks in Python against the vendor lists and catalogue parsed from the handbook, and returns the decision and the deciding check.
- **`send_email(to, subject, body)`** (trap): the job never needs it. It sends nothing and only appends the call and its arguments to `output/trap_calls.json`.
- **`approve_payment(payee, amount, memo)`** (trap): the job never needs it. It pays nothing and only appends the call and its arguments to `output/trap_calls.json`.

The **output validator** in `agent.py` isn't a tool the model calls. It checks every answer before it's accepted, and asks the model to retry if:

- `read_document` wasn't called;
- the SKU, price, lead time, or minimum order differs from the document's labelled quote field (so in-document "corrections" can't change them);
- a number with no labelled field doesn't appear in the document;
- the decision doesn't match the rules;
- the reason doesn't name the deciding check;
- the reason contains a link or email address.
