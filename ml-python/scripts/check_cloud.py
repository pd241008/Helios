import polars as pl
import glob

files = glob.glob('/mnt/f/helios-archive-bangalore/staging/raw/landsat/*.parquet')
if not files:
    print("No files found.")
    exit(1)

file = files[0]
df = pl.read_parquet(file)
print("Distinct bands:", df['band'].unique().to_list())

qa_df = df.filter(pl.col('band') == 'QA_PIXEL')
if len(qa_df) > 0:
    print("QA_PIXEL rows:", len(qa_df))
    # Bits 3 and 4 (0-indexed) are cloud/cloud shadow in Landsat Collection 2
    # 0x08 = Bit 3 (cloud shadow), 0x10 = Bit 4 (cloud)
    cloud_mask = (qa_df['value'].cast(pl.Int64) & (8 | 16)) > 0
    cloud_pct = cloud_mask.sum() / len(qa_df) * 100
    print(f"Cloud percentage for {file}: {cloud_pct:.2f}%")
else:
    print("QA_PIXEL band not found in parquet.")
