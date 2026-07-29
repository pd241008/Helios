import duckdb
import os

def main():
    print("Initializing DuckDB...")
    # Use a temp directory on the F drive so we don't run out of space on the root drive during spilling
    os.makedirs('/mnt/f/helios-archive/staging/duckdb_temp', exist_ok=True)
    con = duckdb.connect(database=':memory:', config={'temp_directory': '/mnt/f/helios-archive/staging/duckdb_temp'})
    
    con.execute("PRAGMA memory_limit='8GB';")
    con.execute("PRAGMA threads=4;")
    con.execute("SET TimeZone='UTC';")
    
    print("Creating views for spatial_aligned and ST bands...")
    con.execute("""
    CREATE OR REPLACE VIEW sa AS 
    SELECT lat, lon, timestamp::TIMESTAMP AS timestamp, lulc_class, B2, B3, B4, B5, B6
    FROM '/mnt/f/helios-archive/staging/intermediate/spatial_aligned/*.parquet';
    """)
    
    con.execute("""
    CREATE OR REPLACE VIEW st AS 
    SELECT lat, lon, timestamp::TIMESTAMP AS timestamp, value AS lst_k
    FROM '/mnt/f/helios-archive/staging/raw/landsat/*.parquet'
    WHERE band IN ('ST_B10', 'ST_B6');
    """)
    
    print("Creating joined view...")
    con.execute("""
    CREATE OR REPLACE VIEW joined AS
    SELECT 
        sa.lat, sa.lon, sa.timestamp, 
        date_part('year', sa.timestamp) AS year,
        date_part('month', sa.timestamp) AS month,
        sa.lulc_class, sa.B2, sa.B3, sa.B4, sa.B5, sa.B6,
        (sa.B5 - sa.B4) / (sa.B5 + sa.B4) AS ndvi,
        st.lst_k
    FROM sa
    INNER JOIN st ON sa.lat = st.lat AND sa.lon = st.lon AND sa.timestamp = st.timestamp
    WHERE sa.lulc_class IS NOT NULL AND st.lst_k IS NOT NULL;
    """)
    
    print("Creating target encoding view...")
    con.execute("""
    CREATE OR REPLACE VIEW target_encoding AS
    SELECT 
        timestamp,
        lulc_class,
        count(*) AS lulc_count,
        avg(lst_k) AS lulc_mean
    FROM joined
    GROUP BY timestamp, lulc_class;
    """)
    
    print("Creating final view...")
    con.execute("""
    CREATE OR REPLACE VIEW final_output AS
    SELECT 
        j.lat, j.lon, j.timestamp, j.year, j.month, j.lulc_class, 
        j.B2, j.B3, j.B4, j.B5, j.B6, j.ndvi, 
        (t.lulc_mean * t.lulc_count + 308.008254 * 10.0) / (t.lulc_count + 10.0) AS lulc_encoded,
        t.lulc_count,
        j.lst_k
    FROM joined j
    LEFT JOIN target_encoding t ON j.timestamp = t.timestamp AND j.lulc_class = t.lulc_class;
    """)
    
    print("Writing output to parquet using DuckDB...")
    os.makedirs('/mnt/f/helios-archive/staging/dense', exist_ok=True)
    
    # We write directly to the dense directory
    con.execute("""
    COPY (SELECT * FROM final_output) 
    TO '/mnt/f/helios-archive/staging/dense/' 
    (FORMAT PARQUET, PARTITION_BY (year, month), OVERWRITE_OR_IGNORE 1);
    """)
    
    print("Done!")

if __name__ == '__main__':
    main()
