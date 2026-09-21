"""
Phase 1 / Task 4 -- Sentinel-2-derived NDVI, aggregated to the 300m master grid.

Same architecture as process_landsat_lst.py (see that file's docstring for
the grid-alignment trick): reproject each scene's masked NDVI to EPSG:6933
at native (10m) resolution with the destination origin snapped to a 300m
multiple, then reshape into 30x30 blocks (300/10) and reduce with
vectorized NumPy. Per-cell stats across scenes come from a
(n_scenes, n_cells) matrix, same as LST.

Run:
    python process_sentinel_ndvi.py

Resumable via backend/data/phase1/ndvi/checkpoint.json and cache/.
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

# ============================================================
# CONFIG
# ============================================================

COLLECTION = "sentinel-2-l2a"
RED_ASSET = "B04"
NIR_ASSET = "B08"
SCL_ASSET = "SCL"           # Scene Classification Layer, 20m native
NATIVE_RESOLUTION_M = 10
DATE_START = "2026-05-01"
DATE_END = "2026-09-15"
MAX_CLOUD_COVER_PCT = 20.0
BLOCK = GRID_SIZE_M // NATIVE_RESOLUTION_M   # 30

# SCL classes considered valid ground for NDVI: vegetation, not-vegetated,
# water, unclassified. Excluded: no-data, saturated/defective, dark area,
# cloud shadow, cloud (medium/high prob), thin cirrus, snow.
SCL_VALID_CLASSES = {4, 5, 6, 7}

OUT_DIR = PHASE1_DIR / "ndvi"
CACHE_DIR = OUT_DIR / "cache"
CHECKPOINT_FILE = OUT_DIR / "checkpoint.json"
OUTPUT_CSV = OUT_DIR / "ndvi_300m.csv"


def search_scenes(catalog, bbox_wgs84):
    print(f"\nSearching {COLLECTION} for {DATE_START}..{DATE_END}, "
          f"cloud_cover < {MAX_CLOUD_COVER_PCT}%...")

    def _search():
        s = catalog.search(
            collections=[COLLECTION],
            bbox=bbox_wgs84,
            datetime=f"{DATE_START}/{DATE_END}",
            query={"eo:cloud_cover": {"lt": MAX_CLOUD_COVER_PCT}},
        )
        return list(s.items())

    items = retry(_search, label="STAC search")
    print(f"Found {len(items)} candidate scene(s).")
    if not items:
        return []

    # Select spatially: one lowest-cloud scene per distinct MGRS tile that
    # intersects NCR, not one per time bucket. NCR spans many 100km
    # Sentinel-2 tiles, so time-bucketing alone left ~92% of the grid
    # uncovered even with 7/7 scenes "succeeding" -- this is the actual fix.
    def tile_key(it):
        return it.properties.get("s2:mgrs_tile", it.id)

    by_tile: dict[str, list] = {}
    for it in items:
        by_tile.setdefault(tile_key(it), []).append(it)

    print(f"Distinct MGRS tiles intersecting NCR: {len(by_tile)}")

    selected = [min(v, key=lambda it: it.properties.get("eo:cloud_cover", 100))
                for v in by_tile.values()]
    selected.sort(key=lambda it: it.datetime)

    print(f"Selected {len(selected)} scene(s), one lowest-cloud scene per tile "
          f"(not a fixed count -- driven by how many tiles NCR spans):")
    for it in selected:
        print(f"  - {it.id}  tile={tile_key(it)}  {it.datetime.date()}  "
              f"cloud={it.properties.get('eo:cloud_cover', 'NA')}%")
    return selected


def _read_band(href, boundary_bounds_4326, env_kwargs, resample_to=None):
    with rasterio.Env(**env_kwargs):
        with rasterio.open(href) as src:
            left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *boundary_bounds_4326)
            win = from_bounds(left, bottom, right, top, transform=src.transform)
            win = win.round_offsets().round_lengths()
            win = win.intersection(Window(0, 0, src.width, src.height))
            if win.width <= 0 or win.height <= 0:
                raise RuntimeError("NCR boundary does not overlap this asset's extent.")
            if resample_to is None:
                data = src.read(1, window=win)
            else:
                out_h, out_w = resample_to
                data = src.read(
                    1, window=win, out_shape=(out_h, out_w), resampling=Resampling.nearest
                )
            transform = src.window_transform(win)
            return data, transform, src.crs, src.nodata


def process_scene(item, boundary_bounds_4326, grid_index):
    # Re-sign right before use -- see process_landsat_lst.py's comment on
    # this; NDVI's 403s in the first run were exactly this (all clustered
    # on scenes processed later in a long run).
    item = planetary_computer.sign(item)

    scene_id = item.id
    date = item.datetime.date()
    cloud = item.properties.get("eo:cloud_cover", "NA")
    print(f"\n--- Scene {scene_id} ({date}, cloud={cloud}%) ---")

    red_asset = item.assets.get(RED_ASSET)
    nir_asset = item.assets.get(NIR_ASSET)
    scl_asset = item.assets.get(SCL_ASSET)
    print(f"  {RED_ASSET} found: {red_asset is not None}  "
          f"{NIR_ASSET} found: {nir_asset is not None}  "
          f"{SCL_ASSET} found: {scl_asset is not None}")
    if not all([red_asset, nir_asset, scl_asset]):
        raise RuntimeError(f"Missing required asset(s) on item {scene_id}.")

    env_kwargs = gdal_retry_env()

    red, transform, src_crs, red_nodata = retry(
        lambda: _read_band(red_asset.href, boundary_bounds_4326, env_kwargs),
        label=f"read {RED_ASSET} for {scene_id}",
    )
    nir, _, _, nir_nodata = retry(
        lambda: _read_band(nir_asset.href, boundary_bounds_4326, env_kwargs),
        label=f"read {NIR_ASSET} for {scene_id}",
    )
    # SCL ships at 20m native; resample it onto the 10m Red/NIR grid.
    scl, _, _, _ = retry(
        lambda: _read_band(scl_asset.href, boundary_bounds_4326, env_kwargs,
                            resample_to=red.shape),
        label=f"read {SCL_ASSET} for {scene_id}",
    )

    print(f"  Source CRS: {src_crs}")
    print(f"  Windowed read shape: {red.shape}")

    if not (red.shape == nir.shape == scl.shape):
        raise RuntimeError(
            f"Band shape mismatch: red={red.shape} nir={nir.shape} scl={scl.shape}"
        )

    red = red.astype(np.float64)
    nir = nir.astype(np.float64)
    valid_data = (red != (red_nodata or 0)) & (nir != (nir_nodata or 0))

    denom = nir + red
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(denom != 0, (nir - red) / denom, np.nan)

    scl_valid = np.isin(scl, list(SCL_VALID_CLASSES))
    in_range = (ndvi >= -1.0) & (ndvi <= 1.0)
    final_valid = valid_data & scl_valid & in_range & ~np.isnan(ndvi)

    total_px = ndvi.size
    print(f"  Pixel breakdown (of {total_px:,} windowed pixels):")
    print(f"    nodata (red/nir):        {int((~valid_data).sum()):,}")
    print(f"    SCL cloud/shadow/other:  {int((~scl_valid).sum()):,}")
    print(f"    out-of-range NDVI:       {int((valid_data & scl_valid & ~in_range).sum()):,}")
    n_valid_px = int(final_valid.sum())
    print(f"    VALID NDVI pixels:       {n_valid_px:,} "
          f"({100.0 * n_valid_px / total_px:.2f}%)")

    if n_valid_px == 0:
        raise RuntimeError(
            "0 valid pixels after masking -- see breakdown above."
        )

    ndvi_masked = np.where(final_valid, ndvi, np.nan)

    left, bottom, right, top = rasterio.transform.array_bounds(*ndvi_masked.shape, transform)
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
        source=ndvi_masked, destination=dst,
        src_transform=transform, src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=GRID_CRS,
        src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.nearest,
    )

    stats = aggregate_aligned_array(dst, block=BLOCK)
    n_br, n_bc = stats["mean"].shape
    rows_idx, cols_idx = np.meshgrid(np.arange(n_br), np.arange(n_bc), indexing="ij")
    block_cx = dminx + (cols_idx * BLOCK + BLOCK / 2) * NATIVE_RESOLUTION_M
    block_cy = dmaxy - (rows_idx * BLOCK + BLOCK / 2) * NATIVE_RESOLUTION_M
    gcol, grow = GridIndex.col_row_from_xy(block_cx.ravel(), block_cy.ravel())
    cell_ids = grid_index.lookup(gcol, grow)

    flat_mean = stats["mean"].ravel()
    keep = pd.notna(cell_ids) & ~np.isnan(flat_mean)
    n_valid_cells = int(keep.sum())
    print(f"  300m cells covered by this scene: {n_valid_cells:,}")

    return {
        "cell_id": cell_ids[keep], "mean": flat_mean[keep],
        "n_valid_cells": n_valid_cells, "scene_id": scene_id,
        "date": str(date), "cloud_cover": cloud,
    }


def main():
    print("=" * 70)
    print("SENTINEL-2 NDVI PROCESSING (Phase 1, Task 4)")
    print("=" * 70)

    grid = load_master_grid()
    grid_index = build_grid_index(grid)
    print(f"Master grid loaded: {grid_index.n_cells:,} cells.")

    import geopandas as gpd
    boundary = gpd.read_file(BOUNDARY_FILE)
    boundary_bounds_4326 = tuple(boundary.to_crs("EPSG:4326").total_bounds)

    catalog = open_pc_catalog()
    scenes = search_scenes(catalog, boundary_bounds_4326)
    if not scenes:
        raise RuntimeError(
            "STAC search returned zero Sentinel-2 scenes for the given "
            "date range / cloud-cover threshold."
        )

    checkpoint = Checkpoint(CHECKPOINT_FILE)
    n_cells = grid_index.n_cells
    cell_ids_all = grid["cell_id"].to_numpy()
    cell_pos = pd.Series(np.arange(n_cells), index=cell_ids_all)

    scene_values = []
    failures = []

    for item in scenes:
        scene_id = item.id
        cache_file = cache_path_for(CACHE_DIR, scene_id)

        if checkpoint.is_done(scene_id) and cache_file.exists():
            print(f"\n--- Scene {scene_id}: cached, skipping download ---")
            npz = np.load(cache_file, allow_pickle=True)
            arr = np.full(n_cells, np.nan, dtype=np.float32)
            idx = cell_pos.reindex(npz["cell_id"]).to_numpy()
            ok = ~pd.isna(idx)
            arr[idx[ok].astype(int)] = npz["mean"][ok]
            scene_values.append(arr)
            continue

        try:
            result = process_scene(item, boundary_bounds_4326, grid_index)
        except Exception as exc:  # noqa: BLE001
            print(f"\nSCENE FAILED:\n{scene_id}\n\nERROR:\n{exc}\n")
            checkpoint.mark_failed(scene_id, str(exc))
            failures.append((scene_id, str(exc)))
            print("Continuing with next scene...")
            continue

        arr = np.full(n_cells, np.nan, dtype=np.float32)
        idx = cell_pos.reindex(result["cell_id"]).to_numpy()
        ok = ~pd.isna(idx)
        arr[idx[ok].astype(int)] = result["mean"][ok]
        scene_values.append(arr)

        meta = {"scene_id": scene_id, "date": result["date"],
                "cloud_cover": result["cloud_cover"], "n_valid_cells": result["n_valid_cells"]}
        np.savez_compressed(cache_file, cell_id=result["cell_id"], mean=result["mean"],
                             meta=np.array(meta, dtype=object))
        checkpoint.mark_done(scene_id, meta)

    n_successful = len(scene_values)
    print(f"\nSuccessful scenes: {n_successful} / {len(scenes)}")

    if n_successful == 0:
        print("\n" + "=" * 70)
        print("ALL SCENES FAILED -- DIAGNOSTIC SUMMARY")
        print("=" * 70)
        for sid, err in failures:
            print(f"\n{sid}:\n  {err}")
        raise RuntimeError(f"No NDVI observations available: all {len(scenes)} scene(s) failed.")

    matrix = np.stack(scene_values, axis=0)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        ndvi_mean = np.nanmean(matrix, axis=0)
        ndvi_median = np.nanmedian(matrix, axis=0)
        ndvi_min = np.nanmin(matrix, axis=0)
        ndvi_max = np.nanmax(matrix, axis=0)
        ndvi_std = np.nanstd(matrix, axis=0)
    ndvi_obs = np.sum(~np.isnan(matrix), axis=0)

    out = pd.DataFrame({
        "cell_id": cell_ids_all,
        "ndvi_mean": ndvi_mean, "ndvi_median": ndvi_median,
        "ndvi_min": ndvi_min, "ndvi_max": ndvi_max,
        "ndvi_std": ndvi_std, "ndvi_observations": ndvi_obs,
    })
    out = out[out["ndvi_observations"] > 0].copy()

    out["ndvi_source"] = "Sentinel-2 L2A (B04/B08, SCL-masked), Microsoft Planetary Computer"
    out["ndvi_native_resolution_m"] = NATIVE_RESOLUTION_M
    out["ndvi_spatial_resolution_m"] = GRID_SIZE_M
    out["ndvi_period_start"] = DATE_START
    out["ndvi_period_end"] = DATE_END
    out["data_status"] = "REAL_SATELLITE_DATA"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_CSV, index=False)

    coverage_pct = 100.0 * len(out) / n_cells
    print("\n" + "=" * 70)
    print("NDVI SUMMARY")
    print("=" * 70)
    print(f"Scenes used: {n_successful} (of {len(scenes)} attempted, {len(failures)} failed)")
    print(f"Cells with >=1 observation: {len(out):,} / {n_cells:,} ({coverage_pct:.2f}% coverage)")
    if len(out):
        print(f"ndvi_mean   min={out['ndvi_mean'].min():.3f}  max={out['ndvi_mean'].max():.3f}  "
              f"mean={out['ndvi_mean'].mean():.3f}  median={out['ndvi_mean'].median():.3f}")
    print(f"Output: {OUTPUT_CSV}")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
