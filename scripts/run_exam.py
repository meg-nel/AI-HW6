"""Problem 8: run the final defended agent on the 10 exam documents.

Usage:
    python scripts/run_exam.py

Writes output/exam_results.json straight from the agent's answers and the API's token counts, one entry per
exam file. Nothing is edited by hand. cached_tokens is the cache-read count the API reported.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import LAYERS, run_doc  # noqa: E402
from evaluate import new_traps, trap_count  # noqa: E402
from tools import ROOT, run_cost  # noqa: E402

DOCS = ROOT / "data" / "exam_docs"
OUT = ROOT / "output" / "exam_results.json"


def main() -> None:
    entries = []
    for doc in sorted(p for p in DOCS.iterdir() if p.suffix.lower() in {".html", ".pdf", ".eml"}):
        before = trap_count()
        answer, result = run_doc(doc, defenses=frozenset(LAYERS))
        usage = result.usage
        entries.append({
            "file": doc.name,
            "vendor": answer.vendor,
            "sku": answer.sku,
            "unit_price": answer.unit_price,
            "lead_time_days": answer.lead_time_days,
            "min_order": answer.min_order,
            "decision": answer.decision,
            "reason": answer.reason,
            "trap_tool_called": bool(new_traps(before)),
            "input_tokens": usage.input_tokens,
            "cached_tokens": usage.cache_read_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": run_cost(usage)[0],
        })
        e = entries[-1]
        print(f"{e['file']:16} {e['vendor']:26} {e['sku']} ${e['unit_price']} {e['lead_time_days']}d {e['min_order']}u "
              f"{e['decision']:17} trap={e['trap_tool_called']} ${e['cost_usd']:.6f}", flush=True)
    OUT.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(entries)} entries, total ${sum(e['cost_usd'] for e in entries):.6f}")


if __name__ == "__main__":
    main()
