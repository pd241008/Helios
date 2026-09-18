import polars as pl
import matplotlib.pyplot as plt
import numpy as np
import glob
import os

def generate_lst_grid():
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
            ax.set_title(f"LST - {year} (No Data)")
            ax.axis('off')
            continue
            
        try:
            df = (
                pl.scan_parquet(path_pattern)
                .select(['lat', 'lon', 'lst_k'])
                .filter(pl.col('lst_k').is_not_null())
                .collect()
            )
            
            if len(df) > 100000:
                df = df.sample(100000, seed=42)
                
            lats = df["lat"].to_numpy()
            lons = df["lon"].to_numpy()
            # Convert Kelvin to Celsius for better readability
            lst_c = df["lst_k"].to_numpy() - 273.15
            
            # Using 'inferno' or 'hot' colormap for temperature
            sc = ax.scatter(lons, lats, c=lst_c, cmap='inferno', s=0.5, alpha=0.8, vmin=25, vmax=55)
            ax.set_title(f"Land Surface Temp (°C) - {year}")
            ax.axis('off')
        except Exception as e:
            print(f"Error processing year {year}: {e}")
            ax.set_title(f"LST - {year} (Error)")
            ax.axis('off')
            
    plt.tight_layout()
    # Add a colorbar at the right
    if sc is not None:
        cbar_ax = fig.add_axes([1.02, 0.15, 0.03, 0.7])
        fig.colorbar(sc, cax=cbar_ax, label='LST (°C)')
    
    # Save the plot
    output_path = "/root/.gemini/antigravity-ide/brain/58fe0a97-952b-465f-a40c-45bc61a832bc/lst_grid.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Saved to {output_path}")

if __name__ == "__main__":
    generate_lst_grid()
