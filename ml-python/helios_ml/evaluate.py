"""
3.4 — Evaluation (SHAP)

Reports RMSE, MAE, R² on the held-out test years and also evaluates
LST_single_channel as a baseline.  Generates SHAP summary/dependence
plots confirming the model leverages the BT10_minus_BT11 thermal
differential term.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from rich.console import Console
from rich.table import Table
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def evaluate_model(
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> dict[str, float]:
    """Compute regression metrics.

    Returns dictionary with MAE, RMSE, R², and MAPE.
    """
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = float(r2_score(y_true, y_pred))

    mask = y_true != 0
    if mask.any():
        mape = float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)
    else:
        mape = float("nan")

    return {"mae": mae, "rmse": rmse, "r2": r2, "mape_pct": mape}


def print_metrics_table(
    metrics: dict[str, float],
    title: str = "[bold]Evaluation Metrics[/bold]",
    console: Console | None = None,
) -> None:
    """Render metrics as a Rich table."""
    if console is None:
        console = Console()

    table = Table(title=title, show_header=True, header_style="bold magenta")
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


def evaluate_and_report(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    console: Console | None = None,
) -> dict[str, float]:
    """Compute metrics and print them, returning the metric dict."""
    metrics = evaluate_model(y_true, y_pred)
    print_metrics_table(metrics, console=console)
    return metrics


def eval_baseline_lst_single_channel(
    y_true_lst_split: np.ndarray,
    y_pred_baseline: np.ndarray,
    console: Console | None = None,
) -> None:
    """Evaluate ST_B10 as a naive single-channel predictor of LST_split_window.

    If the split-window target is more learnable/consistent than the raw
    single-channel retrieval, the model's error should be lower than this
    baseline.
    """
    metrics = evaluate_model(y_true_lst_split, y_pred_baseline)
    print_metrics_table(
        metrics,
        title="[bold]Baseline: ST_B10 (single-channel)[/bold]",
        console=console,
    )


def shap_dependence_plots(
    model,
    X_test: np.ndarray,
    feature_names: list[str],
    out_dir: str | Path = "./reports",
) -> None:
    """Generate SHAP dependence plots for key physical features.

    Produces dependence plots for:
      - bt10_minus_bt11  (thermal differential — split-window driver)
      - ndvi             (vegetation index — modulates emissivity)
      - zoning_category_encoded  (land-cover LST bias)

    Also saves SHAP summary bar and dot plots.

    Note: matplotlib must be installed (part of pyproject.toml deps).
    shap must be installed separately (see pyproject.toml notes).
    """
    try:
        import shap as _shap
    except ImportError as exc:
        print(f"  SKIP SHAP plots — shap not available ({exc}). "
              f"Install with: uv pip install 'llvmlite>=0.47.0' 'shap'")
        return

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    explainer = _shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)

    key_features = ["bt10_minus_bt11", "ndvi", "zoning_category_encoded"]
    present = [f for f in key_features if f in feature_names]

    for feat in present:
        idx = feature_names.index(feat)
        _shap.dependence_plot(
            idx, shap_values, X_test,
            feature_names=feature_names, show=False,
        )
        fig_path = out_path / f"shap_dependence_{feat}.png"
        plt.savefig(str(fig_path), dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  SHAP dependence ({feat}): {fig_path}")

    # Summary bar plot (top-10).
    _shap.summary_plot(
        shap_values, X_test, feature_names=feature_names,
        plot_type="bar", show=False,
    )
    fig_path = out_path / "shap_summary_bar.png"
    plt.savefig(str(fig_path), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  SHAP summary bar: {fig_path}")

    # Summary dot plot.
    _shap.summary_plot(
        shap_values, X_test, feature_names=feature_names, show=False,
    )
    fig_path = out_path / "shap_summary_dot.png"
    plt.savefig(str(fig_path), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  SHAP summary dot: {fig_path}")
