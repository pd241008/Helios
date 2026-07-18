"""
geometry.py — Post-processing geometry operations on GeoJSON features.

Handles:
- Bbox clipping
- Invalid geometry repair
- Force-closed sliver detection and removal
- Deduplication
- MultiPolygon decomposition
"""

from __future__ import annotations

import math

from shapely.geometry import mapping, shape
from shapely.geometry import box as shapely_box
from shapely.validation import make_valid

from .config import DEG2_KM2, MIN_AREA_DEG2


def is_force_closed_sliver(
    geom,
    threshold: float = 5.0,
    max_compactness: float = 0.15,
) -> bool:
    """Detect if a polygon was created by force-closing a linestring.

    A force-closed linestring has its closing edge (last→first vertex)
    dramatically longer than the average of other edges, AND the polygon
    is not compact (thin sliver shape).

    Returns True if the polygon is a force-closed sliver to be removed.
    """
    if geom.geom_type != "Polygon":
        return False
    coords = list(geom.exterior.coords)
    if len(coords) < 4:
        return False

    # Edge lengths in metres
    edges: list[float] = []
    for j in range(len(coords) - 1):
        dlat = (coords[j + 1][1] - coords[j][1]) * 111000
        dlon = (
            (coords[j + 1][0] - coords[j][0])
            * 111000
            * math.cos(math.radians(13.0))
        )
        edges.append(math.sqrt(dlat**2 + dlon**2))
    if len(edges) < 2:
        return False

    avg_edge = sum(edges[:-1]) / len(edges[:-1])
    if avg_edge == 0:
        return False
    closing_ratio = edges[-1] / avg_edge

    # Compactness: 4π·A / P²
    area = geom.area
    perim = geom.length
    compactness = 4 * math.pi * area / (perim**2) if perim > 0 else 0

    return closing_ratio > threshold and compactness < max_compactness


def deduplicate_features(features: list[dict]) -> list[dict]:
    """Remove duplicate features (same geometry WKT + same category)."""
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    n_removed = 0
    for feat in features:
        geom = shape(feat["geometry"])
        key = (geom.wkt, feat["properties"]["zoning_category"])
        if key not in seen:
            seen.add(key)
            deduped.append(feat)
        else:
            n_removed += 1
    if n_removed:
        print(f"  Deduplication removed {n_removed} duplicate features")
    return deduped


def clip_features_to_bbox(
    geojson: dict,
    bbox: tuple[float, float, float, float],
    max_area_km2: float = 10.0,
) -> dict:
    """Clip all features to the query bbox and repair/remove invalid geometries.

    This fixes oversized features from Overpass relations (e.g. coastline
    relations) that extend far beyond the query bbox.

    Also decomposes MultiPolygons into individual Polygons and filters
    out features whose area exceeds max_area_km2 (they are almost certainly
    broken relation geometries, not real land-use parcels).

    Uses shapely for geometry operations. Requires shapely >= 2.0.
    """
    south, west, north, east = bbox
    bbox_poly = shapely_box(west, south, east, north)
    max_area_deg2 = max_area_km2 / DEG2_KM2

    clipped_features: list[dict] = []
    n_clipped = 0
    n_repaired = 0
    n_dropped = 0
    n_degenerate = 0
    n_oversized = 0
    n_decomposed = 0
    n_slivers = 0

    for feat in geojson["features"]:
        geom = shape(feat["geometry"])

        # Repair invalid geometries first
        if not geom.is_valid:
            try:
                geom = make_valid(geom)
                n_repaired += 1
            except Exception:
                n_dropped += 1
                continue

        # Clip to bbox
        clipped = geom.intersection(bbox_poly)

        # Skip empty or degenerate results
        if clipped.is_empty:
            n_dropped += 1
            continue

        # If clipping produced a GeometryCollection, extract only
        # Polygon/MultiPolygon components (drop lines/points)
        if clipped.geom_type == "GeometryCollection":
            from shapely.ops import unary_union

            polys = [
                g
                for g in clipped.geoms
                if g.geom_type in ("Polygon", "MultiPolygon")
            ]
            if not polys:
                n_dropped += 1
                continue
            clipped = polys[0] if len(polys) == 1 else unary_union(polys)

        # Drop degenerate geometries
        if clipped.area < MIN_AREA_DEG2:
            n_degenerate += 1
            continue

        # Check if geometry shrank significantly (was oversized)
        orig_area = geom.area
        clip_area = clipped.area
        if orig_area > 0 and clip_area / orig_area < 0.1:
            n_clipped += 1

        # Decompose MultiPolygons into individual Polygons
        # and filter oversized / sliver features
        if clipped.geom_type == "MultiPolygon":
            sub_polys = list(clipped.geoms)
            n_decomposed += 1
            for poly in sub_polys:
                if poly.area < MIN_AREA_DEG2:
                    n_degenerate += 1
                    continue
                if poly.area > max_area_deg2:
                    n_oversized += 1
                    continue
                if is_force_closed_sliver(poly):
                    n_slivers += 1
                    continue
                clipped_features.append({
                    "type": "Feature",
                    "properties": feat["properties"],
                    "geometry": mapping(poly),
                })
        else:
            # Single Polygon — check size
            if clipped.area > max_area_deg2:
                n_oversized += 1
                continue
            if is_force_closed_sliver(clipped):
                n_slivers += 1
                continue
            clipped_features.append({
                "type": "Feature",
                "properties": feat["properties"],
                "geometry": mapping(clipped),
            })

    print(f"\n  === Bbox Clipping ===")
    print(f"  Features before: {len(geojson['features'])}")
    print(f"  Features after clipping: {len(clipped_features)}")
    print(f"  Repaired invalid: {n_repaired}")
    print(f"  Clipped (>90% shrink): {n_clipped}")
    print(f"  Decomposed MultiPolygons: {n_decomposed}")
    print(f"  Oversized (> {max_area_km2:.0f} km²): {n_oversized}")
    print(f"  Force-closed slivers: {n_slivers}")
    print(f"  Dropped (empty): {n_dropped}")
    print(f"  Dropped (degenerate): {n_degenerate}")

    # Deduplicate
    deduped = deduplicate_features(clipped_features)
    print(f"  Features after dedup:  {len(deduped)}")

    return {"type": "FeatureCollection", "features": deduped}
