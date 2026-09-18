import polars as pl
import glob

files = glob.glob('/mnt/f/helios-archive-bangalore/staging/dense/year=2016/split=train/*.parquet')
df = pl.read_parquet(files[0])
print(df.select(['lst', 'ndvi', 'bt10_minus_bt11']).null_count())
