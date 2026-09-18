# Postmortem: Autonomous Ingestion Chaining

**Date:** 2026-08-18  
**Status:** Resolved

## Incident Summary
After successfully completing an authorized model training run for Chennai (`make train`), the monolithic `run_overnight.sh` script autonomously proceeded to execute the next target: `make ingest-bangalore`. This kicked off a massive 66GB download for an unscoped geographic region without human intervention or explicit authorization, polluting the `F:` drive archive.

## Root Cause
The root cause was the design of `run_overnight.sh`. It was built as a fire-and-forget monolithic sequence:
```bash
make process
uv run python -m helios_ml.ensemble ...
make ingest-bangalore
```
Because `set -e` was used, any failure would stop the script, but successes caused it to blindly chain into experimental, future-work commands (like Bangalore ingestion) that lacked defined scoping constraints (BBox, STAC thresholds, cloud cover).

## Timeline
- **16:08** — `make train` completes successfully for Chennai.
- **16:09** — `run_overnight.sh` chains into `make ingest-bangalore` autonomously.
- **16:30** — 66GB of uncontrolled data is ingested.
- **16:40** — The task is forcibly killed midway through Scala processing due to unrecognized spatial bounds.

## Action Items
1. **[DONE]** Nuked `run_overnight.sh` from the repository.
2. **[DONE]** Established a rule: Automated scripts must have explicit stop/confirm gates between major experimental phases.
3. **[DONE]** Wiped the uncontrolled 66GB pull and re-scoped the Bangalore ingestion with strict `-limit 8` parameters.
