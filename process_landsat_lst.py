"""
Phase 1 / Task 3 -- Landsat-derived Land Surface Temperature (LST).

Fixes the previous failure mode:

    Continuing with next scene...
    Successful observations: 0
    RuntimeError: No LST observations available.

That happened because the previous script's actual code no longer exists
in this repository or its git history (verified: no landsat/lst/planetary
file has ever been committed on any branch) -- so this is a fresh,
from-scratch implementation, not a patch. It is written specifically to
avoid the failure modes that produce "0 successful observations" silently:

  1. Assets not signed (or signed with the wrong modifier) -> 403s on
     every read, often swallowed by a bare `except: continue`.
  2. QA_PIXEL bit-mask applied incorrectly (e.g. masking on the wrong
     bits) -> every pixel masked out, not just cloudy ones.
  3. Reprojecting/windowing in the wrong CRS -> an empty read window,
     which silently yields a zero-size or zero-valid array.
  4. A bare "no observations" message with no breakdown of *why* each
     scene contributed nothing.

This script never hides the real exception (see phase1_common.retry) and
always prints, per scene, exactly which QA categories consumed the
scene's pixels, so a genuine "0 valid pixels" scene is diagnosable rather
than mysterious.

Run:
    python process_landsat_lst.py

Resumable: completed scenes are cached under
backend/data/phase1/lst/cache/<scene_id>.npz and skipped on rerun. Delete
that folder (or backend/data/phase1/lst/checkpoint.json) to force a
full re-run.
"""

from __future__ import annotations

import sys
import time
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import planetary_computer
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.windows import from_bounds, Window

from phase1_common import (
    BOUNDARY_FILE, GRID_CRS, GRID_SIZE_M, PHASE1_DIR,
    Checkpoint, aggregate_aligned_array, build_grid_index, cache_path_for,
    gdal_retry_env, load_master_grid, open_pc_catalog, retry, snapped_bounds,
)

# ============================================================
# CONFIG
# ============================================================

COLLECTION = "landsat-c2-l2"
LST_ASSET = "lwir11"        # Surface Temperature (ST_B10), USGS C2 L2
QA_ASSET = "qa_pixel"
NATIVE_RESOLUTION_M = 30
DATE_START = "2026-05-01"
DATE_END = "2026-09-15"
MAX_CLOUD_COVER_PCT = 20.0
BLOCK = GRID_SIZE_M // NATIVE_RESOLUTION_M   # 10 -> 30m pixels per 300m cell

# ST_B10 Collection 2 Level-2 scaling (USGS-published constants).
ST_SCALE = 0.00341802
ST_OFFSET = 149.0

# Broad physical sanity bounds for land-surface temperature (not air
# temperature) anywhere on Earth in the given season -- generous on
# purpose so we only reject genuinely impossible values, not just hot days.
LST_SANITY_MIN_C = -25.0
LST_SANITY_MAX_C = 85.0

OUT_DIR = PHASE1_DIR / "lst"
CACHE_DIR = OUT_DIR / "cache"
CHECKPOINT_FILE = OUT_DIR / "checkpoint.json"
OUTPUT_CSV = OUT_DIR / "lst_300m.csv"


# ============================================================
# QA_PIXEL DECODING (USGS Landsat Collection 2 Level-2, 16-bit)
# ============================================================

def qa_invalid_mask(qa: np.ndarray) -> tuple[np.ndarray, dict]:
    """Returns (invalid_mask, per_flag_pixel_counts) using exactly the
    flags the spec calls for: fill, dilated cloud, cirrus, cloud, cloud
    shadow, snow. Confidence bits are intentionally not used -- the spec
    asks for the named bit flags only, no arbitrary extra filtering."""
    fill = (qa & (1 << 0)) != 0
    dilated_cloud = (qa & (1 << 1)) != 0
    cirrus = (qa & (1 << 2)) != 0
    cloud = (qa & (1 << 3)) != 0
    cloud_shadow = (qa & (1 << 4)) != 0
    snow = (qa & (1 << 5)) != 0

    invalid = fill | dilated_cloud | cirrus | cloud | cloud_shadow | snow
    counts = {
        "fill": int(fill.sum()),
        "dilated_cloud": int(dilated_cloud.sum()),
        "cirrus": int(cirrus.sum()),
        "cloud": int(cloud.sum()),
        "cloud_shadow": int(cloud_shadow.sum()),
        "snow": int(snow.sum()),
        "total_pixels": int(qa.size),
    }
    return invalid, counts


# ============================================================
# STAC SEARCH
# ============================================================

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
    print(f"Found {len(items)} candidate scene(s) under {MAX_CLOUD_COVER_PCT}% cloud.")

    if not items:
        print("No scenes met the cloud-cover threshold -- widening to 40% as a fallback.")

        def _search_wide():
            s = catalog.search(
                collections=[COLLECTION],
                bbox=bbox_wgs84,
                datetime=f"{DATE_START}/{DATE_END}",
                query={"eo:cloud_cover": {"lt": 40}},
            )
            return list(s.items())

        items = retry(_search_wide, label="STAC search (widened)")
        print(f"Found {len(items)} candidate scene(s) under 40% cloud.")

    if not items:
        return []

    # Select spatially: one scene per distinct WRS path/row tile that
    # intersects NCR, not one per time bucket. NCR spans multiple Landsat
    # path/rows (55,225 km2 vs a ~185x180km scene), so time-bucketing alone
    # left ~52% of the grid with zero scenes covering it -- this is what
    # actually fixes that, not a cloud-cover or masking change.
    def tile_key(it):
        # Landsat C2 L2 id format: LC09_L2SP_148040_20260507_02_T1
        # -> "148040" is the 3-digit path + 3-digit row concatenated.
        parts = it.id.split("_")
        return parts[2] if len(parts) > 2 else it.id

    by_tile: dict[str, list] = {}
    for it in items:
        by_tile.setdefault(tile_key(it), []).append(it)

    print(f"Distinct WRS path/row tiles intersecting NCR: {len(by_tile)}")

    selected = [min(v, key=lambda it: it.properties.get("eo:cloud_cover", 100))
                for v in by_tile.values()]
    selected.sort(key=lambda it: it.datetime)

    print(f"Selected {len(selected)} scene(s), one lowest-cloud scene per tile "
          f"(not a fixed count -- driven by how many tiles NCR spans):")
    for it in selected:
        print(f"  - {it.id}  tile={tile_key(it)}  {it.datetime.date()}  "
              f"cloud={it.properties.get('eo:cloud_cover', 'NA')}%")
    return selected


# ============================================================
# PER-SCENE PROCESSING
# ============================================================

def process_scene(item, boundary_bounds_4326, grid_index):
    """Returns dict with keys: cell_id (array), value (array, per-block
    mean LST in C), n_valid_cells (int). Raises on unrecoverable failure
    (caller catches and logs a SCENE FAILED block)."""

    # Re-sign right before use. Items are signed once when the STAC search
    # returns them; a full run processing 14 large scenes can take long
    # enough for the earliest signed URLs to expire (Planetary Computer
    # SAS tokens are short-lived) before this scene's turn comes up --
    # confirmed by the 403s clustering on later-processed scenes in the
    # first run. Re-signing here makes each read use a fresh token.
    item = planetary_computer.sign(item)

    scene_id = item.id
    date = item.datetime.date()
    cloud = item.properties.get("eo:cloud_cover", "NA")

    print(f"\n--- Scene {scene_id} ({date}, cloud={cloud}%) ---")

    lst_asset = item.assets.get(LST_ASSET)
    qa_asset = item.assets.get(QA_ASSET)
    print(f"  LST asset ({LST_ASSET}) found: {lst_asset is not None}")
    print(f"  QA asset  ({QA_ASSET}) found: {qa_asset is not None}")
    if lst_asset is None or qa_asset is None:
        raise RuntimeError(
            f"Missing required asset(s) on item {scene_id}: "
            f"{LST_ASSET}={'present' if lst_asset else 'MISSING'}, "
            f"{QA_ASSET}={'present' if qa_asset else 'MISSING'}"
        )

    env_kwargs = gdal_retry_env()

    def _read_band(href):
        with rasterio.Env(**env_kwargs):
            with rasterio.open(href) as src:
                # Window the read to the NCR boundary's bbox in the
                # scene's own CRS -- this is the step that, done in the
                # wrong CRS, silently produces an empty/garbage window.
                left, bottom, right, top = transform_bounds(
                    "EPSG:4326", src.crs, *boundary_bounds_4326
                )
                win = from_bounds(left, bottom, right, top, transform=src.transform)
                win = win.round_offsets().round_lengths()
                # Clip window to the raster's own extent.
                win = win.intersection(Window(0, 0, src.width, src.height))
                if win.width <= 0 or win.height <= 0:
                    raise RuntimeError(
                        f"NCR boundary does not overlap this scene's raster extent "
                        f"(scene bounds vs windowed bounds don't intersect)."
                    )
                data = src.read(1, window=win)
                transform = src.window_transform(win)
                return data, transform, src.crs, src.nodata, (src.width, src.height)

    lst_dn, lst_transform, src_crs, lst_nodata, src_dims = retry(
        lambda: _read_band(lst_asset.href), label=f"read {LST_ASSET} for {scene_id}"
    )
    qa, qa_transform, qa_crs, _, _ = retry(
        lambda: _read_band(qa_asset.href), label=f"read {QA_ASSET} for {scene_id}"
    )

    print(f"  Source CRS: {src_crs}")
    print(f"  Source raster dimensions (full scene): {src_dims[0]} x {src_dims[1]}")
    print(f"  Windowed read shape: {lst_dn.shape}")

    if lst_dn.shape != qa.shape:
        raise RuntimeError(
            f"LST window {lst_dn.shape} and QA window {qa.shape} shapes differ "
            "-- refusing to mask blindly."
        )

    # --- scale DN -> Celsius ---
    lst_dn = lst_dn.astype(np.float64)
    valid_dn = lst_dn != (lst_nodata if lst_nodata is not None else 0)
    lst_c = np.where(valid_dn, lst_dn * ST_SCALE + ST_OFFSET - 273.15, np.nan)

    # --- QA mask ---
    invalid_qa, qa_counts = qa_invalid_mask(qa)
    sane = (lst_c >= LST_SANITY_MIN_C) & (lst_c <= LST_SANITY_MAX_C)
    out_of_sanity = valid_dn & ~np.isnan(lst_c) & ~sane

    final_valid = valid_dn & ~invalid_qa & sane
    lst_c_masked = np.where(final_valid, lst_c, np.nan)

    n_valid_px = int(final_valid.sum())
    total_px = lst_c.size
    print(f"  Pixel breakdown (of {total_px:,} windowed pixels):")
    print(f"    nodata (fill DN):        {int((~valid_dn).sum()):,}")
    print(f"    QA fill:                 {qa_counts['fill']:,}")
    print(f"    QA dilated cloud:        {qa_counts['dilated_cloud']:,}")
    print(f"    QA cirrus:               {qa_counts['cirrus']:,}")
    print(f"    QA cloud:                {qa_counts['cloud']:,}")
    print(f"    QA cloud shadow:         {qa_counts['cloud_shadow']:,}")
    print(f"    QA snow:                 {qa_counts['snow']:,}")
    print(f"    out-of-sanity-range:     {int(out_of_sanity.sum()):,}")
    print(f"    VALID LST pixels:        {n_valid_px:,} "
          f"({100.0 * n_valid_px / total_px:.2f}%)")

    if n_valid_px == 0:
        raise RuntimeError(
            "0 valid pixels after masking -- see breakdown above for which "
            "QA category consumed the scene (commonly: cloud/cirrus over "
            "this scene's overlap with NCR on this date)."
        )

    # --- reproject to EPSG:6933, 30m, origin snapped to 300m grid ---
    left, bottom, right, top = rasterio.transform.array_bounds(
        *lst_c_masked.shape, lst_transform
    )
    b_minx, b_miny, b_maxx, b_maxy = transform_bounds(src_crs, GRID_CRS, left, bottom, right, top)
    dminx, dminy, dmaxx, dmaxy = snapped_bounds(b_minx, b_miny, b_maxx, b_maxy, GRID_SIZE_M)

    dst_width = int(round((dmaxx - dminx) / NATIVE_RESOLUTION_M))
    dst_height = int(round((dmaxy - dminy) / NATIVE_RESOLUTION_M))
    # Ensure exact divisibility by BLOCK (guaranteed by snapping to 300m,
    # but guard against float rounding at the edges).
    dst_width -= dst_width % BLOCK
    dst_height -= dst_height % BLOCK
    if dst_width <= 0 or dst_height <= 0:
        raise RuntimeError("Snapped destination raster has zero size.")

    dst_transform = rasterio.transform.from_origin(
        dminx, dmaxy, NATIVE_RESOLUTION_M, NATIVE_RESOLUTION_M
    )
    dst = np.full((dst_height, dst_width), np.nan, dtype=np.float64)

    reproject(
        source=lst_c_masked,
        destination=dst,
        src_transform=lst_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=GRID_CRS,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=Resampling.nearest,
    )

    stats = aggregate_aligned_array(dst, block=BLOCK)
    n_br, n_bc = stats["mean"].shape

    # block (r,c) -> centroid in EPSG:6933 -> grid col/row -> cell_id
    rows_idx, cols_idx = np.meshgrid(np.arange(n_br), np.arange(n_bc), indexing="ij")
    block_cx = dminx + (cols_idx * BLOCK + BLOCK / 2) * NATIVE_RESOLUTION_M
    block_cy = dmaxy - (rows_idx * BLOCK + BLOCK / 2) * NATIVE_RESOLUTION_M

    from phase1_common import GridIndex
    gcol, grow = GridIndex.col_row_from_xy(block_cx.ravel(), block_cy.ravel())
    cell_ids = grid_index.lookup(gcol, grow)

    flat_mean = stats["mean"].ravel()
    has_cell = pd.notna(cell_ids)
    has_value = ~np.isnan(flat_mean)
    keep = has_cell & has_value

    n_valid_cells = int(keep.sum())
    print(f"  300m cells covered by this scene: {n_valid_cells:,}")

    return {
        "cell_id": cell_ids[keep],
        "mean": flat_mean[keep],
        "n_valid_cells": n_valid_cells,
        "scene_id": scene_id,
        "date": str(date),
        "cloud_cover": cloud,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("LANDSAT LST PROCESSING (Phase 1, Task 3)")
    print("=" * 70)

    grid = load_master_grid()
    grid_index = build_grid_index(grid)
    print(f"Master grid loaded: {grid_index.n_cells:,} cells.")

    import geopandas as gpd
    boundary = gpd.read_file(BOUNDARY_FILE)
    boundary_bounds_4326 = tuple(boundary.to_crs("EPSG:4326").total_bounds)
    print(f"NCR boundary bbox (WGS84): {boundary_bounds_4326}")

    catalog = open_pc_catalog()
    scenes = search_scenes(catalog, boundary_bounds_4326)
    if not scenes:
        raise RuntimeError(
            "STAC search returned zero scenes for the given date range and "
            "cloud-cover threshold. This is a search-parameter problem, not "
            "a per-scene read problem -- check DATE_START/DATE_END and "
            "MAX_CLOUD_COVER_PCT in process_landsat_lst.py."
        )

    checkpoint = Checkpoint(CHECKPOINT_FILE)

    # per-cell-per-scene matrix for correct across-scene median/std/etc.
    n_cells = grid_index.n_cells
    cell_ids_all = grid["cell_id"].to_numpy()
    cell_pos = pd.Series(np.arange(n_cells), index=cell_ids_all)

    scene_values = []   # list of (n_cells,) float32 arrays, one per scene, NaN where uncovered
    scene_meta = []
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
            scene_meta.append(dict(npz["meta"].item()))
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

        meta = {
            "scene_id": scene_id, "date": result["date"],
            "cloud_cover": result["cloud_cover"], "n_valid_cells": result["n_valid_cells"],
        }
        scene_meta.append(meta)

        np.savez_compressed(
            cache_file, cell_id=result["cell_id"], mean=result["mean"],
            meta=np.array(meta, dtype=object),
        )
        checkpoint.mark_done(scene_id, meta)

    n_successful = len(scene_values)
    print(f"\nSuccessful scenes: {n_successful} / {len(scenes)}")

    if n_successful == 0:
        print("\n" + "=" * 70)
        print("ALL SCENES FAILED -- DIAGNOSTIC SUMMARY")
        print("=" * 70)
        for sid, err in failures:
            print(f"\n{sid}:\n  {err}")
        raise RuntimeError(
            f"No LST observations available: all {len(scenes)} scene(s) failed. "
            "See the per-scene diagnostics above for the specific cause of "
            "each failure -- do not re-run blindly without reading them."
        )

    # --- final per-cell stats across scenes ---
    matrix = np.stack(scene_values, axis=0)  # (n_scenes, n_cells)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        lst_mean = np.nanmean(matrix, axis=0)
        lst_median = np.nanmedian(matrix, axis=0)
        lst_min = np.nanmin(matrix, axis=0)
        lst_max = np.nanmax(matrix, axis=0)
        lst_std = np.nanstd(matrix, axis=0)
    lst_obs = np.sum(~np.isnan(matrix), axis=0)

    out = pd.DataFrame({
        "cell_id": cell_ids_all,
        "lst_mean_c": lst_mean,
        "lst_median_c": lst_median,
        "lst_min_c": lst_min,
        "lst_max_c": lst_max,
        "lst_std_c": lst_std,
        "lst_observations": lst_obs,
    })
    out = out[out["lst_observations"] > 0].copy()

    out["lst_source"] = "Landsat 8/9 Collection 2 Level-2 (ST_B10 / lwir11), Microsoft Planetary Computer"
    out["lst_native_resolution_m"] = NATIVE_RESOLUTION_M
    out["lst_spatial_resolution_m"] = GRID_SIZE_M
    out["lst_period_start"] = DATE_START
    out["lst_period_end"] = DATE_END
    out["lst_scene_count"] = n_successful
    out["data_status"] = "REAL_SATELLITE_DATA"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_CSV, index=False)

    coverage_pct = 100.0 * len(out) / n_cells
    print("\n" + "=" * 70)
    print("LST SUMMARY")
    print("=" * 70)
    print(f"Scenes used: {n_successful} (of {len(scenes)} attempted, {len(failures)} failed)")
    print(f"Cells with >=1 observation: {len(out):,} / {n_cells:,} ({coverage_pct:.2f}% coverage)")
    if len(out):
        print(f"lst_mean_c   min={out['lst_mean_c'].min():.2f}  "
              f"max={out['lst_mean_c'].max():.2f}  mean={out['lst_mean_c'].mean():.2f}  "
              f"median={out['lst_mean_c'].median():.2f}")
    print(f"Output: {OUTPUT_CSV}")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
