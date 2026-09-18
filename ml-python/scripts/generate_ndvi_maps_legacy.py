import polars as pl
import matplotlib.pyplot as plt
import glob
import numpy as np

print("Loading Bangalore dataset for NDVI mapping...")
df = pl.scan_parquet('/mnt/f/helios-archive-bangalore/staging/dense/*/*/*.parquet').select(['lon', 'lat', 'year', 'ndvi']).collect().drop_nulls()

years = sorted(df['year'].unique().to_list())

for year in years:
    print(f"Generating NDVI map for {year}...")
    sub = df.filter(pl.col("year") == year)
    
    lon = sub['lon'].to_numpy()
    lat = sub['lat'].to_numpy()
    ndvi = sub['ndvi'].to_numpy()
    
    plt.figure(figsize=(10, 8))
    # A spatial map using hexbin! 
    # C=ndvi with reduce_C_function=np.mean averages the NDVI per spatial bin
    hb = plt.hexbin(lon, lat, C=ndvi, gridsize=150, cmap='RdYlGn', vmin=-0.1, vmax=0.6, reduce_C_function=np.mean)
    
    plt.colorbar(hb, label='NDVI')
    plt.xlabel('Longitude')
    plt.ylabel('Latitude')
    plt.title(f'Bangalore: NDVI Spatial Map ({year})')
    
    # Save it
    out_path = f'/root/.gemini/antigravity-ide/brain/6233855f-3699-4553-8c74-8a51b5a06126/bangalore_ndvi_map_{year}.png'
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()

print("Done! Generated all NDVI maps.")
