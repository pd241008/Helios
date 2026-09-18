import json
import glob

files = glob.glob('/mnt/f/helios-archive-bangalore/staging/raw/landsat/*/scene_metadata.json')
clouds = []
for f in files:
    with open(f, 'r') as fp:
        data = json.load(fp)
        clouds.append(data['cloud_cover'])

if clouds:
    print(f"Total scenes: {len(clouds)}")
    print(f"Average AOI Cloud Cover: {sum(clouds)/len(clouds):.4f}%")
    print(f"Max AOI Cloud Cover: {max(clouds):.4f}%")
    print(f"Min AOI Cloud Cover: {min(clouds):.4f}%")
else:
    print("No files found.")
