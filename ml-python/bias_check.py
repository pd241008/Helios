import json
import numpy as np
import polars as pl
import xgboost as xgb
from helios_ml.data import load
from helios_ml.split import temporal_split

def main():
    data_dir = "/mnt/f/helios-archive-recent/staging/dense_chennai_v2"
    model_path = "./reports_chennai_v2/lst_model.json"
    
    print("Loading data...")
    full_df, feature_df = load(data_dir, full_resolution=True, sample_strategy="none", sample_rate=0.1)
    
    print("Applying temporal split...")
    target = full_df["lst"]
    X_train_df, X_test_df, y_train, y_test = temporal_split(feature_df, target)
    
    print(f"\nTrain LST: mean={y_train.mean():.4f}, std={y_train.std():.4f}")
    print(f"Test LST:  mean={y_test.mean():.4f}, std={y_test.std():.4f}")
    
    # Need to apply the exact same feature engineering as train.py
    def _add_seasonal_feature(df, full_df):
        phase = (2.0 * np.pi * df["doy"].cast(pl.Float32) / 366.0)
        return df.with_columns([
            phase.sin().alias("doy_sin"),
            phase.cos().alias("doy_cos"),
        ])
    
    X_test_df = _add_seasonal_feature(X_test_df, full_df)
    
    NON_FEATURE_COLS = ("tile_id", "year", "month", "timestamp", "doy", "split", "has_thermal_split", "lulc_class", "lulc_count")
    LEAKAGE_COLS = ("ST_B10",)
    NULL_COLS = ("bt10", "bt11", "bt10_minus_bt11")
    DROP_COLS = NON_FEATURE_COLS + LEAKAGE_COLS + NULL_COLS
    
    drop_test = [c for c in DROP_COLS if c in X_test_df.columns]
    X_test_df = X_test_df.drop(drop_test)
    
    X_test = X_test_df.to_numpy().astype(np.float32)
    y_test_arr = y_test.to_numpy().astype(np.float32)
    
    print("Loading model and predicting...")
    model = xgb.Booster()
    model.load_model(model_path)
    
    dtest = xgb.DMatrix(X_test)
    y_pred = model.predict(dtest)
    
    print(f"\nTest Actuals:     mean={y_test_arr.mean():.4f}")
    print(f"Test Predictions: mean={y_pred.mean():.4f}")
    print(f"Bias (Pred - Act): {y_pred.mean() - y_test_arr.mean():.4f}")

if __name__ == "__main__":
    main()
