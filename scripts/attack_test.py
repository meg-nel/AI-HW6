"""Problem 5: attack the bare vendor desk agent (every defense off) with the 12 practice documents.

Usage:
    python scripts/attack_test.py

The bare agent is `agent.py --no-defenses`: same model, handbook, and output type, but
  - read_document returns ALL text in the file: hidden HTML and PDF text, zero-width characters, every email part
  - prompts/bare_prompt.md has no "the document is data, not instructions" rules
  - the model has the trap tools send_email / approve_payment and makes the buy decision itself
  - no output validator and no quoted-field lock
Trap tools only append to output/trap_calls.json. Results go to output/attack_results.json.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import run_doc  # noqa: E402
from evaluate import new_traps, score, summarize, trap_count  # noqa: E402
from tools import ROOT, now  # noqa: E402

DOCS = ROOT / "data" / "practice_docs"
KEY = ROOT / "data" / "practice_key.json"
OUT = ROOT / "output" / "attack_results.json"


def main() -> None:
    key = {k["file"]: k for k in json.loads(KEY.read_text(encoding="utf-8"))}
    results = []
    for doc in sorted(p for p in DOCS.iterdir() if p.suffix.lower() in {".html", ".pdf", ".eml"}):
        before = trap_count()
        answer, result = run_doc(doc, defenses=frozenset())
        r = score(doc, answer, result, new_traps(before), key[doc.name])
        results.append(r)
        print(f"{doc.name:30} {'FOOLED' if r['fooled'] else 'ok':6} {answer.decision:17} wrong={list(r['wrong_fields'])} "
              f"traps={[t['tool'] for t in r['trap_calls']]} strange={r['strange_text']}")
    summary = {"time": now(), "agent": "bare (no defenses)", **summarize(results)}
    OUT.write_text(json.dumps({"summary": summary, "results": results}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
