# Demo runbook

The shortest path from a cold machine to the full evidence chain. Every command
below was run against this repository on Python 3.12.11 / PostgreSQL 16.15 /
Docker 29.6.1.

**Gemma proposes. PostgreSQL proves.**

## Prerequisites

| Need | Why | Check |
| --- | --- | --- |
| Python 3.11+ | runtime | `python -V` |
| Docker Desktop | the two demo PostgreSQL servers | `docker info` |
| Ollama *(optional)* | local Gemma fallback | `ollama list` |

No API key is needed for the golden demo. The fixture provider is deterministic
and offline.

## Setup

```bash
python -m venv .venv && .venv\Scripts\activate      # POSIX: . .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d --wait                        # baseline :5432, shadow :5433
schemapulse demo --seed-only                       # 1,000,000 orders / 20,000 customers
schemapulse doctor                                 # expect every row to be "ok"
```

`doctor` must be all green before you present. It checks Python, Docker, both
databases, and whether the configured model endpoint is reachable.

## The three commands to show a judge

```bash
schemapulse inspect  demo/slow_orders.sql                      # no model, no network
schemapulse diagnose demo/slow_orders.sql --provider fixture   # the full loop
schemapulse report --open                                      # the evidence page
```

Or all three, plus seeding, in one:

```bash
schemapulse demo --provider fixture
```

### 1. Baseline — deterministic, no model

`inspect` shows a `Seq Scan on orders` reading 1,000,045 rows to return 50, with
a `filter (o.status = 'pending')` discarding 980,205 of them. There is no
non-primary index on `orders`. Nothing here involved a model.

### 2. The loop — propose, validate, prove

`diagnose` prints each stage as it happens, so you can narrate over it:

```
Gemma fixture/schemapulse-heuristic-v1 attempt 1
  ✓ passed validation CREATE INDEX "sp_orders_status_created_at_partial"
      ON "orders" ("created_at" DESC) WHERE "status" = 'pending'
  baseline  run 1..5/5
  created: sp_orders_status_created_at_partial
  candidate run 1..5/5
  cleaned up sp_orders_status_created_at_partial
  VERIFIED · 61.18x verified
```

Expected on the seeded fixture: a **partial** index named
`sp_orders_status_created_at_partial`, verdict `verified`, `rows examined
1,000,045 → 96`, and `buffers touched 53,413 → 708`. The exact multiplier is
machine-specific — 61x–70x on a laptop is normal.

Two details worth pointing at, because they are the whole thesis:

- The DDL is **rebuilt from the parsed AST**, not interpolated from model text.
  Quoting, `IF NOT EXISTS` and `CONCURRENTLY` are chosen by the tool.
- `cleaned up ...` happens **even on failure**. The only writes SchemaPulse ever
  performs are `CREATE INDEX` / `DROP INDEX`, and only on the shadow.

### 3. Verdict and exit code

| Verdict | Exit code | Meaning |
| --- | --- | --- |
| `verified` | `0` | median improved past `min_speedup`, plan actually used the index |
| `rejected` / `inconclusive` / `failed` | `2` | not proven; the reason is printed |
| environment or config error | `1` | nothing ran |

Non-zero on "not verified" is deliberate: it makes `diagnose` usable as a CI gate.

## Showing the honesty, not just the win

A verified result is the easy half of the demo. The half that matters is what
happens when the model is wrong.

```bash
schemapulse diagnose demo/slow_orders.sql --provider ollama
```

With `gemma3:4b-it-q4_K_M` this typically proposes indexes on the **wrong
table** (`customers`) for a query dominated by `orders`. SchemaPulse validates,
measures, and reports the truth:

```
REJECTED
  the planner did not select the new index, so the 1.54x median difference
  is not attributable to it
```

Note what it refuses to do: it will not bank a 1.54x "win" when the plan shape
is unchanged. That rejection is a *better* demo than a green tick, because it is
the claim "PostgreSQL proves" actually being kept.

## Live providers

```bash
schemapulse provider --probe                  # which adapter, and is it live
schemapulse diagnose demo/slow_orders.sql --provider gemini
```

| Provider | Needs | Notes |
| --- | --- | --- |
| `fixture` | nothing | deterministic; labelled `FIXTURE`, `provider_is_live: false` |
| `gemini` | `GEMINI_API_KEY` | `gemma-4-26b-a4b-it`; the key is never logged or reported |
| `ollama` | local model | `ollama pull gemma3:4b-it-q4_K_M` first |

A fixture result is never presented as a model result. Check
`provider_is_live` in `.schemapulse/last-result.json` if you want to prove it.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `doctor` says docker unavailable | daemon not running | start Docker Desktop, wait for the whale to settle |
| databases reachable but `0 rows` / empty demo | compose mounts `tmpfs`, so data does not survive a container restart | `schemapulse demo --seed-only` |
| `finishedReason=RECITATION` in the attempt table | the live model refused once | already retried automatically; the failed attempt stays listed as evidence |
| `finishedReason=RECITATION` on every attempt | the model is being asked something it will not answer | fall back: `--provider fixture` |
| `baseline timing spread was 51%` | a noisy machine, not a bad index | the noise guard handles it; re-run on a quieter machine |
| two URLs identical | refused on purpose | the shadow must be a different database; that refusal is the safety invariant |

## One honest caveat to state out loud

The numbers come from a synthetic shadow database with a single query's
workload, on one machine. It is a smoke test, not a capacity plan. SchemaPulse
prints this warning in the report itself — worth reading aloud rather than
skipping, because it is the difference between a demo and a tool.