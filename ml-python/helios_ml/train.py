"""
Helios ML Training Pipeline.

Loads the dense Parquet matrix produced by the Scala/Spark processing
layer and trains an XGBoost gradient-boosted tree regressor to predict
Land Surface Temperature (LST).

Supports:
  - XGBoost (default): Histogram-based gradient boosting.
  - Random Forest: scikit-learn ensemble for baseline comparison.

Usage:
    uv run python -m helios_ml.train \
        --data-dir ./staging/dense \
        --model-out ./models/lst_model.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import typer
import xgboost as xgb
from rich.console import Console
from rich.table import Table
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

from helios_ml.data_loader import load_with_validation
from helios_ml.evaluate import evaluate_model, print_metrics

app = typer.Typer(help="Helios LST Model Training CLI")
console = Console()


@app.command()
def train(
    data_dir: str = typer.Option(
        "./staging/dense",
        "--data-dir",
        help="Path to dense Parquet matrix from Scala pipeline.",
    ),
    model_out: str = typer.Option(
        "./models/lst_model.json",
        "--model-out",
        help="Path to save the trained model.",
    ),
    algorithm: str = typer.Option(
        "xgboost",
        "--algorithm",
        help="Training algorithm: 'xgboost' or 'random_forest'.",
    ),
    test_size: float = typer.Option(
        0.2,
        "--test-size",
        help="Fraction of data reserved for testing.",
    ),
    random_seed: int = typer.Option(
        42,
        "--seed",
        help="Random seed for reproducibility.",
    ),
    n_estimators: int = typer.Option(
        500,
        "--n-estimators",
        help="Number of boosting rounds / trees.",
    ),
) -> None:
    """Train an LST prediction model on the dense geospatial matrix."""
    console.print("\n[bold cyan]═══ Helios ML Training Pipeline ═══[/bold cyan]\n")

    # ── 1. Load data ──────────────────────────────────────────────
    console.print(f"[dim]Loading data from:[/dim] {data_dir}")
    features, target = load_with_validation(data_dir)

    console.print(f"  Features: {features.shape[0]:,} rows × {features.shape[1]} cols")
    console.print(f"  Target  : {target.name} (mean={target.mean():.2f}, std={target.std():.2f})")

    # Convert to NumPy for sklearn/xgboost.
    X = features.to_numpy().astype(np.float32)
    y = target.to_numpy().astype(np.float32)

    # ── 2. Train/test split ───────────────────────────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_seed
    )
    console.print(f"  Train: {X_train.shape[0]:,}  |  Test: {X_test.shape[0]:,}\n")

    # ── 3. Train model ────────────────────────────────────────────
    t0 = time.perf_counter()

    if algorithm == "xgboost":
        model = _train_xgboost(X_train, y_train, X_test, y_test, n_estimators, random_seed)
    elif algorithm == "random_forest":
        model = _train_random_forest(X_train, y_train, n_estimators, random_seed)
    else:
        console.print(f"[red]Unknown algorithm: {algorithm}[/red]")
        raise typer.Exit(code=1)

    elapsed = time.perf_counter() - t0
    console.print(f"\n[green]✓ Training completed in {elapsed:.1f}s[/green]\n")

    # ── 4. Evaluate ───────────────────────────────────────────────
    if isinstance(model, xgb.Booster):
        dtest = xgb.DMatrix(X_test)
        y_pred = model.predict(dtest)
    else:
        y_pred = model.predict(X_test)

    metrics = evaluate_model(y_test, y_pred)
    print_metrics(metrics, console)

    # ── 5. Save model ─────────────────────────────────────────────
    out_path = Path(model_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(model, xgb.Booster):
        model.save_model(str(out_path))
    else:
        # Persist RF via joblib-compatible JSON metadata.
        import joblib

        joblib_path = out_path.with_suffix(".joblib")
        joblib.save(model, str(joblib_path))
        out_path = joblib_path

    # Save metrics alongside model.
    metrics_path = out_path.with_suffix(".metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)

    console.print(f"[bold green]✓ Model saved to:[/bold green] {out_path}")
    console.print(f"[dim]  Metrics saved to: {metrics_path}[/dim]\n")


def _train_xgboost(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    n_estimators: int,
    seed: int,
) -> xgb.Booster:
    """Train an XGBoost histogram-based gradient boosted tree."""
    console.print("[cyan]Training XGBoost (hist) regressor...[/cyan]")

    dtrain = xgb.DMatrix(X_train, label=y_train)
    dtest = xgb.DMatrix(X_test, label=y_test)

    params: dict[str, str | int | float] = {
        "objective": "reg:squarederror",
        "tree_method": "hist",          # Memory-efficient histogram method
        "max_depth": 8,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "reg_alpha": 0.1,               # L1 regularization
        "reg_lambda": 1.0,              # L2 regularization
        "seed": seed,
        "nthread": -1,
        "verbosity": 1,
    }

    model = xgb.train(
        params,
        dtrain,
        num_boost_round=n_estimators,
        evals=[(dtrain, "train"), (dtest, "test")],
        early_stopping_rounds=50,
        verbose_eval=100,
    )

    return model


def _train_random_forest(
    X_train: np.ndarray,
    y_train: np.ndarray,
    n_estimators: int,
    seed: int,
) -> RandomForestRegressor:
    """Train a scikit-learn Random Forest regressor as a baseline."""
    console.print("[cyan]Training Random Forest regressor...[/cyan]")

    model = RandomForestRegressor(
        n_estimators=n_estimators,
        max_depth=12,
        min_samples_split=10,
        min_samples_leaf=5,
        max_features="sqrt",
        n_jobs=-1,
        random_state=seed,
        verbose=1,
    )
    model.fit(X_train, y_train)
    return model


if __name__ == "__main__":
    app()
