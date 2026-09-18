import polars as pl
import matplotlib.pyplot as plt
import numpy as np
import glob

def debug_2022():
    out_dir = "/root/.gemini/antigravity-ide/brain/6233855f-3699-4553-8c74-8a51b5a06126"
    
    # Check Bangalore 2022
    path_pattern = "/mnt/f/helios-archive-recent/staging/dense/year=2022/**/*.parquet"
    df = (
        pl.scan_parquet(path_pattern)
        .select(['lat', 'lon', 'ndvi'])
        .filter(pl.col('ndvi').is_not_null())
        .collect()
    )
    print(f"Bangalore 2022 valid NDVI rows: {len(df)}")
    
    if len(df) > 0:
        if len(df) > 100000:
            df = df.sample(100000, seed=42)
        plt.figure()
        plt.scatter(df["lon"].to_numpy(), df["lat"].to_numpy(), c=df["ndvi"].to_numpy(), cmap='RdYlGn', s=0.5)
        plt.colorbar()
        plt.savefig(f"{out_dir}/debug_bangalore_2022.png")
        plt.close()
        
    # Check Chennai 2022
    path_pattern = "/mnt/f/helios-archive-recent/staging/dense_chennai_v2/year=2022/**/*.parquet"
    df = (
        pl.scan_parquet(path_pattern)
        .select(['lat', 'lon', 'ndvi'])
        .filter(pl.col('ndvi').is_not_null())
        .collect()
    )
    print(f"Chennai 2022 valid NDVI rows: {len(df)}")
    
if __name__ == "__main__":
    debug_2022()
