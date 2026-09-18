# ADR 005: Per-City Temporal Split Policy

## Status
Accepted (2026-08-21)

## Context
`temporal_split()` honours the `split` marker column written by the Scala
pipeline as hive partitions (`year=YYYY/split=train|test`). Those markers
encode a **static calendar-year boundary** (Bangalore: test = 2025;
Chennai: test = 2025--2026).

Two problems surfaced:

1. **Stale markers.** The corrected evaluation design — a rolling 12-month
   test window anchored on each city's latest scene (`cutoff = latest_scene_date
   − 365d`) — exists in `_split_by_last_12_months()` but only ran as a
   fallback. Because the marker column was always present, the fallback never
   fired, and a full-res ensemble was silently evaluated on the superseded
   calendar-year split (test = 1.63M rows / 2 scenes for Bangalore). The
   signature of the stale split: near-zero/negative individual-model R².
2. **Cross-artifact comparability (Chennai).** The Chennai single-model
   headline (R² = 0.7999) was produced on the fixed calendar-year window,
   while the ensemble rerun used the rolling window — two different test sets
   inside one results section.

The two cities are not symmetric cases: Bangalore's calendar-2025 test set is
thin and seasonally shifted (test LST σ = 2.98 K vs train 5.85 K), while
Chennai's fixed 2025--2026 window has 11 scenes and a well-matched test
distribution (σ 5.59 vs 5.63).

## Decision

- `temporal_split()` gains an explicit `strategy` parameter:
  - `"marker"` — honour pipeline-written partitions (default; preserves all
    existing callers).
  - `"dynamic"` — always use the rolling 12-month boundary, ignoring markers.
- The ensemble CLI exposes `--split-strategy {dynamic,marker}`.

**Per-city policy:**

| City | Strategy | Test window | Test scenes | Rationale |
|------|----------|-------------|-------------|-----------|
| Bangalore | `dynamic` | > 2024-12-10 | 4 | Fixes thin/biased calendar-2025 test |
| Chennai | `marker` | 2025-01-01 -- 2026-06-06 | 11 | Matches single-model headline window; no thin-test problem |

Both choices are recorded in machine-readable evidence files
(`split_evidence.txt`: cutoff date, per-split row counts, scene lists, LST
mean/σ, run-log excerpt) written into each reports directory, so every
published number carries its own split provenance.

## Consequences
**Positive:**
- Individual models show positive, sensible R² on both cities after the fix
  (0.27--0.39 Bangalore; 0.58--0.79 Chennai) versus the broken-split
  signature.
- Ensemble and single-model numbers within each city's results section are
  evaluated on identical windows.
- Split provenance is auditable from artifacts alone.

**Negative:**
- The two cities use different window definitions. This is deliberate and
  disclosed, but cross-city R² comparisons must be qualitative, not direct.
- Static markers elsewhere in the repo remain calendar-based; any new
  consumer must choose a strategy explicitly rather than trusting defaults.
