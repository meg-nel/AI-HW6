# Handbook Size and Cost Estimate

The vendor desk agent sends the whole Campus Customs Shop Handbook (`data/shop_handbook.md`) to the model on every call. This file works out how many tokens that is and what it costs.

## 1. Token count: **10,058 tokens**

| Measure | Value |
|---|---|
| Characters | 28,903 |
| Words | 6,127 |
| Lines | 338 |
| **Tokens (tiktoken `o200k_base`)** | **10,058** |
| **Tokens (API usage report)** | **10,058** |

### How I got it

I counted it two ways with `scripts/count_handbook_tokens.py`, and both gave the same number.

1. **Local count.** I ran the handbook text through OpenAI's `tiktoken` library with the `o200k_base` encoding, which is the tokenizer used by the GPT-4o / GPT-5 model family. Result: **10,058 tokens**.
2. **What the API billed.** I made two real calls through Portkey to `gpt-5.6-luna` with the same short user message (`"Reply with OK."`):
   - Empty system message: `prompt_tokens = 14`. That's the message overhead plus the user message.
   - Handbook as the system message: `prompt_tokens = 10,072`.
   - Handbook alone = 10,072 − 14 = **10,058 tokens**.

Rough check: 28,903 characters ÷ 10,058 tokens ≈ 2.9 characters per token. That's lower than the usual rule of thumb of about 4 for English prose, because the handbook is mostly tables. The pipes, SKUs, dollar amounts, and numbers split into many small tokens.

## 2. Prices used

From `data/prices.json` (OpenAI Standard pricing, MGT 409 Lecture 11). The only model listed there is `gpt-6-luna`:

| Token type | Price per 1M tokens | Price per token |
|---|---|---|
| Input (uncached) | $0.10 | $0.0000001 |
| Cached input (cache read) | $0.01 | $0.00000001 |
| Cache write | $0.125 | $0.000000125 |

Cost of the handbook part of one call = 10,058 tokens × (price per 1M ÷ 1,000,000).

## 3. Without caching

Every call pays the full input price for all 10,058 handbook tokens.

- **One call:** 10,058 × $0.10 / 1,000,000 = **$0.0010058** (about a tenth of a cent)
- **1,000 calls:** 1,000 × $0.0010058 = **$1.0058** (about $1.01)

## 4. With caching

The handbook is the same on every call, so it can be put at the start of the prompt as a cached prefix. The first call writes the cache, which costs a bit more than normal input. Every call after that reads the handbook from the cache at the much lower cached price.

- **Cache write (first call):** 10,058 × $0.125 / 1,000,000 = **$0.00125725**
- **Cache read (each later call):** 10,058 × $0.01 / 1,000,000 = **$0.00010058**

**One call:**
- If it's the first call, it pays the cache write: **$0.00125725**. That's about 25% *more* than uncached ($0.00125725 ÷ $0.0010058 = 1.25), so caching doesn't pay off on a single call.
- If the handbook is already cached (a cache hit): **$0.00010058**, which is 10× cheaper than uncached.

**1,000 calls** (1 cache write, then 999 cache reads):

```
  1 × $0.00125725        = $0.00125725
999 × $0.00010058        = $0.10047942
                           -----------
Total                    = $0.10173667   (about $0.10)
```

## 5. Summary

| Scenario | Handbook cost |
|---|---|
| 1 call, no cache | $0.0010058 |
| 1 call, cache write (first call) | $0.00125725 |
| 1 call, cache hit | $0.00010058 |
| **1,000 calls, no cache** | **$1.0058** |
| **1,000 calls, with cache** (1 write + 999 hits) | **$0.1017** |

Caching saves $1.0058 − $0.1017 = **$0.9041 per 1,000 calls, about 89.9%**. This counts the handbook's input tokens only. Each vendor document, the user message, and the model's output (at $0.50 per 1M output tokens) cost extra.

## 6. Caveats

- **Pricing vs. the model we call.** `prices.json` only lists `gpt-6-luna`, so all the dollar figures use those prices. The agent itself calls `gpt-5.6-luna` (per `AGENTS.md`). If its prices differ, the token count stays the same but the dollar figures need to be redone with its prices.
- **Caching isn't guaranteed.** In my test, the second identical handbook call came back with `cached_tokens = 0`, so it was billed as normal input. OpenAI only caches prompt prefixes of at least 1,024 tokens (the handbook easily clears that), and only on a best-effort basis. Caches also expire after a few minutes of inactivity, and requests through a gateway like Portkey may be routed in ways that miss the cache. The "1,000 calls with cache" figure assumes the calls come close enough together that the cache stays warm, and that the handbook sits at the very start of every prompt, unchanged, before any per-document text.
- The cache write premium ($0.125 vs. $0.10) comes from `prices.json`. If the provider doesn't charge for cache writes, the first call costs $0.0010058 and the 1,000-call total drops slightly, to $0.1015 (= $0.0010058 + $0.10047942).
