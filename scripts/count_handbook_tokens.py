"""Count the tokens in the shop handbook and price it per call.

Usage:
    python scripts/count_handbook_tokens.py           # local tiktoken count only
    python scripts/count_handbook_tokens.py --api     # also ask the model how many input tokens it billed

Two ways to count:
  1. Locally with tiktoken's o200k_base encoding (the tokenizer used by OpenAI's GPT-4o / GPT-5 family).
  2. From the API's usage report: send the handbook as the system message, then send the same
     call with an empty system message, and subtract. The difference is what the handbook alone costs.
     Sending the handbook call twice also shows whether the second call reads it from the cache.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import tiktoken

ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "data" / "shop_handbook.md"
PRICES = ROOT / "data" / "prices.json"
MODEL = "gpt-5.6-luna"
PRICED_MODEL = "gpt-6-luna"  # the only model listed in prices.json
PROBE = "Reply with OK."


def local_count(text: str) -> int:
    return len(tiktoken.get_encoding("o200k_base").encode(text))


def api_usage(system: str) -> dict:
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(ROOT.parent / ".env")
    key = os.getenv("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is missing from the root .env file.")
    client = OpenAI(api_key=key, base_url="https://api.portkey.ai/v1", default_headers={"x-portkey-api-key": key})
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": PROBE}],
    )
    u = resp.usage
    cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) if u.prompt_tokens_details else 0
    return {"prompt_tokens": u.prompt_tokens, "cached_tokens": cached or 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", action="store_true", help="also measure with real API calls")
    args = parser.parse_args()

    text = HANDBOOK.read_text(encoding="utf-8")
    prices = json.loads(PRICES.read_text(encoding="utf-8"))[PRICED_MODEL]
    result = {
        "characters": len(text),
        "words": len(text.split()),
        "tiktoken_o200k_base": local_count(text),
        "prices_per_1m": prices,
    }
    if args.api:
        baseline = api_usage("")
        first = api_usage(text)
        second = api_usage(text)
        result["api"] = {
            "model": MODEL,
            "empty_system_call": baseline,
            "handbook_call_1": first,
            "handbook_call_2": second,
            "handbook_tokens": first["prompt_tokens"] - baseline["prompt_tokens"],
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
