import polars as pl
import os
import glob
import sys

def main():
    print("Scanning raw data for ST bands...")
    raw_lf = pl.scan_parquet('/mnt/f/helios-archive/staging/raw/landsat/*.parquet')
    
    st_lf = raw_lf.filter(pl.col("band").is_in(["ST_B10", "ST_B6"]))
    st_lf = st_lf.select(["lat", "lon", "timestamp", pl.col("value").alias("lst_k")])
    st_lf = st_lf.with_columns(pl.col("timestamp").cast(pl.Datetime("ms")).dt.replace_time_zone(None))
    st_df = st_lf.collect()
    print(f"Collected ST bands: {st_df.shape}")

    print("Using pre-computed global mean for ST bands...")
    global_mean_lst = 308.008254
    print(f"Global mean LST is {global_mean_lst}")
    
    out_dir = '/mnt/f/helios-archive/staging/dense'
    os.makedirs(out_dir, exist_ok=True)
    
    sa_files = sorted(glob.glob('/mnt/f/helios-archive/staging/intermediate/spatial_aligned/*.parquet'))
    
    for idx, sa_file in enumerate(sa_files):
        out_path = os.path.join(out_dir, f'part-{idx:05d}-fixed.parquet')
        if os.path.exists(out_path):
            print(f"Part {idx+1} already exists, skipping...")
            continue
            
        print(f"Processing part {idx+1}/{len(sa_files)}: {os.path.basename(sa_file)}")
        sa_lf = pl.scan_parquet(sa_file)
        sa_lf = sa_lf.with_columns(pl.col("timestamp").cast(pl.Datetime("ms")).dt.replace_time_zone(None))
        
        # We join with the collected dataframe (lazy() converts it back so the rest of the graph works)
        joined_lf = sa_lf.join(st_df.lazy(), on=["lat", "lon", "timestamp"], how="inner")
        
        joined_lf = joined_lf.with_columns(
            ndvi = (pl.col("B5") - pl.col("B4")) / (pl.col("B5") + pl.col("B4"))
        )
        
        joined_lf = joined_lf.filter(
            pl.col("lulc_class").is_not_null() & 
            pl.col("lst_k").is_not_null() & 
            pl.col("lst_k").is_not_nan()
        )
        
        joined_lf = joined_lf.with_columns([
            pl.col("timestamp").dt.year().alias("year"),
            pl.col("timestamp").dt.month().alias("month")
        ])
        
        target_encoding_lf = joined_lf.group_by(["timestamp", "lulc_class"]).agg([
            pl.len().alias("lulc_count"),
            pl.mean("lst_k").alias("lulc_mean")
        ])
        
        target_encoding_lf = target_encoding_lf.with_columns(
            lulc_encoded = (pl.col("lulc_mean") * pl.col("lulc_count") + pl.lit(global_mean_lst) * 10.0) / (pl.col("lulc_count") + 10.0)
        ).drop("lulc_mean")
        
        final_lf = joined_lf.join(target_encoding_lf, on=["timestamp", "lulc_class"], how="left")
        
        final_cols = ["lat", "lon", "timestamp", "year", "month", "lulc_class", "B2", "B3", "B4", "B5", "B6", "ndvi", "lulc_encoded", "lulc_count", "lst_k"]
        
        # We can just use collect() since it's just one part file (~500k rows)
        final_df = final_lf.select(final_cols).collect()
        print(f"  Shape: {final_df.shape}")
        
        if final_df.shape[0] > 0:
            out_path = os.path.join(out_dir, f'part-{idx:05d}-fixed.parquet')
            final_df.write_parquet(out_path)
            
    print("Done!")

if __name__ == '__main__':
    main()
