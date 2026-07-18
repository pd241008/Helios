"""
config.py — Category mappings, constants, and excluded tags for OSM → Helios
zoning classification.

This is the single source of truth for how OSM tags map to the 5 Helios
zone categories: residential, commercial, industrial, green, water.
"""

from __future__ import annotations


# ── Default category mapping (OSM tag value → Helios zone category) ───
# Keys are OSM tag values; values are Helios 5-zone categories.
# Any OSM tag not listed here is excluded (not defaulted).
DEFAULT_CATEGORY_MAP: dict[str, str] = {
    # residential
    "residential": "residential",
    # commercial (includes retail, office)
    "commercial":  "commercial",
    "retail":      "commercial",
    "office":      "commercial",
    # industrial (includes construction, brownfield, military)
    "industrial":  "industrial",
    "construction": "industrial",
    "brownfield":  "industrial",
    "military":    "industrial",
    # green (vegetation, parks, agriculture, cemeteries)
    "grass":            "green",
    "farmland":         "green",
    "recreation_ground": "green",
    "cemetery":         "green",
    "forest":           "green",
    "orchard":          "green",
    "village_green":    "green",
    "meadow":           "green",
    "scrub":            "green",
    # leisure tags mapped to green
    "park":             "green",
    "garden":           "green",
    "nature_reserve":   "green",
    # water (natural + infrastructure)
    "water":            "water",
    "wetland":          "water",
    "reservoir":        "water",
    # waterway tags mapped to water
    "riverbank":        "water",
}

# Waterway tags (key=waterway) that map to water
WATERWAY_TO_CATEGORY: dict[str, str] = {
    "river":    "water",
    "canal":    "water",
    "drain":    "water",
    "stream":   "water",
    "ditch":    "water",
    "weir":     "water",
    "dam":      "water",
}

# Tags that we explicitly exclude (not mapped to any category)
EXCLUDED_TAGS: dict[str, set[str]] = {
    "landuse": {"railway", "education", "landfill", "empty plot", "religious"},
    "leisure": {"playground", "sports_centre", "boatyard", "lock_gate"},
    "natural": {"wood", "hill", "bare_rock", "scree", "cliff"},
}

# Geographic sanity-check points: (label, lon, lat, expected_category_or_None)
SANITY_CHECK_POINTS: list[tuple[str, float, float, str | None]] = [
    ("Marina Beach area (water)", 80.282, 13.049, "water"),
    ("T. Nagar (residential/commercial)", 80.234, 13.041, None),
    ("Ennore Creek (water body)", 80.304, 13.220, "water"),
    ("Adyar river area", 80.257, 13.005, "water"),
    ("Guindy National Park", 80.218, 12.984, "green"),
    ("CBD / Fort area", 80.270, 13.090, None),
]

# ── Derived constants ─────────────────────────────────────────────────

# Approximate conversion factor at Chennai's latitude (~13°N)
# 1 deg² ≈ 110.6 × (110.6 × cos(13°)) km²
import math
DEG2_KM2: float = 110.6 * (110.6 * math.cos(math.radians(13.0)))

# Minimum area in degree² — anything smaller is considered degenerate
# At 13°N: 1° ≈ 110km, so 10 m² ≈ (0.00009°)² ≈ 8e-9 deg²
MIN_AREA_DEG2: float = 8e-9
