"""Problem 4: run the agent on all 12 practice documents with and without prompt caching.

Usage:
    python scripts/cache_test.py

Every model call from both setups goes to output/cache_test.json with its token counts and cost.
Both setups get the same fresh run tag at the start of the instructions, so the with-cache setup starts
from a cold cache (no help from earlier runs). The without-cache setup runs first and writes nothing to
the cache, so it can't warm the cache for the with-cache setup.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic_ai.messages import ModelResponse  # noqa: E402

from agent import run_doc  # noqa: E402
from tools import MODEL_NAME, PRICES_FILE, ROOT, now, run_cost  # noqa: E402

DOCS = ROOT / "data" / "practice_docs"
KEY = ROOT / "data" / "practice_key.json"
OUT = ROOT / "output" / "cache_test.json"
SETUPS = (("without_cache", False), ("with_cache", True))
FIELDS = ("vendor", "sku", "unit_price", "lead_time_days", "min_order", "decision")


def main() -> None:
    run_tag = uuid4().hex[:12]
    key = {k["file"]: k for k in json.loads(KEY.read_text(encoding="utf-8"))}
    docs = sorted(p for p in DOCS.iterdir() if p.suffix.lower() in {".html", ".pdf", ".eml"})
    calls, documents = [], []
    for setup, cache in SETUPS:
        for doc in docs:
            answer, result = run_doc(doc, cache=cache, run_tag=run_tag)
            responses = [m for m in result.all_messages() if isinstance(m, ModelResponse)]
            for i, resp in enumerate(responses, 1):
                u = resp.usage
                cost, priced_as = run_cost(u)
                calls.append({
                    "setup": setup,
                    "document": doc.name,
                    "call": i,
                    "response_id": resp.provider_response_id,
                    "time": resp.timestamp.isoformat(timespec="seconds"),
                    "input_tokens": u.input_tokens,
                    "uncached_input_tokens": u.input_tokens - u.cache_read_tokens - u.cache_write_tokens,
                    "cache_read_tokens": u.cache_read_tokens,
                    "cache_write_tokens": u.cache_write_tokens,
                    "output_tokens": u.output_tokens,
                    **{f"output_{k}" if "reasoning" in k or "prediction" in k else k: v for k, v in u.details.items()},
                    "cost_usd": cost,
                    "priced_as": priced_as,
                })
            expected = key.get(doc.name, {})
            mismatches = [f for f in FIELDS if expected and getattr(answer, f) != expected[f]]
            documents.append({
                "setup": setup,
                "document": doc.name,
                "model_calls": len(responses),
                "cost_usd": round(sum(c["cost_usd"] for c in calls if c["setup"] == setup and c["document"] == doc.name), 8),
                "decision": answer.decision,
                "matches_key": not mismatches,
                "mismatched_fields": mismatches,
            })
            print(f"{setup:14} {doc.name:30} calls={len(responses)} ${documents[-1]['cost_usd']:.6f} {answer.decision} {'OK' if not mismatches else mismatches}")

    summary = {}
    for setup, _ in SETUPS:
        rows = [c for c in calls if c["setup"] == setup]
        totals = {k: sum(c[k] for c in rows) for k in ("input_tokens", "uncached_input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "output_reasoning_tokens")}
        total = round(sum(c["cost_usd"] for c in rows), 8)
        summary[setup] = {"model_calls": len(rows), "documents": len(docs), **totals, "total_cost_usd": total, "cost_per_document_usd": round(total / len(docs), 8)}
    OUT.write_text(json.dumps({
        "time": now(),
        "model": MODEL_NAME,
        "run_tag": run_tag,
        "prices": json.loads(PRICES_FILE.read_text(encoding="utf-8")),
        "summary": summary,
        "documents": documents,
        "calls": calls,
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
