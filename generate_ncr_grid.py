import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import box
from pathlib import Path
import time


# ============================================================
# NCR 300m x 300m GRID GENERATOR
# ============================================================

BOUNDARY_FILE = Path("backend/data/ncr_boundary.geojson")
OUTPUT_DIR = Path("backend/data")

GRID_SIZE = 300  # metres

# Metric CRS used for metre-based grid generation
GRID_CRS = "EPSG:6933"


# ============================================================
# START
# ============================================================

start_time = time.time()

print("=" * 70)
print("NCR OPTIMIZED 300m x 300m GRID GENERATOR")
print("=" * 70)


# ============================================================
# CHECK INPUT
# ============================================================

if not BOUNDARY_FILE.exists():
    raise FileNotFoundError(
        f"\nBoundary file not found:\n{BOUNDARY_FILE}"
    )


# ============================================================
# LOAD NCR BOUNDARY
# ============================================================

print("\nLoading NCR boundary...")

ncr = gpd.read_file(BOUNDARY_FILE)

if ncr.empty:
    raise RuntimeError("NCR boundary is empty.")

print(
    f"Loaded {len(ncr)} boundary feature(s)."
)


# ============================================================
# FIX GEOMETRY
# ============================================================

print("\nChecking boundary geometry...")

ncr["geometry"] = ncr.geometry.make_valid()

boundary = ncr.geometry.union_all()

print(
    f"Boundary geometry: {boundary.geom_type}"
)


# ============================================================
# PROJECT TO METRIC CRS
# ============================================================

print(
    f"\nProjecting boundary to {GRID_CRS}..."
)

boundary_gdf = gpd.GeoDataFrame(
    {"name": ["NCR"]},
    geometry=[boundary],
    crs="EPSG:4326"
)

boundary_metric = boundary_gdf.to_crs(GRID_CRS)

boundary_geom = boundary_metric.geometry.iloc[0]


# ============================================================
# AREA
# ============================================================

area_km2 = (
    boundary_metric.geometry.area.iloc[0]
    / 1_000_000
)

print(
    f"NCR area in projected CRS: "
    f"{area_km2:,.2f} km²"
)


# ============================================================
# BOUNDING BOX
# ============================================================

minx, miny, maxx, maxy = boundary_geom.bounds

print("\nProjected bounds:")

print(f"minx = {minx:,.0f}")
print(f"miny = {miny:,.0f}")
print(f"maxx = {maxx:,.0f}")
print(f"maxy = {maxy:,.0f}")


# ============================================================
# CREATE 300m GRID COORDINATES
# ============================================================

print(
    f"\nCreating {GRID_SIZE}m x {GRID_SIZE}m "
    "candidate grid..."
)

xs = np.arange(
    np.floor(minx / GRID_SIZE) * GRID_SIZE,
    np.ceil(maxx / GRID_SIZE) * GRID_SIZE,
    GRID_SIZE
)

ys = np.arange(
    np.floor(miny / GRID_SIZE) * GRID_SIZE,
    np.ceil(maxy / GRID_SIZE) * GRID_SIZE,
    GRID_SIZE
)

print(
    f"Grid columns: {len(xs)}"
)

print(
    f"Grid rows: {len(ys)}"
)

candidate_count = (
    len(xs) * len(ys)
)

print(
    f"Candidate cells: "
    f"{candidate_count:,}"
)


# ============================================================
# GENERATE POLYGONS
# ============================================================

print("\nGenerating grid cells...")

cells = [
    box(
        x,
        y,
        x + GRID_SIZE,
        y + GRID_SIZE
    )
    for x in xs
    for y in ys
]

cells_gdf = gpd.GeoDataFrame(
    {
        "geometry": cells
    },
    crs=GRID_CRS
)

print(
    f"Generated {len(cells_gdf):,} candidate cells."
)


# ============================================================
# FAST SPATIAL INDEX FILTER
# ============================================================

print(
    "\nFinding cells intersecting NCR..."
)

candidate_idx = (
    cells_gdf.sindex.query(
        boundary_geom,
        predicate="intersects"
    )
)

cells_gdf = (
    cells_gdf
    .iloc[candidate_idx]
    .copy()
)

cells_gdf.reset_index(
    drop=True,
    inplace=True
)

print(
    f"Candidate NCR cells: "
    f"{len(cells_gdf):,}"
)


# ============================================================
# EXACT INTERSECTION CHECK
# ============================================================

print(
    "\nPerforming exact boundary check..."
)

intersects = (
    cells_gdf.geometry.intersects(
        boundary_geom
    )
)

cells_gdf = (
    cells_gdf
    .loc[intersects]
    .copy()
)

cells_gdf.reset_index(
    drop=True,
    inplace=True
)

print(
    f"Cells intersecting NCR: "
    f"{len(cells_gdf):,}"
)


# ============================================================
# SEPARATE INTERIOR AND EDGE CELLS
# ============================================================

print(
    "\nIdentifying boundary-edge cells..."
)

inside = (
    cells_gdf.geometry.within(
        boundary_geom
    )
)

interior_cells = (
    cells_gdf
    .loc[inside]
    .copy()
)

edge_cells = (
    cells_gdf
    .loc[~inside]
    .copy()
)

print(
    f"Interior cells: "
    f"{len(interior_cells):,}"
)

print(
    f"Edge cells requiring clipping: "
    f"{len(edge_cells):,}"
)


# ============================================================
# CLIP ONLY EDGE CELLS
# ============================================================

if not edge_cells.empty:

    print(
        "\nClipping boundary-edge cells..."
    )

    edge_cells["geometry"] = (
        edge_cells.geometry
        .intersection(boundary_geom)
    )

    edge_cells = edge_cells[
        ~edge_cells.geometry.is_empty
    ].copy()


# ============================================================
# COMBINE CELLS
# ============================================================

print(
    "\nCombining grid cells..."
)

grid = pd.concat(
    [
        interior_cells,
        edge_cells
    ],
    ignore_index=True
)

grid = gpd.GeoDataFrame(
    grid,
    geometry="geometry",
    crs=GRID_CRS
)

grid.reset_index(
    drop=True,
    inplace=True
)

print(
    f"Combined cells: "
    f"{len(grid):,}"
)


# ============================================================
# FINAL GEOMETRY CLEANUP
# ============================================================

print(
    "\nCleaning final geometries..."
)

grid["geometry"] = (
    grid.geometry.make_valid()
)

grid = grid[
    ~grid.geometry.is_empty
].copy()

grid.reset_index(
    drop=True,
    inplace=True
)


# ============================================================
# CELL IDs
# ============================================================

print(
    "\nCreating cell IDs..."
)

grid.insert(
    0,
    "cell_id",
    [
        f"NCR300_{i:07d}"
        for i in range(
            1,
            len(grid) + 1
        )
    ]
)


# ============================================================
# METADATA
# ============================================================

grid["resolution_m"] = GRID_SIZE

grid["grid_type"] = "NCR_300M"

grid["data_status"] = "SPATIAL_GRID"


# ============================================================
# CENTROIDS
# ============================================================

print(
    "\nCalculating centroids..."
)

centroids = (
    grid.geometry.centroid
)

grid["centroid_x"] = (
    centroids.x
)

grid["centroid_y"] = (
    centroids.y
)


# ============================================================
# CELL AREA
# ============================================================

grid["area_m2"] = (
    grid.geometry.area
)


# ============================================================
# OUTPUT DIRECTORY
# ============================================================

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# SAVE GEOPACKAGE
# ============================================================

gpkg_file = (
    OUTPUT_DIR /
    "ncr_300m_grid.gpkg"
)

print(
    "\nSaving GeoPackage..."
)

print(
    f"File: {gpkg_file}"
)

grid.to_file(
    gpkg_file,
    layer="ncr_300m_grid",
    driver="GPKG"
)


# ============================================================
# CONVERT TO WGS84
# ============================================================

print(
    "\nConverting grid to WGS84..."
)

grid_wgs84 = (
    grid.to_crs("EPSG:4326")
)


# ============================================================
# SAVE GEOJSON
# ============================================================

geojson_file = (
    OUTPUT_DIR /
    "ncr_300m_grid.geojson"
)

print(
    "\nSaving GeoJSON..."
)

print(
    f"File: {geojson_file}"
)

grid_wgs84.to_file(
    geojson_file,
    driver="GeoJSON"
)


# ============================================================
# FILE SIZES
# ============================================================

gpkg_size_mb = (
    gpkg_file.stat().st_size
    / (1024 * 1024)
)

geojson_size_mb = (
    geojson_file.stat().st_size
    / (1024 * 1024)
)


# ============================================================
# FINAL SUMMARY
# ============================================================

elapsed_minutes = (
    time.time() - start_time
) / 60


print("\n" + "=" * 70)
print("SUCCESS!")
print("=" * 70)

print(
    f"\nFinal grid cells: "
    f"{len(grid):,}"
)

print(
    f"NCR area: "
    f"{area_km2:,.2f} km²"
)

print(
    f"Grid resolution: "
    f"{GRID_SIZE}m x {GRID_SIZE}m"
)

print(
    f"\nGeoPackage size: "
    f"{gpkg_size_mb:.2f} MB"
)

print(
    f"GeoJSON size: "
    f"{geojson_size_mb:.2f} MB"
)

print(
    f"\nTime taken: "
    f"{elapsed_minutes:.2f} minutes"
)

print(
    "\nGeoPackage:"
)

print(gpkg_file)

print(
    "\nGeoJSON:"
)

print(geojson_file)

print(
    "\nNext step:"
)

print(
    "Add satellite-derived spatial features "
    "(LST, NDVI, land cover, built-up, etc.)."
)

print("=" * 70)