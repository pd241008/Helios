import polars as pl
import matplotlib.pyplot as plt
import glob
import numpy as np

print("Loading data for NDVI vs PV plot...")
# Load a single parquet file to be fast, or sample from the dataset
files = glob.glob('/mnt/f/helios-archive-bangalore/staging/dense/year=2016/split=train/*.parquet')
df = pl.read_parquet(files[0], columns=['ndvi', 'pv']).drop_nulls()

ndvi = df['ndvi'].to_numpy()
pv = df['pv'].to_numpy()

plt.figure(figsize=(8, 6))
hb = plt.hexbin(ndvi, pv, gridsize=50, cmap='viridis', mincnt=1, bins='log')
plt.colorbar(hb, label='log10(count)')
plt.xlabel('NDVI')
plt.ylabel('Fractional Vegetation (Pv)')
plt.title('Bangalore: NDVI vs Pv Collinearity')
plt.grid(alpha=0.3)

out_path = '/root/.gemini/antigravity-ide/brain/6233855f-3699-4553-8c74-8a51b5a06126/bangalore_ndvi_pv_collinearity.png'
plt.savefig(out_path, dpi=150, bbox_inches='tight')
print(f"Saved plot to {out_path}")
