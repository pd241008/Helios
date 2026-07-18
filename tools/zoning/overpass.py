"""
overpass.py — Overpass API client for fetching OSM elements.

Handles query construction, HTTP transport, and response parsing.
Does NOT do any geometry conversion — that's parser.py's job.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request


def fetch_overpass(bbox: tuple[float, float, float, float],
                   timeout: int = 180) -> dict:
    """Fetch OSM elements from Overpass API for the given bbox.

    Queries for landuse, natural=water/wetland, leisure=park/garden/reserve,
    and waterway **relations** (not ways — waterway ways are linear features).

    Returns the raw JSON response dict with 'elements' list.
    """
    south, west, north, east = bbox
    bbox_str = f"({south},{west},{north},{east})"

    # Note: We do NOT fetch way["waterway"] — waterway tags on ways are
    # linear features (river/canal centerlines), not area features.  Only
    # relations can produce proper multipolygon areas for waterways.
    # Area water features come from way["natural"~"water|wetland"] instead.
    query = f"""[out:json][timeout:{timeout}];
(
  way["landuse"]{bbox_str};
  relation["landuse"]{bbox_str};
  way["natural"~"water|wetland"]{bbox_str};
  relation["natural"~"water|wetland"]{bbox_str};
  way["leisure"~"park|nature_reserve|garden"]{bbox_str};
  relation["leisure"~"park|nature_reserve|garden"]{bbox_str};
  relation["waterway"]{bbox_str};
);
out body;
>;out skel qt;"""

    print(f"  Querying Overpass API for bbox {bbox_str} ...")
    url = "https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(query)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "helios-zoning-fetch/1.0")

    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=timeout + 60)
    data = json.loads(resp.read())
    elapsed = time.time() - t0

    elements = data.get("elements", [])
    n_nodes = sum(1 for e in elements if e["type"] == "node")
    n_ways = sum(1 for e in elements if e["type"] == "way")
    n_rels = sum(1 for e in elements if e["type"] == "relation")
    print(f"  Fetched {n_ways} ways, {n_rels} relations, {n_nodes} nodes in {elapsed:.1f}s")
    return data
