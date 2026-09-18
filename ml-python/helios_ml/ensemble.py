"""
Helios LST Multi-Model Ensemble Training (Base vs Tuned)
"""

from __future__ import annotations

import gc
import json
import time
from pathlib import Path

import joblib
import numpy as np
import polars as pl
import typer
from rich.console import Console

from xgboost import XGBRegressor
from lightgbm import LGBMRegressor
from catboost import CatBoostRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer

from helios_ml.data import load
from helios_ml.evaluate import evaluate_model, print_comparison_table, shap_dependence_plots, SHAP_MAX_ROWS
from helios_ml.split import temporal_split

app = typer.Typer(help="Helios LST Multi-Model Ensemble CLI")
console = Console()

PREDICT_CHUNK_ROWS = 1_000_000


def slug(name: str) -> str:
    return name.replace(" ", "_").replace("(", "").replace(")", "").lower()


def predict_in_chunks(model, X: np.ndarray, chunk_rows: int = PREDICT_CHUNK_ROWS) -> np.ndarray:
    """Predict in row chunks into a preallocated float32 array.

    Avoids the memory spike of a single .predict() call over millions of rows.
    """
    n = X.shape[0]
    out = np.empty(n, dtype=np.float32)
    for start in range(0, n, chunk_rows):
        stop = min(start + chunk_rows, n)
        out[start:stop] = model.predict(X[start:stop]).astype(np.float32)
    return out



def get_base_models(seed: int) -> list[tuple[str, any]]:
    """Return the 4 base models using default parameters."""
    return [
        ("XGBoost (Base)", XGBRegressor(tree_method="hist", random_state=seed, n_jobs=-1)),
        ("LightGBM (Base)", LGBMRegressor(random_state=seed, n_jobs=-1, verbose=-1)),
        ("CatBoost (Base)", CatBoostRegressor(
            random_state=seed, verbose=100, thread_count=4,
            border_count=64, used_ram_limit='4gb',
        )),
        ("GradientBoost (Base)", Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("model", HistGradientBoostingRegressor(random_state=seed))
        ])),
    ]


def get_tuned_models(seed: int) -> list[tuple[str, any]]:
    """Return the 4 models using literature-standard tuned hyperparameters.
    
    Rationale for parameters:
    - XGBoost: deeper trees (max_depth=8) and row/col subsampling (0.8) are standard 
      for spatial/RS datasets to prevent overfitting while capturing interactions (Chen & Guestrin 2016).
    - LightGBM: similar to XGBoost for comparability, though it uses leaf-wise growth (Ke et al 2017).
    - CatBoost: default depth is often 6, but 8 aligns with the others.
    - GradientBoost: slower sequential implementation, so n_estimators is reduced compared to XGB, 
      with a higher learning rate and smaller depth (Friedman 2001 default scaling).
    """
    return [
        ("XGBoost (Tuned)", XGBRegressor(
            tree_method="hist", n_estimators=500, max_depth=8, learning_rate=0.05, 
            subsample=0.8, colsample_bytree=0.8, random_state=seed, n_jobs=-1
        )),
        ("LightGBM (Tuned)", LGBMRegressor(
            n_estimators=500, max_depth=8, learning_rate=0.05, 
            subsample=0.8, colsample_bytree=0.8, random_state=seed, n_jobs=-1, verbose=-1
        )),
        ("CatBoost (Tuned)", CatBoostRegressor(
            iterations=500, depth=8, learning_rate=0.05,
            subsample=0.8, random_state=seed, verbose=100, thread_count=4,
            border_count=64, used_ram_limit='4gb',
        )),
        ("GradientBoost (Tuned)", Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("model", HistGradientBoostingRegressor(
                max_iter=100, max_depth=5, learning_rate=0.1, 
                random_state=seed
            ))
        ])),
    ]


@app.command()
def train_ensemble(
    data_dir: str = typer.Option(
        "/mnt/f/helios-archive/staging/dense",
        "--data-dir",
        help="Path to dense Parquet matrix.",
    ),
    reports_dir: str = typer.Option(
        "/mnt/f/helios-archive/reports/ml-ensemble",
        "--reports-dir",
        help="Directory for output metrics.",
    ),
    sample_strategy: str = typer.Option(
        "none", "--sample-strategy", help="Spatial sampling strategy."
    ),
    sample_rate: float = typer.Option(
        0.1, "--sample-rate", help="Fraction of rows to keep."
    ),
    split_strategy: str = typer.Option(
        "dynamic",
        "--split-strategy",
        help="Temporal split rule: 'dynamic' (rolling 12-month window) or 'marker' (pipeline-written calendar-year partition labels, e.g. fixed 2025-2026 test window).",
    ),
    random_seed: int = typer.Option(42, "--seed", help="Random seed."),
) -> None:
    console.print("\n[bold cyan]═══ Helios ML Ensemble Pipeline ═══[/bold cyan]\n")

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)

    # 1. Load Data
    console.print("[bold]1. Data Loading[/bold]")
    full_df, feature_df = load(
        data_dir,
        full_resolution=(sample_strategy == "none"),
        sample_strategy=sample_strategy,  # type: ignore
        sample_rate=sample_rate,
    )

    # 2. Split Temporal
    if split_strategy == "dynamic":
        console.print("[bold]2. Temporal Split (dynamic rolling 12-month window)[/bold]")
    elif split_strategy == "marker":
        console.print("[bold]2. Temporal Split (fixed calendar-year window from partition markers)[/bold]")
    else:
        console.print(f"[red]Unknown --split-strategy '{split_strategy}' (use 'dynamic' or 'marker')[/red]")
        raise typer.Exit(code=2)
    target = full_df["lst"]
    X_train_df, X_test_df, y_train, y_test = temporal_split(feature_df, target, strategy=split_strategy)
    
    # 3. Add cyclic DOY feature
    from helios_ml.train import _add_seasonal_feature
    X_train_df = _add_seasonal_feature(X_train_df, full_df)
    X_test_df = _add_seasonal_feature(X_test_df, full_df)

    # 4. Leakage Guard
    NON_FEATURE_COLS = ("tile_id", "year", "month", "timestamp", "doy", "split", "has_thermal_split", "lulc_class", "lulc_count")
    LEAKAGE_COLS = ("ST_B10",)
    NULL_COLS = ("bt10", "bt11", "bt10_minus_bt11")
    EXCLUDE_FEATURES = ("pv", "eps10", "eps11", "ndbi")
    DROP_COLS = NON_FEATURE_COLS + LEAKAGE_COLS + NULL_COLS + EXCLUDE_FEATURES

    drop_train = [c for c in DROP_COLS if c in X_train_df.columns]
    drop_test = [c for c in DROP_COLS if c in X_test_df.columns]
    X_train_df = X_train_df.drop(drop_train)
    X_test_df = X_test_df.drop(drop_test)

    feature_names = list(X_train_df.columns)
    
    X_train = X_train_df.to_numpy().astype(np.float32)
    X_test = X_test_df.to_numpy().astype(np.float32)
    y_train_arr = y_train.to_numpy().astype(np.float32)
    y_test_arr = y_test.to_numpy().astype(np.float32)

    del full_df, feature_df, target, X_train_df, X_test_df, y_train, y_test
    gc.collect()

    console.print(f"  Train: {len(X_train)} rows | Test: {len(X_test)} rows")
    console.print(f"  Features ({len(feature_names)}): {feature_names}\n")

    # 5. Define Model Architectures
    base_estimators = get_base_models(random_seed)
    tuned_estimators = get_tuned_models(random_seed)

    metrics_path = reports_path / "ensemble_metrics.json"
    models_path = reports_path / "models"
    models_path.mkdir(parents=True, exist_ok=True)

    all_results = {}
    if metrics_path.exists():
        try:
            with open(metrics_path, "r") as f:
                all_results = json.load(f)
            console.print(f"[bold green]  Loaded checkpoint with {len(all_results)} completed models.[/bold green]")
        except Exception:
            pass

    console.print("[bold]3. Training & Evaluation[/bold]")

    preds_cache: dict[str, np.ndarray] = {}

    def get_or_make_preds(name: str, model) -> np.ndarray | None:
        """Return cached test predictions for a model, retraining it if needed.

        On resume, loads the serialized model from disk instead of refitting.
        Returns None only if the model cannot be produced.
        """
        if name in preds_cache:
            return preds_cache[name]

        model_file = models_path / f"{slug(name)}.joblib"
        if model_file.exists():
            console.print(f"  Loading serialized model for {name}...")
            model = joblib.load(model_file)
        else:
            t0 = time.perf_counter()
            console.print(f"  Training {name}...")
            model.fit(X_train, y_train_arr)
            joblib.dump(model, model_file)
            console.print(f"    ✓ fit done in {time.perf_counter() - t0:.1f}s — model serialized to {model_file}")

        preds_cache[name] = predict_in_chunks(model, X_test)
        gc.collect()
        return preds_cache[name]

    def train_and_eval(name: str, model) -> None:
        shap_sample_n = min(len(X_test), SHAP_MAX_ROWS)

        if name in all_results:
            console.print(f"  [yellow]{name} already in checkpoint — ensuring predictions available[/yellow]")
            get_or_make_preds(name, model)
            return

        preds = get_or_make_preds(name, model)
        if preds is None:
            return

        if len(X_test) == 0:
            metrics = {"mae": float("nan"), "rmse": float("nan"), "r2": float("nan"), "mape_pct": float("nan")}
        else:
            metrics = evaluate_model(y_test_arr, preds)

        metrics["shap_sample_rows"] = shap_sample_n
        elapsed_line = f"    ✓ Done | RMSE: {metrics['rmse']:.3f} | R²: {metrics['r2']:.3f} | SHAP n={shap_sample_n}"
        console.print(elapsed_line)
        all_results[name] = metrics

        console.print(f"    Generating SHAP for {name} (bounded sample: {shap_sample_n} rows)...")
        shap_data = X_test if len(X_test) > 0 else X_train[:1000]
        shap_dependence_plots(model, name, shap_data, feature_names, str(reports_path), random_seed)

        with open(metrics_path, "w") as f:
            json.dump(all_results, f, indent=2)

        gc.collect()

    def eval_mean_ensemble(name: str, member_names: list[str]) -> None:
        """Evaluate the equal-weight mean ensemble from cached test predictions."""
        if name in all_results:
            console.print(f"  [yellow]Skipping {name} (already in checkpoint)[/yellow]")
            return
        missing = [m for m in member_names if m not in preds_cache]
        if missing:
            console.print(f"  [red]Skipping {name}: missing predictions for {missing}[/red]")
            return
        console.print(f"  Building {name} (averaging {len(member_names)} prediction vectors)...")
        stacked = np.mean([preds_cache[m] for m in member_names], axis=0).astype(np.float32)
        metrics = evaluate_model(y_test_arr, stacked)
        metrics["members"] = member_names
        console.print(f"    ✓ {name} | RMSE: {metrics['rmse']:.3f} | R²: {metrics['r2']:.3f}")
        all_results[name] = metrics
        with open(metrics_path, "w") as f:
            json.dump(all_results, f, indent=2)

    # Base Models
    for name, model in base_estimators:
        train_and_eval(name, model)
    eval_mean_ensemble("Base Ensemble", [n for n, _ in base_estimators])

    # Tuned Models
    for name, model in tuned_estimators:
        train_and_eval(name, model)
    eval_mean_ensemble("Tuned Ensemble", [n for n, _ in tuned_estimators])


    # 6. Final Report
    console.print("\n[bold cyan]Final Results[/bold cyan]")
    print_comparison_table(all_results, console)

    console.print(f"\n[bold green]═══ Pipeline complete ═══[/bold green]")


if __name__ == "__main__":
    app()
