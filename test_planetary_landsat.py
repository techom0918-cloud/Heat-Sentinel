from pathlib import Path

import geopandas as gpd
import rasterio
import planetary_computer
from pystac_client import Client


BOUNDARY_FILE = Path(
    "backend/data/ncr_boundary.geojson"
)

STAC_URL = (
    "https://planetarycomputer.microsoft.com/"
    "api/stac/v1"
)


# --------------------------------------------------
# NCR boundary
# --------------------------------------------------

ncr = gpd.read_file(
    BOUNDARY_FILE
).to_crs("EPSG:4326")

geometry = ncr.geometry.union_all()

print("NCR loaded")


# --------------------------------------------------
# Planetary Computer STAC
# --------------------------------------------------

catalog = Client.open(
    STAC_URL
)

print("STAC connected")


# --------------------------------------------------
# Search ONE good Landsat scene
# --------------------------------------------------

search = catalog.search(
    collections=["landsat-c2-l2"],
    intersects=geometry.__geo_interface__,
    datetime=(
        "2026-08-01T00:00:00Z/"
        "2026-08-31T23:59:59Z"
    ),
    query={
        "eo:cloud_cover": {
            "lt": 15
        }
    },
    limit=1,
)

items = list(
    search.items()
)

print(
    "Scenes found:",
    len(items)
)

if not items:
    raise RuntimeError(
        "No Landsat scene found."
    )


item = items[0]

print("\nScene:")
print(item.id)

print(
    "Date:",
    item.datetime
)

print(
    "Cloud:",
    item.properties.get(
        "eo:cloud_cover"
    )
)


# --------------------------------------------------
# Sign item for data access
# --------------------------------------------------

print("\nSigning item...")

signed_item = (
    planetary_computer.sign(
        item
    )
)

print("Item signed")


# --------------------------------------------------
# LST asset
# --------------------------------------------------

asset = signed_item.assets["lwir11"]

print("\nLST asset:")
print(asset.title)

print(
    "URL:",
    asset.href
)


# --------------------------------------------------
# Open remote COG
# --------------------------------------------------

print("\nOpening LST raster...")

with rasterio.open(
    asset.href
) as src:

    print(
        "CRS:",
        src.crs
    )

    print(
        "Resolution:",
        src.res
    )

    print(
        "Size:",
        src.width,
        "x",
        src.height
    )

    print(
        "Data type:",
        src.dtypes[0]
    )

    print(
        "NoData:",
        src.nodata
    )

    print(
        "Bounds:",
        src.bounds
    )

    # Read ONE pixel only
    sample = next(
        src.sample(
            [
                (
                    src.bounds.left + 1000,
                    src.bounds.top - 1000,
                )
            ]
        )
    )

    print(
        "Raw LST pixel:",
        sample[0]
    )


print(
    "\n================================"
)

print(
    "PLANETARY COMPUTER LST TEST OK"
)

print(
    "================================"
)