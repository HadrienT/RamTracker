# RamTracker

A monitoring agent that finds underpriced DDR4 ECC memory on second-hand markets.
It collects listings, extracts structured specifications from their titles,
computes a price per gigabyte, and sends a push notification when a listing is
genuinely below market.

The target machine is a Supermicro X10DRi-T4+: 16 DIMM slots, DDR4 RDIMM or LRDIMM.
The project exploits a specific arbitrage. The board accepts DDR4-2133, the cheapest
band on the market because almost nobody else wants it.

## How it works

```text
collect → extract → decide → notify
```

| Package | Role |
|---|---|
| `collect` | One collector per marketplace: eBay, plus Leboncoin and Reddit as opt-in sources |
| `extract` | Turns a listing into a `MemorySpec` through a deterministic cascade, with an isolated LLM fallback |
| `decide` | Deduplication, rolling market index, alert barriers, auction handling |
| `notify` | ntfy push messages and anti-spam limits |
| `runtime` | Scheduler, per-source circuit breaker, inverted watchdog, CLI |
| `core` | Configuration, logging, SQLite, data models, money, clock |

The extraction cascade goes from the most deterministic step to the most expensive
one and stops as soon as it is sure: manufacturer part number decoding, then
grammar, coherence checks and a prefilter, then a local LLM for what remains. It
does not guess. An implausibly low price is treated as a parsing bug, not a bargain.

An alert must clear two barriers: an absolute ceiling in €/GB and a discount against
a rolling 30-day market index. With too few samples, the index stays in observation
mode.

## Design principles

- **No hardcoded price.** Every threshold lives in `configs/thresholds.yaml`.
- **Money is exact.** Amounts are `Decimal`, including in configuration files.
- **Parsing is tested offline.** A golden corpus of listing titles reports the
  resolution rate at each stage of the cascade.
- **Silence is a failure.** `ramtracker status` reports silent or failing sources
  and exits non-zero when degraded.
- **Boundaries are enforced.** Package dependencies are checked by `import-linter`.

## Getting started

Requires Python 3.13, [uv](https://docs.astral.sh/uv/) and
[just](https://just.systems/), an eBay developer key and an
[ntfy](https://ntfy.sh/) topic.

```bash
uv sync --all-extras
cp .env.example .env          # EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, NTFY_URL

uv run ramtracker migrate
uv run ramtracker run-once --source ebay
uv run ramtracker loop        # continuous scheduler, with per-source cadence and jitter
uv run ramtracker status      # health of sources, market and alerts
```

| File | Purpose |
|---|---|
| `configs/sources.yaml` | Enabled sources, queries, cadence |
| `configs/compat.yaml` | Memory the target board accepts |
| `configs/thresholds.yaml` | Barriers, guards, auction policy, anti-spam |

## Development

```bash
just lint          # ruff and mypy
just arch          # architecture contracts
just test          # everything except live tests
just test-golden   # golden corpus, with a resolution table per stage
just report
```

## Deployment

`deploy/ramtracker.service` runs it under systemd, and `deploy/docker-compose.yml`
is the container alternative.

eBay requires an always-on account deletion endpoint under GDPR and CCPA. A free
[Cloudflare Worker](deploy/worker/) acknowledges notifications around the clock
and queues them, and RamTracker pulls that queue, so nothing is exposed from home.

## Status

Collection, extraction, market index, notifications, scheduler and the replay loop
are implemented and tested. Some values still need confirming against live data,
such as a few marketplace identifiers and manufacturer decoding tables; they are
marked `[À CONFIRMER]` in `configs/` and the code. The golden corpus is a starting
set of 100 titles, meant to grow.

## Documentation

The specification is in [`blueprint/`](blueprint/README.md) and the design rationale
in [`docs/blueprint.html`](docs/blueprint.html), both in French.

## License

[MIT](LICENSE)
