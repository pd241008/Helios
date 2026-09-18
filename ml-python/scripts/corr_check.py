import polars as pl
import scipy.stats as stats
import glob

print("Loading data for collinearity check...")
files = glob.glob('/mnt/f/helios-archive-bangalore/staging/dense/year=2016/split=train/*.parquet')
if not files:
    print("No files found!")
    exit(1)

df = pl.read_parquet(files[0], columns=['ndvi', 'pv']).drop_nulls()
print(f"Loaded {len(df)} rows.")

ndvi = df['ndvi'].to_numpy()
pv = df['pv'].to_numpy()

pearson_corr, _ = stats.pearsonr(ndvi, pv)
spearman_corr, _ = stats.spearmanr(ndvi, pv)

print(f"Pearson correlation (NDVI vs Pv): {pearson_corr:.4f}")
print(f"Spearman correlation (NDVI vs Pv): {spearman_corr:.4f}")
