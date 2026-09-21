"""
Phase 1 / Task 6 -- Elevation (NASADEM), aggregated to the 300m master grid.

NASADEM is a single, static, global mosaic (no date range / cloud filter
to worry about) served on Planetary Computer as ~1deg x 1deg tiles. NCR's
bbox spans roughly lon 75.5-78.5, lat 26.7-30.0, so this typically pulls
in on the order of a dozen tiles, each treated like a "scene" in the same
sense as process_landsat_lst.py -- searched, read with retries, cached,
and aggregated to the 300m grid with the same block-reshape trick (30m
native resolution -> 10x10 blocks).

Because tiles tile the globe edge-to-edge with no time dimension, a 300m
cell is covered by exactly one tile in the overwhelming majority of cases
(only cells sitting exactly on a 1-degree seam could see two); the final
merge takes the mean of whatever tile(s) produced a value for that cell,
which reduces to "that tile's value" in the normal case.

Run:
    python process_elevation.py
"""

from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd
import planetary_computer
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import from_bounds, Window

from phase1_common import (
    BOUNDARY_FILE, GRID_CRS, GRID_SIZE_M, GridIndex, PHASE1_DIR,
    Checkpoint, aggregate_aligned_array, build_grid_index, cache_path_for,
    gdal_retry_env, load_master_grid, open_pc_catalog, retry, snapped_bounds,
)

COLLECTION = "nasadem"
NATIVE_RESOLUTION_M = 30
BLOCK = GRID_SIZE_M // NATIVE_RESOLUTION_M   # 10

# Generous physical bounds (Dead Sea shoreline to well above Everest) --
# only rejects genuinely corrupt DEM values, not real terrain.
ELEV_SANITY_MIN_M = -430.0
ELEV_SANITY_MAX_M = 9000.0

# NASADEM's elevation asset key on Planetary Computer. Checked defensively
# at runtime (see find_elevation_asset) in case of naming differences.
CANDIDATE_ASSET_KEYS = ["elevation", "data", "dem"]

OUT_DIR = PHASE1_DIR / "elevation"
CACHE_DIR = OUT_DIR / "cache"
CHECKPOINT_FILE = OUT_DIR / "checkpoint.json"
OUTPUT_CSV = OUT_DIR / "elevation_300m.csv"


def find_elevation_asset(item):
    for key in CANDIDATE_ASSET_KEYS:
        if key in item.assets:
            return key, item.assets[key]
    # Fall back to any asset whose roles include "data".
    for key, asset in item.assets.items():
        if "data" in (asset.roles or []):
            return key, asset
    return None, None


def search_tiles(catalog, bbox_wgs84):
    print(f"\nSearching {COLLECTION} for NCR bbox {bbox_wgs84}...")

    def _search():
        s = catalog.search(collections=[COLLECTION], bbox=bbox_wgs84)
        return list(s.items())

    items = retry(_search, label="STAC search")
    print(f"Found {len(items)} NASADEM tile(s) covering NCR.")
    for it in items:
        print(f"  - {it.id}")
    return items


def process_tile(item, boundary_bounds_4326, grid_index):
    item = planetary_computer.sign(item)  # fresh token -- see LST script's comment
    tile_id = item.id
    print(f"\n--- Tile {tile_id} ---")

    asset_key, asset = find_elevation_asset(item)
    print(f"  Elevation asset found: {asset is not None} (key={asset_key!r})")
    if asset is None:
        raise RuntimeError(
            f"No elevation-like asset found on item {tile_id}. "
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

    dem, transform, src_crs, nodata, src_dims = retry(_read, label=f"read elevation for {tile_id}")

    print(f"  Source CRS: {src_crs}")
    print(f"  Source dimensions (full tile): {src_dims[0]} x {src_dims[1]}")
    print(f"  Windowed read shape: {dem.shape}")

    dem = dem.astype(np.float64)
    valid_nodata = dem != (nodata if nodata is not None else -32768)
    in_range = (dem >= ELEV_SANITY_MIN_M) & (dem <= ELEV_SANITY_MAX_M)
    final_valid = valid_nodata & in_range

    total_px = dem.size
    n_valid_px = int(final_valid.sum())
    print(f"  Pixel breakdown (of {total_px:,} windowed pixels):")
    print(f"    nodata/void:             {int((~valid_nodata).sum()):,}")
    print(f"    out-of-sanity-range:     {int((valid_nodata & ~in_range).sum()):,}")
    print(f"    VALID elevation pixels:  {n_valid_px:,} ({100.0 * n_valid_px / total_px:.2f}%)")

    if n_valid_px == 0:
        raise RuntimeError("0 valid pixels after masking.")

    dem_masked = np.where(final_valid, dem, np.nan)

    left, bottom, right, top = rasterio.transform.array_bounds(*dem_masked.shape, transform)
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
    dst = np.full((dst_height, dst_width), np.nan, dtype=np.float64)
    reproject(
        source=dem_masked, destination=dst,
        src_transform=transform, src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=GRID_CRS,
        src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear,
    )

    stats = aggregate_aligned_array(dst, block=BLOCK)
    n_br, n_bc = stats["mean"].shape
    rows_idx, cols_idx = np.meshgrid(np.arange(n_br), np.arange(n_bc), indexing="ij")
    block_cx = dminx + (cols_idx * BLOCK + BLOCK / 2) * NATIVE_RESOLUTION_M
    block_cy = dmaxy - (rows_idx * BLOCK + BLOCK / 2) * NATIVE_RESOLUTION_M
    gcol, grow = GridIndex.col_row_from_xy(block_cx.ravel(), block_cy.ravel())
    cell_ids = grid_index.lookup(gcol, grow)

    flat_mean = stats["mean"].ravel()
    flat_min = stats["min"].ravel()
    flat_max = stats["max"].ravel()
    keep = pd.notna(cell_ids) & ~np.isnan(flat_mean)
    n_valid_cells = int(keep.sum())
    print(f"  300m cells covered by this tile: {n_valid_cells:,}")

    return {
        "cell_id": cell_ids[keep], "mean": flat_mean[keep],
        "min": flat_min[keep], "max": flat_max[keep],
        "n_valid_cells": n_valid_cells, "tile_id": tile_id,
    }


def main():
    print("=" * 70)
    print("NASADEM ELEVATION PROCESSING (Phase 1, Task 6)")
    print("=" * 70)

    grid = load_master_grid()
    grid_index = build_grid_index(grid)
    print(f"Master grid loaded: {grid_index.n_cells:,} cells.")

    import geopandas as gpd
    boundary = gpd.read_file(BOUNDARY_FILE)
    boundary_bounds_4326 = tuple(boundary.to_crs("EPSG:4326").total_bounds)

    catalog = open_pc_catalog()
    tiles = search_tiles(catalog, boundary_bounds_4326)
    if not tiles:
        raise RuntimeError("STAC search returned zero NASADEM tiles for the NCR bbox.")

    checkpoint = Checkpoint(CHECKPOINT_FILE)
    n_cells = grid_index.n_cells
    cell_ids_all = grid["cell_id"].to_numpy()
    cell_pos = pd.Series(np.arange(n_cells), index=cell_ids_all)

    mean_matrix, min_matrix, max_matrix = [], [], []
    failures = []

    for item in tiles:
        tile_id = item.id
        cache_file = cache_path_for(CACHE_DIR, tile_id)

        if checkpoint.is_done(tile_id) and cache_file.exists():
            print(f"\n--- Tile {tile_id}: cached, skipping download ---")
            npz = np.load(cache_file, allow_pickle=True)
            idx = cell_pos.reindex(npz["cell_id"]).to_numpy()
            ok = ~pd.isna(idx)
            for matrix, key in ((mean_matrix, "mean"), (min_matrix, "min"), (max_matrix, "max")):
                arr = np.full(n_cells, np.nan, dtype=np.float32)
                arr[idx[ok].astype(int)] = npz[key][ok]
                matrix.append(arr)
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
        for matrix, key in ((mean_matrix, "mean"), (min_matrix, "min"), (max_matrix, "max")):
            arr = np.full(n_cells, np.nan, dtype=np.float32)
            arr[idx[ok].astype(int)] = result[key][ok]
            matrix.append(arr)

        meta = {"tile_id": tile_id, "n_valid_cells": result["n_valid_cells"]}
        np.savez_compressed(cache_file, cell_id=result["cell_id"], mean=result["mean"],
                             min=result["min"], max=result["max"], meta=np.array(meta, dtype=object))
        checkpoint.mark_done(tile_id, meta)

    n_successful = len(mean_matrix)
    print(f"\nSuccessful tiles: {n_successful} / {len(tiles)}")

    if n_successful == 0:
        print("\n" + "=" * 70)
        print("ALL TILES FAILED -- DIAGNOSTIC SUMMARY")
        print("=" * 70)
        for tid, err in failures:
            print(f"\n{tid}:\n  {err}")
        raise RuntimeError(f"No elevation data available: all {len(tiles)} tile(s) failed.")

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        elev_mean = np.nanmean(np.stack(mean_matrix, axis=0), axis=0)
        elev_min = np.nanmin(np.stack(min_matrix, axis=0), axis=0)
        elev_max = np.nanmax(np.stack(max_matrix, axis=0), axis=0)
    has_value = ~np.isnan(elev_mean)

    out = pd.DataFrame({
        "cell_id": cell_ids_all,
        "elevation_mean_m": elev_mean,
        "elevation_min_m": elev_min,
        "elevation_max_m": elev_max,
    })
    out = out[has_value].copy()
    out["elevation_source"] = "NASADEM HGT v001, Microsoft Planetary Computer"
    out["elevation_native_resolution_m"] = NATIVE_RESOLUTION_M
    out["elevation_spatial_resolution_m"] = GRID_SIZE_M
    out["data_status"] = "REAL_SATELLITE_DATA"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_CSV, index=False)

    coverage_pct = 100.0 * len(out) / n_cells
    print("\n" + "=" * 70)
    print("ELEVATION SUMMARY")
    print("=" * 70)
    print(f"Tiles used: {n_successful} (of {len(tiles)} attempted, {len(failures)} failed)")
    print(f"Cells with a value: {len(out):,} / {n_cells:,} ({coverage_pct:.2f}% coverage)")
    if len(out):
        print(f"elevation_mean_m   min={out['elevation_mean_m'].min():.1f}  "
              f"max={out['elevation_mean_m'].max():.1f}  mean={out['elevation_mean_m'].mean():.1f}")
    print(f"Output: {OUTPUT_CSV}")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
