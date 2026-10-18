"""Problem 6: rerun the practice documents with the defense layers on, alone, and left out one at a time.

Usage:
    python scripts/defense_test.py

Configurations: none, each layer alone, each pair (all but one layer), and all three.
Each runs on the 12 practice documents plus the 4 visible-attack probes in data/defense_probes/
(copies of p02, p03, p04, p09 with the attack text made visible, so the code layer can't strip it).
Each configuration gets its own run tag, so every one starts from a cold prompt cache.

Outputs:
    output/defense_results.json   all three layers, 12 practice documents, in the Problem 5 shape plus tokens and dollars
    output/defense_ablation.json  every configuration on all 16 documents, with summaries
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import LAYERS, run_doc  # noqa: E402
from evaluate import new_traps, score, summarize, trap_count  # noqa: E402
from tools import ROOT, now  # noqa: E402

SETS = {
    "practice": (ROOT / "data" / "practice_docs", ROOT / "data" / "practice_key.json"),
    "probe": (ROOT / "data" / "defense_probes", ROOT / "data" / "defense_probes" / "probe_key.json"),
}
CONFIGS = {
    "none": (),
    "code": ("code",),
    "design": ("design",),
    "prompt": ("prompt",),
    "code+design": ("code", "design"),
    "code+prompt": ("code", "prompt"),
    "design+prompt": ("design", "prompt"),
    "all": LAYERS,
}
RESULTS = ROOT / "output" / "defense_results.json"
ABLATION = ROOT / "output" / "defense_ablation.json"


def docs(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in {".html", ".pdf", ".eml"})


def main() -> None:
    only = sys.argv[1:] or list(CONFIGS)
    ablation = json.loads(ABLATION.read_text(encoding="utf-8")) if ABLATION.exists() else {"configs": {}}
    for name in only:
        layers = frozenset(CONFIGS[name])
        run_tag = uuid4().hex[:12]
        by_set = {}
        for set_name, (folder, key_file) in SETS.items():
            key = {k["file"]: k for k in json.loads(key_file.read_text(encoding="utf-8"))}
            results = []
            for doc in docs(folder):
                before = trap_count()
                answer, result = run_doc(doc, defenses=layers, run_tag=run_tag)
                r = score(doc, answer, result, new_traps(before), key[doc.name])
                results.append(r)
                print(f"{name:14} {doc.name:42} {'FOOLED' if r['fooled'] else 'ok':6} {answer.decision:17} "
                      f"wrong={list(r['wrong_fields'])} traps={[t['tool'] for t in r['trap_calls']]} "
                      f"strange={r['strange_text']} ${r['cost_usd']:.6f}", flush=True)
            by_set[set_name] = {"summary": summarize(results), "results": results}
        ablation["configs"][name] = {"layers": sorted(layers), "run_tag": run_tag, "time": now(), **by_set}
        ABLATION.write_text(json.dumps(ablation, indent=2) + "\n", encoding="utf-8")
        if name == "all":
            practice = by_set["practice"]
            summary = {"time": now(), "agent": "defended (code + design + prompt)", **practice["summary"]}
            RESULTS.write_text(json.dumps({"summary": summary, "results": practice["results"]}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
