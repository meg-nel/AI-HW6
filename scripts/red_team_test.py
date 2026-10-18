"""Problem 7: run the red-team documents in data/my_attacks/ on the bare and the defended agent.

Usage:
    python scripts/red_team_test.py            (3 runs per document per agent)
    python scripts/red_team_test.py --repeat 5

Each run is scored like Problem 5 (field match, decision, trap calls, strange text, tokens, dollars).
Results go to output/red_team_results.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import LAYERS, run_doc  # noqa: E402
from evaluate import new_traps, score, summarize, trap_count  # noqa: E402
from tools import ROOT, now  # noqa: E402

DOCS = ROOT / "data" / "my_attacks"
KEY = DOCS / "my_attacks_key.json"
OUT = ROOT / "output" / "red_team_results.json"
AGENTS = {"no_defenses": frozenset(), "defended": frozenset(LAYERS)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--agents", default="no_defenses,defended", help="which agents to run")
    parser.add_argument("--label", default="", help="suffix for the defended agent's results, e.g. _after_patch")
    args = parser.parse_args()
    key = {k["file"]: k for k in json.loads(KEY.read_text(encoding="utf-8"))}
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() and args.label else {"agents": {}}
    out.update(time=now(), repeat=args.repeat)
    for name in args.agents.split(","):
        layers = AGENTS[name]
        agent_name = name + (args.label if name == "defended" else "")
        results = []
        for doc in sorted(p for p in DOCS.iterdir() if p.suffix.lower() in {".html", ".pdf", ".eml"}):
            for attempt in range(1, args.repeat + 1):
                before = trap_count()
                answer, result = run_doc(doc, defenses=layers)
                r = {"attempt": attempt, **score(doc, answer, result, new_traps(before), key[doc.name])}
                results.append(r)
                print(f"{agent_name:12} {doc.name:40} #{attempt} {'FOOLED' if r['fooled'] else 'ok':6} {answer.decision:17} "
                      f"wrong={r['wrong_fields']} traps={[t['tool'] for t in r['trap_calls']]}", flush=True)
        out["agents"][agent_name] = {"layers": sorted(layers), "summary": summarize(results), "results": results}
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for name, a in out["agents"].items():
        print(name, json.dumps(a["summary"]))


if __name__ == "__main__":
    main()
