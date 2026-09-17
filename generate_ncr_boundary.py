import requests
import geopandas as gpd
from shapely.geometry import shape
from pathlib import Path


# ============================================================
# NCR BOUNDARY GENERATOR
# ============================================================

URL = (
    "https://services2.arcgis.com/fQDJ6zNJPJ0yhFjv/"
    "ArcGIS/rest/services/India_Admin/FeatureServer/2/query"
)


# ============================================================
# OFFICIAL NCR DISTRICTS
#
# 14 Haryana
# 8 Uttar Pradesh
# 2 Rajasthan
# + Entire NCT Delhi
# ============================================================

NCR_DISTRICTS = [
    # ---------------- HARYANA ----------------
    "Faridabad",
    "Gurugram",
    "Gurgaon",
    "Nuh",
    "Mewat",
    "Rohtak",
    "Sonipat",
    "Sonepat",
    "Rewari",
    "Jhajjar",
    "Panipat",
    "Palwal",
    "Bhiwani",
    "Charkhi Dadri",
    "Mahendragarh",
    "Jind",
    "Karnal",

    # ---------------- UTTAR PRADESH ----------------
    "Meerut",
    "Ghaziabad",
    "Gautam Buddha Nagar",
    "Gautam Budh Nagar",
    "Gautambuddha Nagar",
    "Bulandshahr",
    "Baghpat",
    "Hapur",
    "Shamli",
    "Muzaffarnagar",

    # ---------------- RAJASTHAN ----------------
    "Alwar",
    "Bharatpur",
]


print("=" * 65)
print("NCR BOUNDARY GENERATOR")
print("=" * 65)


# ============================================================
# DOWNLOAD
# ============================================================

print("\nDownloading district boundaries...")

params = {
    "where": "1=1",
    "outFields": "*",
    "returnGeometry": "true",
    "outSR": "4326",
    "f": "geojson",
}


response = requests.get(
    URL,
    params=params,
    timeout=180
)

response.raise_for_status()

data = response.json()

features = data.get("features", [])

print(
    f"\nDownloaded {len(features)} district features."
)


if not features:
    raise RuntimeError(
        "No district geometries returned."
    )


# ============================================================
# FIND FIELDS
# ============================================================

print("\nAvailable properties:")
print(
    features[0]["properties"].keys()
)


district_field = "District"
state_field = "State"


if district_field not in features[0]["properties"]:

    raise RuntimeError(
        f"District field '{district_field}' not found."
    )


if state_field not in features[0]["properties"]:

    raise RuntimeError(
        f"State field '{state_field}' not found."
    )


print(
    f"\nUsing district field: {district_field}"
)

print(
    f"Using state field: {state_field}"
)


# ============================================================
# NORMALIZE NAMES
# ============================================================

def normalize_name(name):

    if name is None:
        return ""

    return (
        str(name)
        .strip()
        .lower()
        .replace("-", " ")
        .replace("_", " ")
    )


ncr_lookup = {
    normalize_name(name)
    for name in NCR_DISTRICTS
}


# ============================================================
# SELECT NCR DISTRICTS + ENTIRE DELHI
# ============================================================

selected = []


for feature in features:

    props = feature["properties"]

    district = props.get(district_field)

    state = props.get(state_field)

    district_normalized = normalize_name(
        district
    )

    state_normalized = normalize_name(
        state
    )


    # --------------------------------------------------------
    # Delhi
    #
    # NCR contains entire NCT Delhi.
    # Therefore include every Delhi district polygon.
    # --------------------------------------------------------

    if state_normalized in [
        "delhi",
        "nct of delhi",
        "nct delhi",
        "national capital territory of delhi",
    ]:

        selected.append(feature)

        continue


    # --------------------------------------------------------
    # Haryana / UP / Rajasthan NCR districts
    # --------------------------------------------------------

    if district_normalized in ncr_lookup:

        selected.append(feature)


print(
    f"\nSelected {len(selected)} GIS features."
)


# ============================================================
# SHOW SELECTED FEATURES
# ============================================================

print("\nSelected NCR GIS features:")

for feature in selected:

    props = feature["properties"]

    district = props.get(district_field)

    state = props.get(state_field)

    print(
        f"  ✓ {state} -> {district}"
    )


# ============================================================
# CONVERT TO GEODATAFRAME
# ============================================================

records = []


for feature in selected:

    geometry = feature.get("geometry")

    if geometry is None:
        continue


    records.append(
        {
            "district": feature["properties"].get(
                district_field
            ),

            "state": feature["properties"].get(
                state_field
            ),

            "geometry": shape(geometry),
        }
    )


if not records:

    raise RuntimeError(
        "No valid NCR geometries found."
    )


gdf = gpd.GeoDataFrame(
    records,
    crs="EPSG:4326"
)


# ============================================================
# FIX INVALID GEOMETRIES
# ============================================================

print("\nChecking geometries...")

gdf["geometry"] = (
    gdf.geometry.buffer(0)
)


gdf = gdf[
    ~gdf.geometry.is_empty
].copy()


# ============================================================
# DISSOLVE
# ============================================================

print(
    "\nDissolving NCR geometry..."
)


try:

    ncr_geometry = gdf.union_all()

except AttributeError:

    ncr_geometry = gdf.unary_union


# ============================================================
# FINAL NCR GEODATAFRAME
# ============================================================

ncr = gpd.GeoDataFrame(
    [
        {
            "name": "National Capital Region",

            "source": (
                "NCRPB current NCR extent; "
                "district polygons from GIS dataset"
            ),

            "geometry": ncr_geometry,
        }
    ],

    crs="EPSG:4326"
)


# ============================================================
# OUTPUT
# ============================================================

output_dir = Path(
    "backend/data"
)

output_dir.mkdir(
    parents=True,
    exist_ok=True
)


output_file = (
    output_dir /
    "ncr_boundary.geojson"
)


print(
    "\nSaving NCR boundary..."
)


ncr.to_file(
    output_file,
    driver="GeoJSON"
)


# ============================================================
# AREA
# ============================================================

area_km2 = (
    ncr
    .to_crs("EPSG:6933")
    .geometry
    .area
    .iloc[0]
    / 1_000_000
)


print(
    f"\nApproximate NCR area: "
    f"{area_km2:,.2f} km²"
)


# ============================================================
# FINAL
# ============================================================

print("\n" + "=" * 65)
print("SUCCESS!")
print("=" * 65)

print(
    "\nSaved:"
)

print(
    output_file
)

print(
    "\nNext step:"
)

print(
    "Generate the ~300m × 300m NCR grid."
)

print("=" * 65)