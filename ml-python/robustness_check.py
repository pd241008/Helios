import json
import numpy as np
import polars as pl
import xgboost as xgb
from helios_ml.data import load
from helios_ml.split import temporal_split

def run_robustness(data_dir, dataset_name):
    print(f"\n=============================================")
    print(f"Running DuckDB Robustness Check for {dataset_name}")
    print(f"=============================================")
    
    print(f"Loading data from {data_dir}...")
    full_df, feature_df = load(data_dir, full_resolution=True, sample_strategy="none", sample_rate=0.1)
    
    # Handle the fact that Bangalore target might be lst_k while Chennai target is lst
    # Wait, the load() function handles this, but let's check what it returns
    # Actually, temporal_split expects a Series.
    # In robustness_check.py earlier, it did target = full_df["lst"].
    if "lst_k" in full_df.columns:
        target = full_df["lst_k"]
    elif "lst" in full_df.columns:
        target = full_df["lst"]
    else:
        raise ValueError(f"Could not find lst or lst_k in columns: {full_df.columns}")
        
    print("Applying temporal split...")
    X_train_df, X_test_df, y_train, y_test = temporal_split(feature_df, target)
    
    def _add_seasonal_feature(df, full_df):
        phase = (2.0 * np.pi * df["doy"].cast(pl.Float32) / 366.0)
        return df.with_columns([
            phase.sin().alias("doy_sin"),
            phase.cos().alias("doy_cos"),
        ])
    
    X_train_df = _add_seasonal_feature(X_train_df, full_df)
    X_test_df = _add_seasonal_feature(X_test_df, full_df)
    
    NON_FEATURE_COLS = ("tile_id", "year", "month", "timestamp", "doy", "split", "has_thermal_split", "lulc_class", "lulc_count")
    LEAKAGE_COLS = ("ST_B10",)
    NULL_COLS = ("bt10", "bt11", "bt10_minus_bt11")
    
    # DROP ZONING to simulate the DuckDB LULC-proxy pipeline!
    EXCLUDE_FEATURES = ("zoning_category_encoded",)
    
    DROP_COLS = NON_FEATURE_COLS + LEAKAGE_COLS + NULL_COLS + EXCLUDE_FEATURES
    
    drop_train = [c for c in DROP_COLS if c in X_train_df.columns]
    drop_test = [c for c in DROP_COLS if c in X_test_df.columns]
    
    X_train_df = X_train_df.drop(drop_train)
    X_test_df = X_test_df.drop(drop_test)
    
    print(f"Features: {X_train_df.columns}")
    
    X_train = X_train_df.to_numpy().astype(np.float32)
    X_test = X_test_df.to_numpy().astype(np.float32)
    y_train_arr = y_train.to_numpy().astype(np.float32)
    y_test_arr = y_test.to_numpy().astype(np.float32)
    
    n_val = max(1, int(len(X_train) * 0.15))
    X_val, y_val = X_train[:n_val], y_train_arr[:n_val]
    X_train_fit, y_train_fit = X_train[n_val:], y_train_arr[n_val:]
    
    dtrain = xgb.DMatrix(X_train_fit, label=y_train_fit)
    dval = xgb.DMatrix(X_val, label=y_val)
    dtest = xgb.DMatrix(X_test)
    
    params = {
        "objective": "reg:squarederror",
        "tree_method": "hist",
        "max_depth": 8,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "seed": 42,
        "nthread": -1,
        "verbosity": 1,
    }
    
    print(f"Training XGBoost without zoning (LULC-proxy equivalent) for {dataset_name}...")
    model = xgb.train(
        params,
        dtrain,
        num_boost_round=500,
        evals=[(dtrain, "train"), (dval, "val")],
        early_stopping_rounds=50,
        verbose_eval=100,
    )
    
    y_pred = model.predict(dtest)
    from sklearn.metrics import r2_score, mean_squared_error
    
    r2 = r2_score(y_test_arr, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test_arr, y_pred))
    
    print(f"\n[{dataset_name} - Robustness Check Result]")
    print(f"RMSE: {rmse:.4f}")
    print(f"R²:   {r2:.4f}")
    
    return r2, rmse

def main():
    datasets = [
        {"name": "Chennai (v2, 43 scenes)", "dir": "/mnt/f/helios-archive-recent/staging/dense_chennai_v2"},
        {"name": "Bangalore (26 scenes)", "dir": "/mnt/f/helios-archive-bangalore/staging/dense"}
    ]
    
    results = {}
    for ds in datasets:
        r2, rmse = run_robustness(ds["dir"], ds["name"])
        results[ds["name"]] = {"R2": r2, "RMSE": rmse}
        
    print("\n\n=== FINAL SUMMARY ===")
    for k, v in results.items():
        print(f"{k}: R²={v['R2']:.4f}, RMSE={v['RMSE']:.4f}")

if __name__ == "__main__":
    main()
