import polars as pl
from pathlib import Path

in_dir = Path("../staging/helios_output")
out_dir = Path("../staging/helios_output_scratch")

print(f"Reading from {in_dir}...")
lf = pl.scan_parquet(in_dir / "**/*.parquet", hive_partitioning=True)

# Format: LC08_L2SP_142051_YYYYMMDD_02_T1
df = lf.with_columns(
    pl.col("tile_id").str.split("_").list.get(3).str.to_date("%Y%m%d").dt.ordinal_day().alias("doy").cast(pl.Int32)
).collect()

print(f"Loaded {len(df)} rows. Sample doy:")
print(df.select(["tile_id", "doy"]).head(5))

out_dir.mkdir(exist_ok=True, parents=True)
out_file = out_dir / "scratch_data.parquet"
df.write_parquet(out_file)
print(f"Wrote scratch data to {out_file}")
