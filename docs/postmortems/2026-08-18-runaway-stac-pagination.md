# Postmortem: Runaway STAC Pagination

**Date:** 2026-08-18  
**Status:** Resolved

## Incident Summary
When attempting to restrict the Bangalore ingestion to a balanced dataset of 8 scenes per year, the Go worker was executed with `-limit 8`. Instead of downloading 8 scenes total, the worker fell into an infinite loop, continuously pulling down batches of 8 scenes and queuing thousands of downloads, overwhelming the local orchestrator.

## Root Cause
A misunderstanding of the Planetary Computer STAC API specification. The `limit` parameter in a STAC search request only bounds the *page size* of the return payload, not the total number of features. Because the `limit` was artificially lowered to 8, the API returned 8 features but appended a `next` link. The Go worker's `Search()` loop was designed to follow `next` links until exhausted, bypassing the user's intent to cap the total download.

## Timeline
- **18:07** — Ingestion loop started for Bangalore years 2016-2026 with `-limit 8`.
- **18:09** — Logs indicate the STAC client reached "page 241" for the year 2016, infinitely spooling 8-scene blocks.
- **18:09** — Ingestion process forcibly killed.

## Action Items
1. **[DONE]** Modified `stac.go` to treat `cfg.Limit` as a hard boundary.
2. **[DONE]** Implemented a slice and `break` routine: if the length of accumulated `features` hits the target limit, the pagination loop drops the `next` link and returns immediately.
3. **[DONE]** See ADR-002.
