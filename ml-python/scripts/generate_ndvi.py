import polars as pl
import matplotlib.pyplot as plt
import numpy as np
import glob
import os

def generate_ndvi_grid():
    years = [2016, 2017, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
    
    fig, axes = plt.subplots(3, 3, figsize=(15, 15))
    axes = axes.flatten()
    sc = None
    
    for i, year in enumerate(years):
        print(f"Loading data for year {year}...")
        ax = axes[i]
        
        path_pattern = f"/mnt/f/helios-archive/staging/dense/year={year}/**/*.parquet"
        files = glob.glob(path_pattern, recursive=True)
        
        if not files:
            print(f"No files found for year {year}")
            ax.set_title(f"NDVI - {year} (No Data)")
            ax.axis('off')
            continue
            
        try:
            # We use scan_parquet to efficiently filter and sample
            df = (
                pl.scan_parquet(path_pattern)
                .select(['lat', 'lon', 'ndvi'])
                .filter(pl.col('ndvi').is_not_null())
                .collect()
            )
            
            if len(df) > 100000:
                df = df.sample(100000, seed=42)
                
            lats = df["lat"].to_numpy()
            lons = df["lon"].to_numpy()
            ndvi = df["ndvi"].to_numpy()
            
            sc = ax.scatter(lons, lats, c=ndvi, cmap='RdYlGn', s=0.5, alpha=0.8, vmin=-0.2, vmax=0.8)
            ax.set_title(f"NDVI - {year}")
            ax.axis('off')
        except Exception as e:
            print(f"Error processing year {year}: {e}")
            ax.set_title(f"NDVI - {year} (Error)")
            ax.axis('off')
            
    plt.tight_layout()
    # Add a colorbar at the right
    if sc is not None:
        cbar_ax = fig.add_axes([1.02, 0.15, 0.03, 0.7])
        fig.colorbar(sc, cax=cbar_ax, label='NDVI')
    
    # Save the plot
    output_path = "/root/.gemini/antigravity-ide/brain/58fe0a97-952b-465f-a40c-45bc61a832bc/ndvi_grid.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Saved to {output_path}")

if __name__ == "__main__":
    generate_ndvi_grid()
