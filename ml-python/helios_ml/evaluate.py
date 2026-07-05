"""
Model evaluation utilities for LST prediction.

Computes standard regression metrics and formats them for console
output using Rich tables.
"""

from __future__ import annotations

import numpy as np
from rich.console import Console
from rich.table import Table
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)


def evaluate_model(
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> dict[str, float]:
    """Compute regression metrics.

    Returns:
        Dictionary with MAE, RMSE, R², and MAPE.
    """
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = float(r2_score(y_true, y_pred))

    # Mean Absolute Percentage Error (guarded against division by zero).
    mask = y_true != 0
    if mask.any():
        mape = float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)
    else:
        mape = float("nan")

    return {
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "mape_pct": mape,
    }


def print_metrics(
    metrics: dict[str, float],
    console: Console | None = None,
) -> None:
    """Render metrics as a Rich table."""
    if console is None:
        console = Console()

    table = Table(
        title="[bold]Evaluation Metrics[/bold]",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    labels = {
        "mae": "Mean Absolute Error",
        "rmse": "Root Mean Squared Error",
        "r2": "R² Score",
        "mape_pct": "MAPE (%)",
    }

    for key, label in labels.items():
        val = metrics.get(key)
        if val is not None:
            table.add_row(label, f"{val:.4f}")

    console.print(table)
