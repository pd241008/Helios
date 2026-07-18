"""
validation.py — Area statistics, geographic sanity checks, and
PNG report generation for zoning GeoJSON data.

Generates visualizations for inclusion in ZONING_VALIDATION.md.
"""

from __future__ import annotations

import math
from pathlib import Path

from shapely.geometry import Point
from shapely.geometry import shape as shapely_shape
from shapely.strtree import STRtree

from .config import DEG2_KM2, SANITY_CHECK_POINTS


# ── Area helpers ──────────────────────────────────────────────────────

def compute_bbox_area_km2(bbox: tuple[float, float, float, float]) -> float:
    """Compute approximate bbox area in km²."""
    south, west, north, east = bbox
    mean_lat = math.radians((south + north) / 2)
    width_km = (east - west) * 111.32 * math.cos(mean_lat)
    height_km = (north - south) * 111.32
    return width_km * height_km


def compute_area_stats(
    geojson: dict,
    bbox: tuple[float, float, float, float],
) -> dict:
    """Compute area statistics for each category.

    Returns dict with keys: bbox_area_km2, total_area_km2,
    category_areas (dict[str, float]), category_counts (dict[str, int]).
    """
    bbox_area = compute_bbox_area_km2(bbox)
    geoms = [shapely_shape(f["geometry"]) for f in geojson["features"]]

    total_area = sum(g.area for g in geoms) * DEG2_KM2
    cat_area: dict[str, float] = {}
    cat_count: dict[str, int] = {}

    for g, feat in zip(geoms, geojson["features"]):
        cat = feat["properties"]["zoning_category"]
        cat_area[cat] = cat_area.get(cat, 0.0) + g.area * DEG2_KM2
        cat_count[cat] = cat_count.get(cat, 0) + 1

    return {
        "bbox_area_km2": bbox_area,
        "total_area_km2": total_area,
        "category_areas": cat_area,
        "category_counts": cat_count,
    }


# ── Sanity checks ────────────────────────────────────────────────────

def run_sanity_checks(
    geojson: dict,
    checks: list[tuple[str, float, float, str | None]] | None = None,
) -> list[dict]:
    """Run geographic sanity checks using strict point-in-polygon containment.

    Returns a list of result dicts, each with keys:
    name, lon, lat, expected, found, status.
    """
    if checks is None:
        checks = SANITY_CHECK_POINTS

    geoms = [shapely_shape(f["geometry"]) for f in geojson["features"]]
    tree = STRtree(geoms)
    cats = [f["properties"]["zoning_category"] for f in geojson["features"]]

    results: list[dict] = []
    for name, px, py, expected_cat in checks:
        pt = Point(px, py)
        candidates = tree.query(pt)
        found = None
        for ci in candidates:
            if geoms[ci].contains(pt):
                found = cats[ci]
                break

        if expected_cat:
            if found == expected_cat:
                status = "match"
            elif found is None:
                status = "coverage_gap"
            else:
                status = "mismatch"
        else:
            status = "info"

        results.append({
            "name": name,
            "lon": px,
            "lat": py,
            "expected": expected_cat,
            "found": found,
            "status": status,
        })

    return results


# ── Console output ────────────────────────────────────────────────────

def print_validation(
    geojson: dict,
    bbox: tuple[float, float, float, float],
) -> None:
    """Print validation stats to stdout (legacy interface)."""
    stats = compute_area_stats(geojson, bbox)
    bbox_area = stats["bbox_area_km2"]
    total_area = stats["total_area_km2"]
    cat_area = stats["category_areas"]

    print(f"\n  === Validation ===")
    print(f"  Bbox area: {bbox_area:.1f} km²")
    print(
        f"  Total zoned area: {total_area:.1f} km²"
        f" ({total_area / bbox_area * 100:.1f}% of bbox)"
    )
    for cat, area in sorted(cat_area.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {area:.1f} km² ({area / bbox_area * 100:.1f}%)")

    print(f"\n  === Geographic Sanity Checks ===")
    results = run_sanity_checks(geojson)
    for r in results:
        if r["expected"]:
            if r["status"] == "match":
                status = "✓"
            else:
                status = f"✗ (got {r['found']})"
        else:
            status = f"→ {r['found']}" if r["found"] else "→ outside all zones"
        print(f"    {r['name']}: {status}")


# ── PNG report generation ─────────────────────────────────────────────

def generate_area_chart(
    geojson: dict,
    bbox: tuple[float, float, float, float],
    output_path: str | Path,
) -> Path:
    """Generate a horizontal bar chart of zoning area by category."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    stats = compute_area_stats(geojson, bbox)
    cat_area = stats["category_areas"]

    # Sort by area descending
    cats = sorted(cat_area.keys(), key=lambda c: cat_area[c])
    areas = [cat_area[c] for c in cats]

    colors = {
        "water": "#2196F3",
        "industrial": "#FF9800",
        "residential": "#9C27B0",
        "green": "#4CAF50",
        "commercial": "#F44336",
    }
    bar_colors = [colors.get(c, "#757575") for c in cats]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(cats, areas, color=bar_colors, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Area (km²)", fontsize=11)
    ax.set_title("Zoning Area by Category", fontsize=13, fontweight="bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Annotate bars
    for i, (cat, area) in enumerate(zip(cats, areas)):
        pct = area / stats["bbox_area_km2"] * 100
        ax.text(
            area + 2,
            i,
            f"{area:.1f} km² ({pct:.1f}%)",
            va="center",
            fontsize=9,
        )

    plt.tight_layout()
    out = Path(output_path)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved area chart: {out}")
    return out


def generate_sanity_check_map(
    geojson: dict,
    bbox: tuple[float, float, float, float],
    output_path: str | Path,
) -> Path:
    """Generate a scatter-plot map of sanity-check points on the bbox."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    south, west, north, east = bbox
    results = run_sanity_checks(geojson)

    fig, ax = plt.subplots(figsize=(8, 8))

    # Draw bbox outline
    ax.add_patch(
        mpatches.Rectangle(
            (west, south),
            east - west,
            north - south,
            linewidth=2,
            edgecolor="#333",
            facecolor="#f0f4f8",
            zorder=0,
        )
    )

    # Plot zoning polygons (sampled for speed)
    from shapely.geometry import shape as shapely_shape

    cat_colors = {
        "water": "#2196F350",
        "industrial": "#FF980050",
        "residential": "#9C27B050",
        "green": "#4CAF5050",
        "commercial": "#F4433650",
    }

    for feat in geojson["features"][:500]:  # sample for speed
        geom = shapely_shape(feat["geometry"])
        cat = feat["properties"]["zoning_category"]
        color = cat_colors.get(cat, "#75757530")
        if geom.geom_type == "Polygon":
            xs, ys = geom.exterior.xy
            ax.fill(xs, ys, color=color, linewidth=0)

    # Plot sanity check points
    status_styles = {
        "match": {"color": "#4CAF50", "marker": "o", "label": "Match"},
        "coverage_gap": {
            "color": "#FFC107",
            "marker": "s",
            "label": "Coverage gap",
        },
        "mismatch": {"color": "#F44336", "marker": "X", "label": "Mismatch"},
        "info": {"color": "#2196F3", "marker": "D", "label": "Info"},
    }

    plotted_labels: set[str] = set()
    for r in results:
        style = status_styles[r["status"]]
        label = style["label"] if style["label"] not in plotted_labels else None
        plotted_labels.add(style["label"])
        ax.scatter(
            r["lon"],
            r["lat"],
            c=style["color"],
            marker=style["marker"],
            s=120,
            edgecolors="white",
            linewidths=1.5,
            zorder=10,
            label=label,
        )
        # Point label
        short_name = r["name"].split("(")[0].strip()
        ax.annotate(
            short_name,
            (r["lon"], r["lat"]),
            xytext=(8, 8),
            textcoords="offset points",
            fontsize=7,
            fontweight="bold",
            color="#333",
            zorder=11,
        )

    ax.set_xlim(west - 0.02, east + 0.02)
    ax.set_ylim(south - 0.02, north + 0.02)
    ax.set_xlabel("Longitude", fontsize=10)
    ax.set_ylabel("Latitude", fontsize=10)
    ax.set_title(
        "Geographic Sanity Checks — Chennai Zoning",
        fontsize=12,
        fontweight="bold",
    )
    ax.legend(loc="lower right", fontsize=9)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    out = Path(output_path)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved sanity check map: {out}")
    return out


def generate_sliver_comparison(
    sliver_coords: list[tuple[float, float]],
    point: tuple[float, float],
    label: str,
    output_path: str | Path,
) -> Path:
    """Generate a visualization of a force-closed sliver polygon
    showing how it falsely contained a test point."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 8))

    xs = [c[0] for c in sliver_coords]
    ys = [c[1] for c in sliver_coords]

    # Fill the sliver
    ax.fill(xs, ys, color="#F4433630", edgecolor="#F44336", linewidth=1.5)

    # Mark vertices
    ax.scatter(xs[:-1], ys[:-1], c="#F44336", s=30, zorder=5)

    # Highlight closing edge
    ax.plot(
        [xs[-2], xs[-1]],
        [ys[-2], ys[-1]],
        color="#F44336",
        linewidth=3,
        linestyle="--",
        label="Force-closing edge",
        zorder=4,
    )

    # Plot test point
    ax.scatter(
        point[0],
        point[1],
        c="#4CAF50",
        marker="*",
        s=200,
        edgecolors="white",
        linewidths=1.5,
        zorder=10,
        label=f"Test point ({label})",
    )

    ax.set_xlabel("Longitude", fontsize=10)
    ax.set_ylabel("Latitude", fontsize=10)
    ax.set_title(
        f"Force-Closed Sliver at {label}",
        fontsize=12,
        fontweight="bold",
    )
    ax.legend(fontsize=9)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    out = Path(output_path)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved sliver comparison: {out}")
    return out
