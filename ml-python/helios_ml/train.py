"""
3.3 — Model Training (XGBoost)

Trains an XGBoost regressor predicting LST from engineered features
(NDVI, Pv, emissivity, spatial coordinates, land-cover encodings).

Leakage guard: ST_B10 (the exact-copy single-channel LST) and all-null
thermal columns (bt10, bt11, bt10_minus_bt11) are explicitly excluded
from the feature matrix.  The baseline comparison still evaluates ST_B10
separately for reference.

Usage:
    uv run python -m helios_ml.train \
        --data-dir ../staging/dense \
        --reports-dir ./reports \
        --sample-strategy systematic-grid \
        --sample-rate 0.1
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import polars as pl
import typer
import xgboost as xgb
from rich.console import Console
from rich.table import Table

from helios_ml.data import load
from helios_ml.evaluate import (
    evaluate_and_report,
    shap_dependence_plots,
    eval_baseline_lst_single_channel,
)
from helios_ml.split import temporal_split

app = typer.Typer(help="Helios LST Model Training CLI")
console = Console()


@app.command()
def train(
    data_dir: str = typer.Option(
        "./staging/dense",
        "--data-dir",
        help="Path to dense Parquet matrix from Scala pipeline.",
    ),
    reports_dir: str = typer.Option(
        "./reports",
        "--reports-dir",
        help="Directory for SHAP plots and metrics JSON.",
    ),
    # ── XGBoost hyperparameters (config-exposed) ────────────────
    max_depth: int = typer.Option(8, "--max-depth", help="XGBoost max_depth."),
    learning_rate: float = typer.Option(0.05, "--learning-rate", help="XGBoost eta."),
    n_estimators: int = typer.Option(500, "--n-estimators", help="Max boosting rounds."),
    subsample: float = typer.Option(0.8, "--subsample", help="Row subsample ratio."),
    colsample_bytree: float = typer.Option(0.8, "--colsample-bytree", help="Col subsample ratio."),
    early_stopping_rounds: int = typer.Option(
        50, "--early-stopping-rounds", help="Stop if val loss does not improve for N rounds."
    ),
    val_fraction: float = typer.Option(
        0.15, "--val-fraction", help="Fraction of training years held out for validation."
    ),
    random_seed: int = typer.Option(42, "--seed", help="Random seed."),
    # ── Spatial sampling ──────────────────────────────────────────
    sample_strategy: str = typer.Option(
        "none",
        "--sample-strategy",
        help="Spatial sampling strategy: none | systematic-grid | stratified-zoning.",
    ),
    sample_rate: float = typer.Option(
        0.1,
        "--sample-rate",
        help="Target fraction of rows to keep (0.0–1.0) when sampling is enabled.",
    ),
) -> None:
    """Train an XGBoost LST prediction model."""
    console.print("\n[bold cyan]═══ Helios ML Training Pipeline ═══[/bold cyan]\n")

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)

    # ── 3.1: Data Loading ──────────────────────────────────────────
    console.print("[bold]3.1 —  Data Loading[/bold]")
    full_df, feature_df = load(
        data_dir,
        full_resolution=(sample_strategy == "none"),
        sample_strategy=sample_strategy,  # type: ignore[arg-type]
        sample_rate=sample_rate,
    )
    console.print(f"  Features: {feature_df.shape[1]} cols\n")

    # ── 3.2: Temporal Split ────────────────────────────────────────
    console.print("[bold]3.2 —  Temporal Split[/bold]")
    target = full_df["lst"]
    X_train_df, X_test_df, y_train, y_test = temporal_split(feature_df, target)
    n_total = len(feature_df)
    console.print(
        f"  Train: {len(X_train_df):,} ({len(X_train_df)/n_total:.1%})  "
        f"| Test: {len(X_test_df):,} ({len(X_test_df)/n_total:.1%})\n"
    )

    # ── 3.3: Model Training ────────────────────────────────────────
    console.print("[bold]3.3 —  Model Training[/bold]")

    # Add derived day-of-year seasonal feature.
    X_train_df = _add_seasonal_feature(X_train_df, full_df)
    X_test_df = _add_seasonal_feature(X_test_df, full_df)

    # ── Leakage & noise guard ──────────────────────────────────────
    # Columns that are non-feature identifiers or metadata.
    NON_FEATURE_COLS = ("tile_id", "year", "doy", "split", "has_thermal_split")

    # ST_B10 is the EXACT COPY of the target `lst` when no split-window
    # thermal bands are available (PC L2 source).  Including it would
    # give the model a trivial identity mapping → R² ≈ 1.0 with zero
    # predictive value.  Must be excluded from the feature matrix.
    LEAKAGE_COLS = ("ST_B10",)

    # Columns that are 100% null for Planetary Computer data (no B10_TIR /
    # B11_TIR raw thermal).  They add no signal and clutter feature lists.
    NULL_COLS = ("bt10", "bt11", "bt10_minus_bt11")

    DROP_COLS = NON_FEATURE_COLS + LEAKAGE_COLS + NULL_COLS

    drop_train = [c for c in DROP_COLS if c in X_train_df.columns]
    drop_test = [c for c in DROP_COLS if c in X_test_df.columns]
    X_train_df = X_train_df.drop(drop_train)
    X_test_df = X_test_df.drop(drop_test)

    feature_names = list(X_train_df.columns)

    console.print(f"  [bold]Leakage guard — dropped columns:[/bold] {drop_train}")
    console.print(f"  [bold]Final feature set ({len(feature_names)} cols):[/bold] {feature_names}\n")

    X_train = X_train_df.to_numpy().astype(np.float32)
    X_test = X_test_df.to_numpy().astype(np.float32)
    y_train_arr = y_train.to_numpy().astype(np.float32)
    y_test_arr = y_test.to_numpy().astype(np.float32)

    # Carve a validation slice from the *training* years (not test years).
    n_val = max(1, int(len(X_train) * val_fraction))
    X_val, y_val = X_train[:n_val], y_train_arr[:n_val]
    X_train_fit, y_train_fit = X_train[n_val:], y_train_arr[n_val:]

    dtrain = xgb.DMatrix(X_train_fit, label=y_train_fit)
    dval = xgb.DMatrix(X_val, label=y_val)

    params: dict[str, str | int | float] = {
        "objective": "reg:squarederror",
        "tree_method": "hist",
        "max_depth": max_depth,
        "learning_rate": learning_rate,
        "subsample": subsample,
        "colsample_bytree": colsample_bytree,
        "min_child_weight": 5,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "seed": random_seed,
        "nthread": -1,
        "verbosity": 1,
    }

    t0 = time.perf_counter()
    model = xgb.train(
        params,
        dtrain,
        num_boost_round=n_estimators,
        evals=[(dtrain, "train"), (dval, "val")],
        early_stopping_rounds=early_stopping_rounds,
        verbose_eval=100,
    )
    elapsed = time.perf_counter() - t0
    best_iter = model.best_iteration + 1 if model.best_iteration else n_estimators
    console.print(f"\n[green]✓ Training completed in {elapsed:.1f}s "
                  f"({best_iter} iterations)[/green]\n")

    # Save model.
    model_path = reports_path / "lst_model.json"
    model.save_model(str(model_path))
    console.print(f"[dim]  Model saved: {model_path}[/dim]")

    # ── 3.4: Evaluation (SHAP + baseline) ──────────────────────────
    console.print("[bold]3.4 —  Evaluation[/bold]")

    # Metrics on held-out test years.
    if len(X_test) == 0:
        console.print(
            "\n  [bold red]⚠ DEGENERATE SPLIT: no test partition exists.[/bold red]\n"
            "  All rows carry split='train'.  The val_fraction carve provides\n"
            "  early-stopping feedback but is NOT a held-out evaluation.\n"
            "  Any metrics on this val slice reflect in-sample fit, not\n"
            "  generalization.  Do NOT report R² from this run as a result.\n"
        )
        metrics = {"mae": float("nan"), "rmse": float("nan"), "r2": float("nan"), "mape_pct": float("nan")}
    else:
        dtest = xgb.DMatrix(X_test)
        y_pred = model.predict(dtest)
        metrics = evaluate_and_report(y_test_arr, y_pred, console)

    # Baseline: evaluate LST_single_channel (ST_B10) as a naive predictor.
    console.print("\n[cyan]Baseline comparison: LST_single_channel (ST_B10)[/cyan]")
    st_b10 = full_df["ST_B10"] if "ST_B10" in full_df.columns else None
    if st_b10 is not None:
        # When no test set exists, evaluate on the validation slice
        # (same slice used for early stopping) — still in-sample.
        if len(X_test) > 0:
            st_b10_eval = st_b10.to_numpy().astype(np.float32)
            y_eval = y_test_arr
        elif len(X_val) > 0:
            st_b10_val_idx = full_df["split"] == "train"
            # Reconstruct val indices — val is first n_val rows of train
            st_b10_arr = st_b10.to_numpy().astype(np.float32)
            # Val slice indices correspond to the first n_val train rows
            train_indices = full_df.with_row_index().filter(pl.col("split") == "train")["index"].to_list()
            val_indices = train_indices[:n_val]
            st_b10_eval = st_b10_arr[val_indices]
            y_eval = y_val
            console.print("  [yellow](Evaluating on val slice — no test set)[/yellow]")
        else:
            st_b10_eval = None
            y_eval = None
            console.print("  [yellow]SKIP — no evaluation data available[/yellow]")

        if st_b10_eval is not None and y_eval is not None:
            mismatch = len(st_b10_eval) != len(y_eval)
            if not mismatch:
                eval_baseline_lst_single_channel(y_eval, st_b10_eval, console)
            else:
                console.print("  [yellow]SKIP — shape mismatch between ST_B10 and evaluation split[/yellow]")
    else:
        console.print("  [yellow]SKIP — ST_B10 column not present in dense matrix[/yellow]")

    # Save metrics JSON.
    metrics_path = reports_path / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    console.print(f"[dim]  Metrics saved: {metrics_path}[/dim]\n")

    # SHAP dependence plots.
    if len(X_test) > 0:
        console.print("[cyan]Generating SHAP plots (on test set)...[/cyan]")
        shap_dependence_plots(
            model, X_test, feature_names=feature_names, out_dir=str(reports_path),
        )
        console.print(f"[green]✓ SHAP plots saved to {reports_path}/[/green]")
    elif len(X_val) > 0:
        console.print("[cyan]Generating SHAP plots (on val slice — no test set)...[/cyan]")
        shap_dependence_plots(
            model, X_val, feature_names=feature_names, out_dir=str(reports_path),
        )
        console.print(f"[green]✓ SHAP plots saved to {reports_path}/[/green]")

    console.print("\n[bold green]═══ Pipeline complete ═══[/bold green]")


def _add_seasonal_feature(
    df: pl.DataFrame,
    full_df: pl.DataFrame,
) -> pl.DataFrame:
    """Derive cyclic day-of-year features and attach them to *df*.

    Uses the ``doy`` column (day-of-year, 1–366) from the Scala pipeline's
    ``dayofyear(timestamp)`` extraction.  Produces two features:

    - ``doy_sin = sin(2π × doy / 366)``
    - ``doy_cos = cos(2π × doy / 366)``

    Both are needed because a single sine term cannot distinguish symmetric
    days (e.g. day 90 ≈ day 275 by sine alone).  The cos term breaks that
    symmetry.

    Falls back to the old year-based computation (constant 0) ONLY when
    ``doy`` is genuinely absent (running against an older dense matrix that
    predates the Scala fix).  Logs a clear WARNING when the fallback
    triggers so it's never silently used.
    """
    if len(df) == 0:
        return df

    if "doy" in df.columns:
        phase = (2.0 * np.pi * df["doy"].cast(pl.Float32) / 366.0)
        return df.with_columns([
            phase.sin().alias("doy_sin"),
            phase.cos().alias("doy_cos"),
        ])

    # ── Fallback: old year-based computation (pre-doy-fix matrices) ──
    print(
        "  \033[93mWARNING: 'doy' column not found — falling back to "
        "year-based doy_sin (constant 0).\033[0m\n"
        "  This means the seasonal feature is BROKEN. Re-run the Scala "
        "pipeline to generate a dense matrix with the 'doy' column."
    )
    if "year" not in df.columns:
        print("  WARNING: no year column available for seasonal feature — skipping")
        return df

    year_min = full_df["year"].min()
    doy_sin = (
        (2.0 * np.pi * (df["year"] - year_min).cast(pl.Float32) / 366.0).sin().alias("doy_sin")
    )
    doy_cos = (
        (2.0 * np.pi * (df["year"] - year_min).cast(pl.Float32) / 366.0).cos().alias("doy_cos")
    )
    return df.with_columns([doy_sin, doy_cos])


if __name__ == "__main__":
    app()
