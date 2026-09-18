import polars as pl
import glob
import os

files = glob.glob('/mnt/f/helios-archive-baseline/staging/raw/landsat/*.parquet')
files = sorted(files)

if not files:
    print("No files found.")
    exit(1)

print(f"Total scenes: {len(files)}")
print("-" * 50)
print(f"{'Scene Name':<40} | {'AOI Cloud %'}")
print("-" * 50)

clouds = []

for file in files:
    scene_name = os.path.basename(file).replace('.parquet', '')
    
    # Lazy load to avoid loading full file into memory at once if it's too big
    df = pl.scan_parquet(file)
    
    # Filter for QA_PIXEL
    qa_df = df.filter(pl.col('band') == 'QA_PIXEL').collect()
    
    if len(qa_df) > 0:
        # Bits 3 and 4 (0-indexed) are cloud/cloud shadow in Landsat Collection 2
        # 0x08 = Bit 3 (cloud shadow), 0x10 = Bit 4 (cloud)
        cloud_mask = (qa_df['value'].cast(pl.Int64) & (8 | 16)) > 0
        cloud_pct = cloud_mask.sum() / len(qa_df) * 100
        clouds.append(cloud_pct)
        print(f"{scene_name:<40} | {cloud_pct:>7.2f}%")
    else:
        print(f"{scene_name:<40} | No QA_PIXEL")

print("-" * 50)
if clouds:
    print(f"Average AOI Cloud Cover: {sum(clouds)/len(clouds):.2f}%")
    print(f"Max AOI Cloud Cover: {max(clouds):.2f}%")
    print(f"Min AOI Cloud Cover: {min(clouds):.2f}%")
