from pathlib import Path
import requests
import geopandas as gpd
from pystac_client import Client

BOUNDARY_FILE = Path("backend/data/ncr_boundary.geojson")

STAC_URL = "https://landsatlook.usgs.gov/stac-server"

ncr = gpd.read_file(
    BOUNDARY_FILE
).to_crs("EPSG:4326")

geometry = ncr.geometry.union_all()

catalog = Client.open(STAC_URL)

search = catalog.search(
    collections=["landsat-c2l2-st"],
    intersects=geometry.__geo_interface__,
    datetime="2026-08-01T00:00:00Z/2026-08-31T23:59:59Z",
    query={
        "eo:cloud_cover": {
            "lt": 15
        }
    },
    limit=1,
)

items = list(search.items())

if not items:
    raise RuntimeError("No scene found.")

item = items[0]

print("Scene:")
print(item.id)

asset = item.assets["lwir11"]

print("\nAsset:")
print(asset.title)

print("\nURL:")
print(asset.href)

print("\nSending HTTP request...")

response = requests.get(
    asset.href,
    stream=True,
    timeout=60,
)

print("\nHTTP status:", response.status_code)

print(
    "Content-Type:",
    response.headers.get("Content-Type")
)

print(
    "Content-Length:",
    response.headers.get("Content-Length")
)

print(
    "Final URL:",
    response.url
)

print("\nFirst bytes:")

chunk = next(
    response.iter_content(
        chunk_size=32
    )
)

print(chunk[:32])

response.close()

print("\nTEST COMPLETE")