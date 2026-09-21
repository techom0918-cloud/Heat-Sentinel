"""
Phase 1 / Task 5 -- Land cover, aggregated to the 300m master grid.

*** DATA-SOURCE FLAG -- READ BEFORE RUNNING (also printed at runtime) ***
The task spec asks for "Dynamic World V1". Dynamic World is NOT indexed
as a Microsoft Planetary Computer STAC collection (verified: it is not in
the PC catalog; the only way to reach it is Google Earth Engine, which
this pipeline does not otherwise depend on and which needs its own
`earthengine authenticate` credential setup). Rather than silently
substitute a different product or block Phase 1 on a second cloud
platform, this script defaults to Planetary Computer's `io-lulc-9-class`
collection (Esri / Impact Observatory, 10m, Sentinel-2-derived, also a
real, non-synthetic, 9-class annual product) and remaps its classes onto
the requested Dynamic-World-style schema. This is a genuine substitution,
not a bug -- see CLASS_MAP below for exactly what is and isn't a clean
1:1 mapping. If true Dynamic World V1 is required, that needs a
Google-Earth-Engine version of this script instead; ask for it if so.

CLASS MAPPING (Esri/IO raw code -> requested class)
    1  Water              -> 0 water
    2  Trees               -> 1 trees
    4  Flooded Vegetation  -> 3 flooded_vegetation
    5  Crops               -> 4 crops
    7  Built Area          -> 6 built
    8  Bare Ground         -> 7 bare
    9  Snow/Ice            -> 8 snow_and_ice
    10 Clouds              -> masked out (residual cloud in the annual composite)
    11 Rangeland           -> 5 shrub_and_scrub (APPROXIMATION: Esri's
                               "Rangeland" merges grass and shrub/scrub;
                               Dynamic World's class 2 "grass" therefore
                               has no source here and will read ~0 cells)

Run:
    python process_land_cover.py
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import planetary_computer
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds, Window

from phase1_common import (
    BOUNDARY_FILE, GRID_CRS, GRID_SIZE_M, GridIndex, PHASE1_DIR,
    Checkpoint, build_grid_index, cache_path_for, gdal_retry_env,
    load_master_grid, majority_aligned_array, open_pc_catalog, retry,
    snapped_bounds,
)
from rasterio.enums import Resampling
from rasterio.warp import reproject

COLLECTION = "io-lulc-9-class"
NATIVE_RESOLUTION_M = 10
BLOCK = GRID_SIZE_M // NATIVE_RESOLUTION_M   # 30

CANDIDATE_ASSET_KEYS = ["data", "lulc", "classification"]

# Esri raw code -> (requested DW-style code, requested name). Code 10
# (Clouds) is intentionally absent -> masked.
CLASS_MAP = {
    1: (0, "water"),
    2: (1, "trees"),
    4: (3, "flooded_vegetation"),
    5: (4, "crops"),
    7: (6, "built"),
    8: (7, "bare"),
    9: (8, "snow_and_ice"),
    11: (5, "shrub_and_scrub"),
}
CLASS_NAMES = {
    0: "water", 1: "trees", 2: "grass", 3: "flooded_vegetation", 4: "crops",
    5: "shrub_and_scrub", 6: "built", 7: "bare", 8: "snow_and_ice",
}

OUT_DIR = PHASE1_DIR / "land_cover"
CACHE_DIR = OUT_DIR / "cache"
CHECKPOINT_FILE = OUT_DIR / "checkpoint.json"
OUTPUT_CSV = OUT_DIR / "land_cover_300m.csv"


def find_data_asset(item):
    for key in CANDIDATE_ASSET_KEYS:
        if key in item.assets:
            return key, item.assets[key]
    for key, asset in item.assets.items():
        if "data" in (asset.roles or []):
            return key, asset
    return None, None


def _item_year(item) -> int:
    """Annual io-lulc-9-class items commonly have `datetime: null` (they're
    year-long composites, so STAC's common-metadata extension expects
    start_datetime/end_datetime instead of a single instant) -- that null
    is exactly what made max()/min() crash comparing NoneType > NoneType.
    Falls back to start_datetime, then to the year embedded in the item id
    (observed format: "<region>-<year>", e.g. "44R-2023")."""
    if item.datetime is not None:
        return item.datetime.year
    start = item.properties.get("start_datetime")
    if start:
        return int(start[:4])
    try:
        return int(item.id.split("-")[-1])
    except (ValueError, IndexError):
        return -1


def search_latest_tiles(catalog, bbox_wgs84):
    print(f"\nSearching {COLLECTION} covering NCR bbox {bbox_wgs84}...")

    def _search():
        s = catalog.search(collections=[COLLECTION], bbox=bbox_wgs84)
        return list(s.items())

    items = retry(_search, label="STAC search")
    print(f"Found {len(items)} candidate tile-year item(s).")

    # Group by spatial tile (region), keep only the most recent year per tile.
    by_region: dict[str, list] = {}
    for it in items:
        region = it.properties.get("region", it.id.split("-")[0])
        by_region.setdefault(region, []).append(it)

    latest = [max(v, key=_item_year) for v in by_region.values()]
    print(f"Selected {len(latest)} most-recent-year tile(s), one per region:")
    for it in latest:
        print(f"  - {it.id}  (year={_item_year(it)})")
    return latest


def process_tile(item, boundary_bounds_4326, grid_index):
    item = planetary_computer.sign(item)  # fresh token -- see LST script's comment
    tile_id = item.id
    print(f"\n--- Tile {tile_id} ---")

    asset_key, asset = find_data_asset(item)
    print(f"  Land-cover asset found: {asset is not None} (key={asset_key!r})")
    if asset is None:
        raise RuntimeError(
            f"No classification asset found on item {tile_id}. "
            f"Available assets: {list(item.assets.keys())}"
        )

    env_kwargs = gdal_retry_env()

    def _read():
        with rasterio.Env(**env_kwargs):
            with rasterio.open(asset.href) as src:
                left, bottom, right, top = transform_bounds(
                    "EPSG:4326", src.crs, *boundary_bounds_4326
                )
                win = from_bounds(left, bottom, right, top, transform=src.transform)
                win = win.round_offsets().round_lengths()
                win = win.intersection(Window(0, 0, src.width, src.height))
                if win.width <= 0 or win.height <= 0:
                    raise RuntimeError("NCR boundary does not overlap this tile.")
                data = src.read(1, window=win)
                transform = src.window_transform(win)
                return data, transform, src.crs, src.nodata, (src.width, src.height)

    raw, transform, src_crs, nodata, src_dims = retry(_read, label=f"read land cover for {tile_id}")

    print(f"  Source CRS: {src_crs}")
    print(f"  Source dimensions (full tile): {src_dims[0]} x {src_dims[1]}")
    print(f"  Windowed read shape: {raw.shape}")

    # Remap Esri raw codes -> requested class codes (unmapped/nodata -> -1).
    remapped = np.full(raw.shape, -1, dtype=np.int16)
    class_pixel_counts = {}
    for esri_code, (dw_code, _name) in CLASS_MAP.items():
        mask = raw == esri_code
        class_pixel_counts[esri_code] = int(mask.sum())
        remapped[mask] = dw_code

    total_px = raw.size
    n_cloud = int((raw == 10).sum())
    n_mapped = int((remapped != -1).sum())
    print(f"  Pixel breakdown (of {total_px:,} windowed pixels):")
    for esri_code, (dw_code, name) in CLASS_MAP.items():
        print(f"    Esri {esri_code:>2} -> {name:<20} {class_pixel_counts[esri_code]:,}")
    print(f"    Esri 10 (Clouds, masked):        {n_cloud:,}")
    print(f"    VALID (mapped) pixels:            {n_mapped:,} "
          f"({100.0 * n_mapped / total_px:.2f}%)")

    if n_mapped == 0:
        raise RuntimeError("0 valid pixels after class remapping.")

    left, bottom, right, top = rasterio.transform.array_bounds(*remapped.shape, transform)
    b_minx, b_miny, b_maxx, b_maxy = transform_bounds(src_crs, GRID_CRS, left, bottom, right, top)
    dminx, dminy, dmaxx, dmaxy = snapped_bounds(b_minx, b_miny, b_maxx, b_maxy, GRID_SIZE_M)

    dst_width = int(round((dmaxx - dminx) / NATIVE_RESOLUTION_M))
    dst_height = int(round((dmaxy - dminy) / NATIVE_RESOLUTION_M))
    dst_width -= dst_width % BLOCK
    dst_height -= dst_height % BLOCK
    if dst_width <= 0 or dst_height <= 0:
        raise RuntimeError("Snapped destination raster has zero size.")

    dst_transform = rasterio.transform.from_origin(
        dminx, dmaxy, NATIVE_RESOLUTION_M, NATIVE_RESOLUTION_M
    )
    dst = np.full((dst_height, dst_width), -1, dtype=np.int16)
    reproject(
        source=remapped, destination=dst,
        src_transform=transform, src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=GRID_CRS,
        src_nodata=-1, dst_nodata=-1, resampling=Resampling.nearest,
    )

    stats = majority_aligned_array(dst, block=BLOCK, valid_classes=list(CLASS_NAMES.keys()))
    n_br, n_bc = stats["dominant_class"].shape
    rows_idx, cols_idx = np.meshgrid(np.arange(n_br), np.arange(n_bc), indexing="ij")
    block_cx = dminx + (cols_idx * BLOCK + BLOCK / 2) * NATIVE_RESOLUTION_M
    block_cy = dmaxy - (rows_idx * BLOCK + BLOCK / 2) * NATIVE_RESOLUTION_M
    gcol, grow = GridIndex.col_row_from_xy(block_cx.ravel(), block_cy.ravel())
    cell_ids = grid_index.lookup(gcol, grow)

    dom = stats["dominant_class"].ravel()
    frac = stats["fraction"].ravel()
    keep = pd.notna(cell_ids) & (dom != -1)
    n_valid_cells = int(keep.sum())
    print(f"  300m cells covered by this tile: {n_valid_cells:,}")

    return {
        "cell_id": cell_ids[keep], "class": dom[keep], "fraction": frac[keep],
        "n_valid_cells": n_valid_cells, "tile_id": tile_id,
    }


def main():
    print("=" * 70)
    print("LAND COVER PROCESSING (Phase 1, Task 5)")
    print("=" * 70)
    print(
        "NOTE: Dynamic World V1 is not a Planetary Computer STAC collection.\n"
        f"Using {COLLECTION} (Esri/Impact Observatory) with the documented\n"
        "class remapping in this file's docstring -- see it before trusting\n"
        "'grass' anywhere downstream (it is not separable from this source)."
    )

    grid = load_master_grid()
    grid_index = build_grid_index(grid)
    print(f"\nMaster grid loaded: {grid_index.n_cells:,} cells.")

    import geopandas as gpd
    boundary = gpd.read_file(BOUNDARY_FILE)
    boundary_bounds_4326 = tuple(boundary.to_crs("EPSG:4326").total_bounds)

    catalog = open_pc_catalog()
    tiles = search_latest_tiles(catalog, boundary_bounds_4326)
    if not tiles:
        raise RuntimeError(f"STAC search returned zero {COLLECTION} tiles for the NCR bbox.")

    checkpoint = Checkpoint(CHECKPOINT_FILE)
    n_cells = grid_index.n_cells
    cell_ids_all = grid["cell_id"].to_numpy()
    cell_pos = pd.Series(np.arange(n_cells), index=cell_ids_all)

    class_matrix, frac_matrix = [], []
    failures = []

    for item in tiles:
        tile_id = item.id
        cache_file = cache_path_for(CACHE_DIR, tile_id)

        if checkpoint.is_done(tile_id) and cache_file.exists():
            print(f"\n--- Tile {tile_id}: cached, skipping download ---")
            npz = np.load(cache_file, allow_pickle=True)
            idx = cell_pos.reindex(npz["cell_id"]).to_numpy()
            ok = ~pd.isna(idx)
            c_arr = np.full(n_cells, -1, dtype=np.int16)
            f_arr = np.full(n_cells, np.nan, dtype=np.float32)
            c_arr[idx[ok].astype(int)] = npz["class_"][ok]
            f_arr[idx[ok].astype(int)] = npz["fraction"][ok]
            class_matrix.append(c_arr)
            frac_matrix.append(f_arr)
            continue

        try:
            result = process_tile(item, boundary_bounds_4326, grid_index)
        except Exception as exc:  # noqa: BLE001
            print(f"\nSCENE FAILED:\n{tile_id}\n\nERROR:\n{exc}\n")
            checkpoint.mark_failed(tile_id, str(exc))
            failures.append((tile_id, str(exc)))
            print("Continuing with next tile...")
            continue

        idx = cell_pos.reindex(result["cell_id"]).to_numpy()
        ok = ~pd.isna(idx)
        c_arr = np.full(n_cells, -1, dtype=np.int16)
        f_arr = np.full(n_cells, np.nan, dtype=np.float32)
        c_arr[idx[ok].astype(int)] = result["class"][ok]
        f_arr[idx[ok].astype(int)] = result["fraction"][ok]
        class_matrix.append(c_arr)
        frac_matrix.append(f_arr)

        meta = {"tile_id": tile_id, "n_valid_cells": result["n_valid_cells"]}
        np.savez_compressed(cache_file, cell_id=result["cell_id"], class_=result["class"],
                             fraction=result["fraction"], meta=np.array(meta, dtype=object))
        # np.savez_compressed can't use the name "class" (reserved) -> stored as class_
        checkpoint.mark_done(tile_id, meta)

    n_successful = len(class_matrix)
    print(f"\nSuccessful tiles: {n_successful} / {len(tiles)}")

    if n_successful == 0:
        print("\n" + "=" * 70)
        print("ALL TILES FAILED -- DIAGNOSTIC SUMMARY")
        print("=" * 70)
        for tid, err in failures:
            print(f"\n{tid}:\n  {err}")
        raise RuntimeError(f"No land-cover data available: all {len(tiles)} tile(s) failed.")

    class_stack = np.stack(class_matrix, axis=0)
    frac_stack = np.stack(frac_matrix, axis=0)
    # If a cell got a value from >1 tile (rare, only at tile seams), take
    # the value from the tile with the highest fraction (most confident).
    best_tile = np.nanargmax(np.where(class_stack != -1, frac_stack, -1), axis=0)
    final_class = np.take_along_axis(class_stack, best_tile[None, :], axis=0)[0]
    final_frac = np.take_along_axis(frac_stack, best_tile[None, :], axis=0)[0]
    has_value = final_class != -1

    out = pd.DataFrame({
        "cell_id": cell_ids_all,
        "land_cover_class": final_class,
        "land_cover_fraction": final_frac,
    })
    out = out[has_value].copy()
    out["land_cover_name"] = out["land_cover_class"].map(CLASS_NAMES)
    out["land_cover_source"] = (
        f"{COLLECTION} (Esri/Impact Observatory), Microsoft Planetary Computer -- "
        "remapped to Dynamic-World-style classes; see script docstring for the mapping"
    )
    out["land_cover_native_resolution_m"] = NATIVE_RESOLUTION_M
    out["land_cover_spatial_resolution_m"] = GRID_SIZE_M
    out["data_status"] = "REAL_SATELLITE_DATA"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_CSV, index=False)

    coverage_pct = 100.0 * len(out) / n_cells
    print("\n" + "=" * 70)
    print("LAND COVER SUMMARY")
    print("=" * 70)
    print(f"Tiles used: {n_successful} (of {len(tiles)} attempted, {len(failures)} failed)")
    print(f"Cells with a class: {len(out):,} / {n_cells:,} ({coverage_pct:.2f}% coverage)")
    if len(out):
        print("Class distribution:")
        print(out["land_cover_name"].value_counts().to_string())
    print(f"Output: {OUTPUT_CSV}")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
