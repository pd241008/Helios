


"""
Helios Dry Run — raw parquet → XGBoost → heatmaps
Bypasses Scala/Spark, does pivot + LST + training + heatmap in Python.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import polars as pl
import xgboost as xgb

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "staging" / "raw" / "landsat"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"
MODEL_PATH = REPORTS_DIR / "lst_model.json"
METRICS_PATH = REPORTS_DIR / "metrics.json"

# Planck constants for Landsat 8/9 Band 10
K1_B10 = 774.8853
K2_B10 = 1321.0789

NDVI_VEG = 0.5
NDVI_SOIL = 0.2


def radiance_to_bt(radiance: pl.Expr, k1: float, k2: float) -> pl.Expr:
    """TOA brightness temperature in Kelvin from thermal band radiance."""
    return k2 / (k1 / radiance + 1.0).log()


def compute_lst(ndvi: pl.Expr, bt10: pl.Expr) -> pl.Expr:
    """Single-channel LST using NDVI-based emissivity correction."""
    pv = ((ndvi - NDVI_SOIL) / (NDVI_VEG - NDVI_SOIL)).clip(0, 1)
    eps10 = 0.004 * pv + 0.986
    return bt10 / (eps10 ** 0.25)


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print("═══ Helios Dry Run Pipeline ═══")

    # ── 1. Load raw parquet ─────────────────────────────────────────
    print("\n1. Loading raw parquet files...")
    parquet_files = [str(p) for p in sorted(RAW_DIR.glob("*.parquet"))]
    print(f"   Found {len(parquet_files)} files")
    df = pl.scan_parquet(parquet_files).collect()
    print(f"   Rows: {df.shape[0]:,}, Cols: {df.shape[1]}")
    print(f"   Bands: {df['band'].unique().to_list()}")

    # ── 2. Pivot wide ───────────────────────────────────────────────
    print("\n2. Pivoting to wide format...")
    wide = df.pivot(
        index=["tile_id", "lat", "lon", "timestamp"],
        columns="band",
        values="value",
        aggregate_function="first",
    )
    wide = wide.with_columns(
        pl.from_epoch(pl.col("timestamp"), time_unit="ms").dt.year().alias("year")
    )
    print(f"   Wide pixels: {wide.shape[0]:,}")
    print(f"   Columns: {wide.columns}")

    # ── 3. Compute NDVI, NDBI, LST ──────────────────────────────────
    print("\n3. Computing biophysical indices & LST...")
    has_nir = "B5_NIR" in wide.columns
    has_red = "B4_Red" in wide.columns
    has_swir1 = "B6_SWIR1" in wide.columns
    has_bt10 = "B10_TIR" in wide.columns

    if has_nir and has_red:
        wide = wide.with_columns(
            ((pl.col("B5_NIR") - pl.col("B4_Red")) / (pl.col("B5_NIR") + pl.col("B4_Red") + 1e-10)).alias("ndvi")
        )
    if has_swir1 and has_nir:
        wide = wide.with_columns(
            ((pl.col("B6_SWIR1") - pl.col("B5_NIR")) / (pl.col("B6_SWIR1") + pl.col("B5_NIR") + 1e-10)).alias("ndbi")
        )
    if has_bt10:
        wide = wide.with_columns(
            radiance_to_bt(pl.col("B10_TIR"), K1_B10, K2_B10).alias("bt10")
        )
    if "bt10" in wide.columns and "ndvi" in wide.columns:
        wide = wide.with_columns(
            compute_lst(pl.col("ndvi"), pl.col("bt10")).alias("lst")
        )

    print(f"   Columns now: {wide.columns}")

    # Drop rows with null LST
    n_before = len(wide)
    wide = wide.drop_nulls(subset=["lst"])
    print(f"   Pixels with LST: {len(wide):,} / {n_before:,}")

    # ── 4. Train/test split (temporal: earlier → train, later → test) ─
    print("\n4. Temporal train/test split...")
    years = sorted(wide["year"].unique().to_list())
    print(f"   Years present: {years}")
    # For 2023 only, use random 80/20
    n = len(wide)
    indices = np.arange(n)
    np.random.seed(42)
    np.random.shuffle(indices)
    n_train = int(n * 0.8)
    train = wide[indices[:n_train]]
    test = wide[indices[n_train:]]
    print(f"   Train: {len(train):,}  Test: {len(test):,}")

    # ── 5. Prepare features ─────────────────────────────────────────
    print("\n5. Preparing features...")
    feature_cols = [c for c in wide.columns if c not in (
        "tile_id", "timestamp", "year", "lst", "bt10"
    ) and wide[c].dtype in (pl.Float32, pl.Float64)]
    print(f"   Feature columns: {feature_cols}")

    # Drop rows with any null features
    train_clean = train.drop_nulls(subset=feature_cols)
    test_clean = test.drop_nulls(subset=feature_cols)

    X_train = train_clean.select(feature_cols).to_numpy().astype(np.float32)
    y_train = train_clean["lst"].to_numpy().astype(np.float32)

    X_test = test_clean.select(feature_cols).to_numpy().astype(np.float32)
    y_test = test_clean["lst"].to_numpy().astype(np.float32)

    print(f"   Train: {X_train.shape}, Test: {X_test.shape}")

    # ── 6. Train XGBoost ────────────────────────────────────────────
    print("\n6. Training XGBoost model...")
    n_val = max(1, int(len(X_train) * 0.15))
    X_val, y_val = X_train[:n_val], y_train[:n_val]
    X_train_fit, y_train_fit = X_train[n_val:], y_train[n_val:]

    dtrain = xgb.DMatrix(X_train_fit, label=y_train_fit, feature_names=feature_cols)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_cols)

    params = {
        "objective": "reg:squarederror",
        "tree_method": "hist",
        "max_depth": 10,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "seed": 42,
        "verbosity": 0,
    }

    t0 = time.perf_counter()
    model = xgb.train(
        params, dtrain, num_boost_round=500,
        evals=[(dtrain, "train"), (dval, "val")],
        early_stopping_rounds=50, verbose_eval=False,
    )
    elapsed = time.perf_counter() - t0
    print(f"   Training: {elapsed:.1f}s, best iteration: {model.best_iteration + 1}")

    # ── 7. Evaluate ─────────────────────────────────────────────────
    print("\n7. Evaluating on test set...")
    dtest = xgb.DMatrix(X_test, feature_names=feature_cols)
    y_pred = model.predict(dtest)

    mae = float(np.mean(np.abs(y_test - y_pred))) if len(y_test) > 0 else 0.0
    rmse = float(np.sqrt(np.mean((y_test - y_pred) ** 2))) if len(y_test) > 0 else 0.0
    r2 = float(1 - np.sum((y_test - y_pred) ** 2) / np.sum((y_test - y_test.mean()) ** 2)) if len(y_test) > 0 else 0.0

    metrics = {"mae": mae, "rmse": rmse, "r2": r2}
    print(f"   MAE: {mae:.2f} K,  RMSE: {rmse:.2f} K,  R²: {r2:.4f}")

    # Save model and metrics
    model.save_model(str(MODEL_PATH))
    with open(METRICS_PATH, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"   Model: {MODEL_PATH}")
    print(f"   Metrics: {METRICS_PATH}")

    # ── 8. Generate heatmaps ────────────────────────────────────────
    print("\n8. Generating heatmaps...")
    heatmap_data = test_clean if len(test_clean) > 100 else train_clean
    _generate_heatmaps(heatmap_data, feature_cols, model, REPORTS_DIR)

    print("\n═══ Dry run complete ═══")
    print(f"   Reports: {REPORTS_DIR}")


def _generate_heatmaps(
    df: pl.DataFrame,
    feature_cols: list[str],
    model: xgb.Booster,
    out_dir: Path,
) -> None:
    """Generate LST heatmap (predicted vs actual) for the top 5000 test pixels."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    top = df.sort("timestamp", descending=True).head(5000)
    X_top = top.select(feature_cols).to_numpy().astype(np.float32)
    y_true = top["lst"].to_numpy().astype(np.float32)
    y_pred = model.predict(xgb.DMatrix(X_top, feature_names=feature_cols))

    # ── Scatter: predicted vs actual ────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    ax = axes[0]
    ax.scatter(y_true - 273.15, y_pred - 273.15, s=1, alpha=0.3, c="#1f77b4")
    lims = [
        min(y_true.min(), y_pred.min()) - 273.15 - 2,
        max(y_true.max(), y_pred.max()) - 273.15 + 2,
    ]
    ax.plot(lims, lims, "r--", lw=1, alpha=0.6)
    ax.set_xlabel("Actual LST (°C)")
    ax.set_ylabel("Predicted LST (°C)")
    ax.set_title(f"Predicted vs Actual (n={len(y_true)})")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    # ── Error histogram ─────────────────────────────────────────────
    ax = axes[1]
    errors = (y_pred - y_true) * 1.0
    ax.hist(errors, bins=60, alpha=0.7, color="#1f77b4", edgecolor="white")
    ax.axvline(0, color="r", linestyle="--", alpha=0.6)
    ax.set_xlabel("Error (Predicted − Actual) °C")
    ax.set_ylabel("Frequency")
    ax.set_title(f"Error Distribution (MAE={np.mean(np.abs(errors)):.2f}°C)")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    scatter_path = out_dir / "pred_vs_actual.png"
    plt.savefig(scatter_path, dpi=150)
    plt.close()
    print(f"   Scatter plot: {scatter_path}")

    # ── Feature importance ──────────────────────────────────────────
    importance = model.get_score(importance_type="weight")
    names = list(importance.keys())
    scores = list(importance.values())
    fidx = np.argsort(scores)[::-1]
    names_sorted = [names[i] for i in fidx][:15]
    scores_sorted = [scores[i] for i in fidx][:15]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(range(len(names_sorted)), scores_sorted, color="#1f77b4")
    ax.set_yticks(range(len(names_sorted)))
    ax.set_yticklabels(names_sorted)
    ax.set_xlabel("Importance (weight)")
    ax.set_title("Top 15 Feature Importances")
    ax.invert_yaxis()
    plt.tight_layout()
    fi_path = out_dir / "feature_importance.png"
    plt.savefig(fi_path, dpi=150)
    plt.close()
    print(f"   Feature importance: {fi_path}")

    # ── LST map (scatter) ───────────────────────────────────────────
    lat = top["lat"].to_numpy()
    lon = top["lon"].to_numpy()

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    sc = axes[0].scatter(lon, lat, c=y_true - 273.15, s=2, cmap="RdYlBu_r", vmin=25, vmax=45)
    axes[0].set_title("Actual LST (°C)")
    axes[0].set_xlabel("Longitude")
    axes[0].set_ylabel("Latitude")
    plt.colorbar(sc, ax=axes[0])

    sc = axes[1].scatter(lon, lat, c=y_pred - 273.15, s=2, cmap="RdYlBu_r", vmin=25, vmax=45)
    axes[1].set_title("Predicted LST (°C)")
    axes[1].set_xlabel("Longitude")
    axes[1].set_ylabel("Latitude")
    plt.colorbar(sc, ax=axes[1])

    plt.tight_layout()
    map_path = out_dir / "lst_map.png"
    plt.savefig(map_path, dpi=150)
    plt.close()
    print(f"   LST map: {map_path}")


if __name__ == "__main__":
    main()
