"""
parser.py — Convert raw Overpass JSON to a GeoJSON FeatureCollection.

Handles:
- Node lookup construction
- Way → Polygon conversion (with closed-way guard for waterways)
- Relation → MultiPolygon assembly (outer/inner rings)
- OSM tag → Helios category classification
"""

from __future__ import annotations

from collections import Counter

from .config import (
    DEFAULT_CATEGORY_MAP,
    EXCLUDED_TAGS,
    WATERWAY_TO_CATEGORY,
)


# ── Node / Way helpers ────────────────────────────────────────────────

def _build_node_lookup(
    elements: list[dict],
) -> dict[int, tuple[float, float]]:
    """Build a node_id → (lon, lat) lookup from OSM elements."""
    return {
        e["id"]: (e["lon"], e["lat"])
        for e in elements
        if e["type"] == "node"
    }


def _way_to_coords(
    way: dict,
    node_lookup: dict[int, tuple[float, float]],
) -> list[tuple[float, float]] | None:
    """Convert an OSM way's node refs to a list of (lon, lat) coords.

    Returns None if any referenced node is missing from the lookup.
    """
    node_ids = way.get("nodes", [])
    coords: list[tuple[float, float]] = []
    for nid in node_ids:
        if nid not in node_lookup:
            return None
        coords.append(node_lookup[nid])
    return coords


# ── Relation → polygon rings ──────────────────────────────────────────

def _relation_to_polygon_coords(
    rel: dict,
    node_lookup: dict[int, tuple[float, float]],
    ways_lookup: dict[int, dict],
) -> list[list[tuple[float, float]]] | None:
    """Convert an OSM multipolygon relation to polygon coordinate rings.

    Handles simple outer+inner ring multipolygons. Returns None on failure.
    """
    members = rel.get("members", [])
    outer_rings: list[list[tuple[float, float]]] = []
    inner_rings: list[list[tuple[float, float]]] = []

    for member in members:
        if member["type"] != "way":
            continue
        way_id = member["ref"]
        role = member.get("role", "")
        way = ways_lookup.get(way_id)
        if way is None:
            continue
        coords = _way_to_coords(way, node_lookup)
        if coords is None or len(coords) < 4:
            continue
        # Close the ring if not already closed
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        if role == "inner":
            inner_rings.append(coords)
        else:
            outer_rings.append(coords)

    if not outer_rings:
        return None

    # For simplicity, take the largest outer ring and any inner rings
    # that fall within its bounding box
    polygons = []
    for outer in outer_rings:
        rings: list[list[tuple[float, float]]] = [outer]
        # Include inner rings that are within the outer ring's bbox
        min_lon = min(c[0] for c in outer)
        max_lon = max(c[0] for c in outer)
        min_lat = min(c[1] for c in outer)
        max_lat = max(c[1] for c in outer)
        for inner in inner_rings:
            cx = sum(c[0] for c in inner) / len(inner)
            cy = sum(c[1] for c in inner) / len(inner)
            if min_lon <= cx <= max_lon and min_lat <= cy <= max_lat:
                rings.append(inner)
        polygons.append(rings)

    return polygons[0] if len(polygons) == 1 else polygons


# ── Tag classification ────────────────────────────────────────────────

def classify_element(
    tags: dict[str, str],
    category_map: dict[str, str],
    waterway_map: dict[str, str],
) -> str | None:
    """Classify an OSM element into one of the 5 Helios zone categories.

    Returns None if the element cannot be mapped (should be excluded).
    """
    # Check waterway tags first (they don't have landuse)
    waterway = tags.get("waterway")
    if waterway and waterway in waterway_map:
        return waterway_map[waterway]

    # Check natural=water/wetland (these take priority over landuse)
    natural = tags.get("natural")
    if natural and natural in category_map:
        cat = category_map[natural]
        if cat is not None:
            return cat

    # Check leisure tags
    leisure = tags.get("leisure")
    if leisure and leisure in category_map:
        cat = category_map[leisure]
        if cat is not None:
            return cat

    # Check landuse tag (primary classifier)
    landuse = tags.get("landuse")
    if landuse:
        # Check exclusions
        excluded = EXCLUDED_TAGS.get("landuse", set())
        if landuse in excluded:
            return None
        cat = category_map.get(landuse)
        if cat is not None:
            return cat
        # Unmapped landuse tag
        return None

    return None


# ── Main conversion ──────────────────────────────────────────────────

def osm_to_geojson(
    data: dict,
    category_map: dict[str, str] | None = None,
    waterway_map: dict[str, str] | None = None,
) -> dict:
    """Convert raw OSM Overpass JSON to a GeoJSON FeatureCollection.

    Applies category mapping and filters unmapped elements.
    """
    if category_map is None:
        category_map = DEFAULT_CATEGORY_MAP
    if waterway_map is None:
        waterway_map = WATERWAY_TO_CATEGORY

    elements = data["elements"]
    node_lookup = _build_node_lookup(elements)
    ways_lookup = {e["id"]: e for e in elements if e["type"] == "way"}

    features: list[dict] = []
    excluded_count: Counter[str] = Counter()
    category_count: Counter[str] = Counter()

    # ── Process ways (direct polygons) ────────────────────────────
    n_waterway_linestrings = 0
    for e in elements:
        if e["type"] != "way":
            continue
        tags = e.get("tags", {})
        category = classify_element(tags, category_map, waterway_map)
        if category is None:
            reason = (
                tags.get("landuse")
                or tags.get("natural")
                or tags.get("leisure")
                or tags.get("waterway")
                or "unknown"
            )
            excluded_count[reason] += 1
            continue

        coords = _way_to_coords(e, node_lookup)
        if coords is None or len(coords) < 4:
            excluded_count["missing_nodes"] += 1
            continue

        # Skip non-closed waterway ways — they are linear features
        # (river/canal centerlines), not area polygons.  Force-closing
        # them creates invalid sliver polygons.
        is_closed = coords[0] == coords[-1]
        if tags.get("waterway") and not is_closed:
            n_waterway_linestrings += 1
            continue

        # Close the ring if not already closed
        if not is_closed:
            coords.append(coords[0])

        feature = {
            "type": "Feature",
            "properties": {"zoning_category": category},
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords],
            },
        }
        features.append(feature)
        category_count[category] += 1

    if n_waterway_linestrings:
        print(
            f"  Skipped {n_waterway_linestrings} non-closed waterway"
            f" ways (linear features)"
        )

    # ── Process relations (multipolygons) ─────────────────────────
    for e in elements:
        if e["type"] != "relation":
            continue
        tags = e.get("tags", {})
        category = classify_element(tags, category_map, waterway_map)
        if category is None:
            reason = (
                tags.get("landuse")
                or tags.get("natural")
                or tags.get("leisure")
                or tags.get("waterway")
                or "unknown"
            )
            excluded_count[reason] += 1
            continue

        rings = _relation_to_polygon_coords(e, node_lookup, ways_lookup)
        if rings is None:
            excluded_count["invalid_geometry"] += 1
            continue

        feature = _rings_to_feature(rings, category)
        if feature is None:
            excluded_count["invalid_geometry"] += 1
            continue

        features.append(feature)
        category_count[category] += 1

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    _print_summary(category_count, excluded_count, len(features))
    return geojson


# ── Internal helpers ──────────────────────────────────────────────────

def _rings_to_feature(
    rings: list,
    category: str,
) -> dict | None:
    """Convert polygon ring(s) from _relation_to_polygon_coords to a
    GeoJSON Feature with the correct Polygon/MultiPolygon type."""
    # Determine if this is a single polygon or multi-polygon.
    # _relation_to_polygon_coords returns:
    #   - [outer_ring, inner1, ...] for a single polygon
    #   - [[outer1, ...], [outer2, ...]] for multiple polygons
    if (
        len(rings) > 0
        and isinstance(rings[0], list)
        and len(rings[0]) > 0
        and isinstance(rings[0][0], list)
        and len(rings[0][0]) > 0
        and isinstance(rings[0][0][0], (list, tuple))
    ):
        # Multiple polygons: rings = [[polygon1_rings], [polygon2_rings], ...]
        valid_polygons = []
        for poly_rings in rings:
            if poly_rings and isinstance(poly_rings[0], list):
                outer = poly_rings[0]
                if outer and outer[0] != outer[-1]:
                    outer = outer + [outer[0]]
                valid_polygons.append([outer] + poly_rings[1:])
        if len(valid_polygons) == 1:
            return {
                "type": "Feature",
                "properties": {"zoning_category": category},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": valid_polygons[0],
                },
            }
        elif len(valid_polygons) > 1:
            return {
                "type": "Feature",
                "properties": {"zoning_category": category},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": valid_polygons,
                },
            }
        return None
    else:
        # Single polygon: rings = [outer_ring, inner1, ...]
        return {
            "type": "Feature",
            "properties": {"zoning_category": category},
            "geometry": {
                "type": "Polygon",
                "coordinates": rings,
            },
        }


def _print_summary(
    category_count: Counter,
    excluded_count: Counter,
    total: int,
) -> None:
    """Print parsing summary to stdout."""
    print(f"\n  Category distribution:")
    for cat, count in sorted(category_count.items()):
        print(f"    {cat}: {count}")
    print(f"    TOTAL features: {total}")

    if excluded_count:
        print(f"\n  Excluded (unmapped tags):")
        for tag, count in sorted(excluded_count.items()):
            print(f"    {tag}: {count}")
        print(f"    TOTAL excluded: {sum(excluded_count.values())}")
