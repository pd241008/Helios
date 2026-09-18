import geopandas as gpd
from shapely.geometry import box

print("Loading zones...")
zones = gpd.read_file('/mnt/f/helios-archive-baseline/staging/raw/zoning.geojson')
zones = zones.to_crs(epsg=3857)

print("Creating bbox...")
bbox = box(79.9469, 12.8000, 80.3450, 13.2300)
bbox_gdf = gpd.GeoDataFrame({'geometry': [bbox]}, crs='EPSG:4326').to_crs(epsg=3857)

bbox_area = bbox_gdf.geometry.area.sum()
print("Clipping...")
zones_clipped = gpd.clip(zones, bbox_gdf)
zones_area = zones_clipped.geometry.area.sum()

print('BBox Area:', bbox_area)
print('Zones Area:', zones_area)
print('Coverage:', (zones_area / bbox_area) * 100, '%')
