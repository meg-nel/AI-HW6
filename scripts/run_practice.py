"""Run the agent on every practice document and compare with data/practice_key.json.

Usage:
    python scripts/run_practice.py              (each document once)
    python scripts/run_practice.py --repeat 3   (each document 3 times, to catch answers that change run to run)

Results go to output/practice_results.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import run_doc  # noqa: E402
from tools import ROOT, TRAP_CALLS, now, run_cost  # noqa: E402

DOCS = ROOT / "data" / "practice_docs"
KEY = ROOT / "data" / "practice_key.json"
OUT = ROOT / "output" / "practice_results.json"
FIELDS = ("vendor", "sku", "unit_price", "lead_time_days", "min_order", "decision")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    key = {k["file"]: k for k in json.loads(KEY.read_text(encoding="utf-8"))}
    traps_before = len(json.loads(TRAP_CALLS.read_text(encoding="utf-8"))) if TRAP_CALLS.exists() else 0
    runs = []
    for doc in sorted(p for p in DOCS.iterdir() if p.suffix.lower() in {".html", ".pdf", ".eml"}):
        for attempt in range(1, args.repeat + 1):
            answer, result = run_doc(doc)
            expected = key[doc.name]
            wrong = {f: {"got": getattr(answer, f), "expected": expected[f]} for f in FIELDS if getattr(answer, f) != expected[f]}
            runs.append({
                "document": doc.name,
                "attempt": attempt,
                "answer": answer.model_dump(),
                "matches_key": not wrong,
                "wrong_fields": wrong,
                "cost_usd": run_cost(result.usage)[0],
            })
            print(f"{doc.name:30} #{attempt} {answer.decision:17} {'OK' if not wrong else wrong}")
    traps_after = len(json.loads(TRAP_CALLS.read_text(encoding="utf-8")))
    summary = {
        "time": now(),
        "runs": len(runs),
        "matching_key": sum(r["matches_key"] for r in runs),
        "new_trap_calls": traps_after - traps_before,
        "total_cost_usd": round(sum(r["cost_usd"] for r in runs), 8),
    }
    OUT.write_text(json.dumps({"summary": summary, "runs": runs}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
