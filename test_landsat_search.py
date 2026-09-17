from pathlib import Path
import geopandas as gpd
from pystac_client import Client

BOUNDARY_FILE = Path(
    "backend/data/ncr_boundary.geojson"
)

STAC_URL = "https://landsatlook.usgs.gov/stac-server"

START_DATE = "2026-05-01"
END_DATE = "2026-09-15"

MAX_CLOUD = 35


# --------------------------------------------------
# Load NCR
# --------------------------------------------------

print("Loading NCR boundary...")

ncr = gpd.read_file(BOUNDARY_FILE)

ncr = ncr.to_crs("EPSG:4326")

geometry = ncr.geometry.union_all()

print("NCR loaded.")
print("Features:", len(ncr))


# --------------------------------------------------
# Connect to USGS STAC
# --------------------------------------------------

print("\nConnecting to USGS Landsat STAC...")

catalog = Client.open(STAC_URL)

print("Connected:", catalog.id)


# --------------------------------------------------
# Search Landsat Surface Temperature
# --------------------------------------------------

print("\nSearching Landsat ST scenes...")

search = catalog.search(
    collections=["landsat-c2l2-st"],
    intersects=geometry.__geo_interface__,
    datetime=f"{START_DATE}T00:00:00Z/{END_DATE}T23:59:59Z",
    query={
        "eo:cloud_cover": {
            "lt": MAX_CLOUD
        }
    },
)

items = list(search.items())

print("\n======================================")
print("RESULT")
print("======================================")

print("Scenes found:", len(items))


# --------------------------------------------------
# Show scenes
# --------------------------------------------------

for i, item in enumerate(items[:20], start=1):

    print("\nScene", i)
    print("ID:", item.id)
    print("Date:", item.datetime)
    print(
        "Cloud:",
        item.properties.get(
            "eo:cloud_cover",
            "N/A"
        )
    )

    print("Assets:")

    for name, asset in item.assets.items():

        print(
            "  ",
            name,
            "->",
            asset.title
        )


print("\n======================================")
print("TEST COMPLETE")
print("======================================")