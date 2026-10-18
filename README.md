# AI Foundations HW6: Campus Customs Vendor Desk Agent

A PydanticAI agent that reads one vendor document (HTML, PDF, or `.eml` email), pulls out the vendor, SKU, unit price, lead time, and minimum order, and recommends whether Campus Customs should buy under the rules in `data/shop_handbook.md`. It calls `gpt-5.6-luna` through Portkey.

`send_email` and `approve_payment` never send or pay anything. Without a human sign-off they only write to `output/trap_calls.json`.

## Setup

Needs Python 3.10+ and a Portkey API key.

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

(on macOS or Linux, use `.venv/bin/python`)

```bash
cp .env.example .env
```

Then put your key in `.env` as `PORTKEY_API_KEY=...`. `.env` is in `.gitignore`, so it's never committed. The agent also reads the course's root `.env` one folder up, if there is one.

## Run the agent

```bash
python agent.py --doc data/practice_docs/p01_bluehen_quote.html
```

It prints the answer as JSON: vendor, sku, item, unit_price, lead_time_days, min_order, decision, reason, and warnings. Every run also appends to `output/usage_log.json` (tokens and dollars) and `output/audit_trail.json` (every tool call and the final answer).

Options:

| Flag | What it does |
|---|---|
| `--no-defenses` | The bare agent with every defense off (Problem 5 / red-team baseline) |
| `--defenses code,prompt` | Only the listed layers (`code`, `design`, `prompt`; default is all three) |
| `--no-cache` | Turn off prompt caching for this run |

## Re-run the tests and the report

| Script | What it produces |
|---|---|
| `python scripts/count_handbook_tokens.py --api` | Handbook token count (Problem 2) |
| `python scripts/cache_test.py` | `output/cache_test.json` (Problem 4) |
| `python scripts/attack_test.py` | `output/attack_results.json`: bare agent on the practice docs (Problem 5) |
| `python scripts/defense_test.py` | `output/defense_results.json` and `output/defense_ablation.json` (Problem 6) |
| `python scripts/build_my_attacks.py` then `python scripts/red_team_test.py` | Red-team documents and `output/red_team_results.json` (Problem 7) |
| `python scripts/run_exam.py` | `output/exam_results.json` (Problem 8) |
| `python scripts/build_report.py` | `output/hw6_report.html`, a single offline results page (Problem 9) |

The design is written up in `output/harness.md`, including its Safety section. The prompts used to build the project are in `AI_prompts.md`.
