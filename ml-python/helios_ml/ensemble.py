"""
Helios LST Multi-Model Ensemble Training (Base vs Tuned)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import polars as pl
import typer
from rich.console import Console

from xgboost import XGBRegressor
from lightgbm import LGBMRegressor
from catboost import CatBoostRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, VotingRegressor
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer

from helios_ml.data import load
from helios_ml.evaluate import evaluate_model, print_comparison_table, shap_dependence_plots
from helios_ml.split import temporal_split

app = typer.Typer(help="Helios LST Multi-Model Ensemble CLI")
console = Console()


def get_base_models(seed: int) -> list[tuple[str, any]]:
    """Return the 4 base models using default parameters."""
    return [
        ("XGBoost (Base)", XGBRegressor(tree_method="hist", random_state=seed, n_jobs=-1)),
        ("LightGBM (Base)", LGBMRegressor(random_state=seed, n_jobs=-1, verbose=-1)),
        ("CatBoost (Base)", CatBoostRegressor(random_state=seed, verbose=0, thread_count=-1)),
        ("GradientBoost (Base)", HistGradientBoostingRegressor(random_state=seed)),
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
            subsample=0.8, random_state=seed, verbose=0, thread_count=-1
        )),
        ("GradientBoost (Tuned)", HistGradientBoostingRegressor(
            max_iter=100, max_depth=5, learning_rate=0.1, 
            random_state=seed
        )),
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
    console.print("[bold]2. Temporal Split (Train: 2016-2024, Test: 2025-2026)[/bold]")
    target = full_df["lst"]
    X_train_df, X_test_df, y_train, y_test = temporal_split(feature_df, target)
    
    # 3. Add cyclic DOY feature
    from helios_ml.train import _add_seasonal_feature
    X_train_df = _add_seasonal_feature(X_train_df, full_df)
    X_test_df = _add_seasonal_feature(X_test_df, full_df)

    # 4. Leakage Guard
    NON_FEATURE_COLS = ("tile_id", "year", "month", "timestamp", "doy", "split", "has_thermal_split", "lulc_class", "lulc_count")
    LEAKAGE_COLS = ("ST_B10",)
    NULL_COLS = ("bt10", "bt11", "bt10_minus_bt11")
    DROP_COLS = NON_FEATURE_COLS + LEAKAGE_COLS + NULL_COLS

    drop_train = [c for c in DROP_COLS if c in X_train_df.columns]
    drop_test = [c for c in DROP_COLS if c in X_test_df.columns]
    X_train_df = X_train_df.drop(drop_train)
    X_test_df = X_test_df.drop(drop_test)

    feature_names = list(X_train_df.columns)
    
    X_train = X_train_df.to_numpy().astype(np.float32)
    X_test = X_test_df.to_numpy().astype(np.float32)
    y_train_arr = y_train.to_numpy().astype(np.float32)
    y_test_arr = y_test.to_numpy().astype(np.float32)
    
    console.print(f"  Train: {len(X_train)} rows | Test: {len(X_test)} rows")
    console.print(f"  Features ({len(feature_names)}): {feature_names}\n")

    # 5. Define Model Architectures
    base_estimators = get_base_models(random_seed)
    tuned_estimators = get_tuned_models(random_seed)

    base_ensemble = VotingRegressor(estimators=base_estimators, n_jobs=-1)
    tuned_ensemble = VotingRegressor(estimators=tuned_estimators, n_jobs=-1)

    all_results = {}
    
    console.print("[bold]3. Training & Evaluation[/bold]")
    
    def train_and_eval(name: str, model, is_ensemble: bool = False):
        t0 = time.perf_counter()
        console.print(f"  Training {name}...")
        
        # Scikit-learn API fit
        model.fit(X_train, y_train_arr)
        
        elapsed = time.perf_counter() - t0
        preds = model.predict(X_test)
        metrics = evaluate_model(y_test_arr, preds)
        
        console.print(f"    ✓ Done in {elapsed:.1f}s | RMSE: {metrics['rmse']:.3f} | R²: {metrics['r2']:.3f}")
        all_results[name] = metrics
        
        # Generate SHAP for individual models only
        if not is_ensemble:
            console.print(f"    Generating SHAP for {name}...")
            shap_dependence_plots(model, name, X_test, feature_names, str(reports_path), random_seed)

    # Base Models
    for name, model in base_estimators:
        train_and_eval(name, model)
    train_and_eval("Base Ensemble", base_ensemble, is_ensemble=True)
    
    # Tuned Models
    for name, model in tuned_estimators:
        train_and_eval(name, model)
    train_and_eval("Tuned Ensemble", tuned_ensemble, is_ensemble=True)

    # 6. Final Report
    console.print("\n[bold cyan]Final Results[/bold cyan]")
    print_comparison_table(all_results, console)

    metrics_path = reports_path / "ensemble_metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(all_results, f, indent=2)

    console.print(f"\n[bold green]═══ Pipeline complete ═══[/bold green]")


if __name__ == "__main__":
    app()
