# ADR 002: Hard Boundaries for STAC Pagination Limit

## Status
Accepted (2026-08-18)

## Context
When querying the Planetary Computer (or LandsatLook) STAC APIs, the `limit` parameter in the `STACSearchRequest` operates as the *page size*, not an absolute maximum on the number of returned records.

Previously, the Go worker passed `-limit 8` and trusted the STAC API to return only 8 items. Instead, the API returned 8 items *per page* and provided a `next` URL. The Go pagination loop blindly followed the `next` link infinitely, attempting to pull down thousands of scenes in batches of 8, causing a runaway worker scenario.

## Decision
We updated the core `stac.go` client to treat the configured `Limit` as an absolute maximum over the entire operation, not just a page size.

Inside the pagination loop, the client now checks if the cumulative `len(features)` matches or exceeds `cfg.Limit`. If it does, the array is sliced to exactly `cfg.Limit`, and the pagination loop is forcefully broken (`break`), ignoring any `next` links provided by the API.

## Consequences
**Positive:** 
- Guarantees bounded network queries regardless of STAC API eccentricities.
- Allows users to specify `-limit N` and reliably download exactly N scenes, enabling precise dataset sampling (e.g., 8 scenes per year).

**Negative:**
- The final STAC API page may fetch slightly more features than needed before being truncated client-side.
