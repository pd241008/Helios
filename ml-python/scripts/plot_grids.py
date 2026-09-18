import polars as pl
import matplotlib.pyplot as plt
import numpy as np
import glob
import os

def generate_grid(data_dir, output_path, var_name, cmap, vmin, vmax, title_prefix, years):
    # 3x4 grid holds up to 12 years
    fig, axes = plt.subplots(3, 4, figsize=(20, 15))
    axes = axes.flatten()
    sc = None
    
    for i, year in enumerate(years):
        print(f"[{title_prefix}] Loading data for year {year}...")
        ax = axes[i]
        
        path_pattern = f"{data_dir}/year={year}/**/*.parquet"
        files = glob.glob(path_pattern, recursive=True)
        
        if not files:
            print(f"No files found for year {year}")
            ax.set_title(f"{title_prefix} - {year} (No Data)")
            ax.axis('off')
            continue
            
        try:
            # handle 'lst_k' for Bangalore, 'lst' for Chennai
            actual_var_name = var_name
            
            # Check actual columns if var_name is 'lst'
            if var_name == "lst":
                # Quick peek at schema
                schema = pl.scan_parquet(files[0]).collect_schema().names()
                if "lst_k" in schema:
                    actual_var_name = "lst_k"
                elif "lst" in schema:
                    actual_var_name = "lst"
                else:
                    raise ValueError(f"Could not find lst column in {schema}")
                    
            df = (
                pl.scan_parquet(path_pattern)
                .select(['lat', 'lon', actual_var_name])
                .filter(pl.col(actual_var_name).is_not_null())
                .collect()
            )
            
            if len(df) == 0:
                ax.set_title(f"{title_prefix} - {year} (No Data)")
                ax.axis('off')
                continue
                
            if len(df) > 100000:
                df = df.sample(100000, seed=42)
                
            lats = df["lat"].to_numpy()
            lons = df["lon"].to_numpy()
            var_data = df[actual_var_name].to_numpy()
            
            # Convert Kelvin to Celsius if LST
            if var_name == "lst":
                # If mean is > 200, it's definitely Kelvin
                if np.mean(var_data) > 200:
                    var_data = var_data - 273.15
            
            sc = ax.scatter(lons, lats, c=var_data, cmap=cmap, s=0.5, alpha=0.8, vmin=vmin, vmax=vmax)
            ax.set_title(f"{title_prefix} - {year}")
            ax.axis('off')
        except Exception as e:
            print(f"Error processing year {year}: {e}")
            ax.set_title(f"{title_prefix} - {year} (Error)")
            ax.axis('off')
            
    # Turn off unused axes
    for i in range(len(years), len(axes)):
        axes[i].axis('off')
            
    plt.tight_layout()
    if sc is not None:
        cbar_ax = fig.add_axes([1.02, 0.15, 0.03, 0.7])
        cbar_label = 'NDVI' if var_name == 'ndvi' else 'LST (°C)'
        fig.colorbar(sc, cax=cbar_ax, label=cbar_label)
    
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    print(f"Saved to {output_path}")

def main():
    out_dir = "/root/.gemini/antigravity-ide/brain/6233855f-3699-4553-8c74-8a51b5a06126"
    
    tasks = [
        # Bangalore
        {
            "data_dir": "/mnt/f/helios-archive-bangalore/staging/dense",
            "output_path": f"{out_dir}/bangalore_ndvi_grid.png",
            "var_name": "ndvi", "cmap": "RdYlGn", "vmin": -0.2, "vmax": 0.8,
            "title_prefix": "NDVI", "years": list(range(2016, 2026))
        },
        {
            "data_dir": "/mnt/f/helios-archive-bangalore/staging/dense",
            "output_path": f"{out_dir}/bangalore_lst_grid.png",
            "var_name": "lst", "cmap": "inferno", "vmin": 25, "vmax": 55,
            "title_prefix": "Land Surface Temp (°C)", "years": list(range(2016, 2026))
        }
    ]
    
    for task in tasks:
        generate_grid(**task)

if __name__ == "__main__":
    main()
