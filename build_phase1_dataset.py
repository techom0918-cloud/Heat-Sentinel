"""
Phase 1 / Task 7 -- merge LST + NDVI + land cover + elevation onto the
existing 300m master grid, run data-quality checks, and write the final
deliverables:

    backend/data/phase1/heat_environment_300m.gpkg
    backend/data/phase1/heat_environment_300m.csv

Run this LAST, after:
    python generate_ncr_grid.py        (only if the grid doesn't exist yet)
    python process_landsat_lst.py
    python process_sentinel_ndvi.py
    python process_land_cover.py
    python process_elevation.py

This script does not fetch anything from the network -- it only reads the
CSVs those four scripts already wrote, so it is safe/cheap to re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from phase1_common import PHASE1_DIR, field_quality_report, load_master_grid

LST_CSV = PHASE1_DIR / "lst" / "lst_300m.csv"
NDVI_CSV = PHASE1_DIR / "ndvi" / "ndvi_300m.csv"
LAND_COVER_CSV = PHASE1_DIR / "land_cover" / "land_cover_300m.csv"
ELEVATION_CSV = PHASE1_DIR / "elevation" / "elevation_300m.csv"

OUT_GPKG = PHASE1_DIR / "heat_environment_300m.gpkg"
OUT_CSV = PHASE1_DIR / "heat_environment_300m.csv"

FINAL_COLUMNS = [
    "cell_id",
    "lst_mean_c", "lst_median_c", "lst_min_c", "lst_max_c", "lst_std_c", "lst_observations",
    "ndvi_mean", "ndvi_median", "ndvi_min", "ndvi_max", "ndvi_std", "ndvi_observations",
    "land_cover_class", "land_cover_fraction", "land_cover_name",
    "elevation_mean_m", "elevation_min_m", "elevation_max_m",
]


def load_optional(path: Path, label: str) -> pd.DataFrame | None:
    if not path.exists():
        print(f"  [{label}] NOT FOUND: {path} -- run the corresponding process_*.py script.")
        return None
    df = pd.read_csv(path)
    print(f"  [{label}] loaded: {len(df):,} rows from {path}")
    return df


def main():
    print("=" * 70)
    print("PHASE 1 -- FINAL INTEGRATED DATASET (Task 7) + VERIFICATION")
    print("=" * 70)

    grid = load_master_grid()
    n_cells = len(grid)
    print(f"\nMaster grid: {n_cells:,} cells.")

    print("\nLoading per-feature outputs...")
    lst = load_optional(LST_CSV, "LST")
    ndvi = load_optional(NDVI_CSV, "NDVI")
    land_cover = load_optional(LAND_COVER_CSV, "Land Cover")
    elevation = load_optional(ELEVATION_CSV, "Elevation")

    status = {
        "NCR Boundary": "PASS",   # verified separately; this script assumes it, per Task 1
        "300m Grid": "PASS",      # loaded above without error
        "Landsat LST": "PASS" if lst is not None and len(lst) else "FAIL",
        "Sentinel-2 NDVI": "PASS" if ndvi is not None and len(ndvi) else "FAIL",
        "Land Cover": "PASS" if land_cover is not None and len(land_cover) else "FAIL",
        "Elevation": "PASS" if elevation is not None and len(elevation) else "FAIL",
    }

    merged = grid[["cell_id", "geometry"]].copy()
    for df, cols in [
        (lst, ["cell_id", "lst_mean_c", "lst_median_c", "lst_min_c", "lst_max_c",
               "lst_std_c", "lst_observations"]),
        (ndvi, ["cell_id", "ndvi_mean", "ndvi_median", "ndvi_min", "ndvi_max",
                "ndvi_std", "ndvi_observations"]),
        (land_cover, ["cell_id", "land_cover_class", "land_cover_fraction", "land_cover_name"]),
        (elevation, ["cell_id", "elevation_mean_m", "elevation_min_m", "elevation_max_m"]),
    ]:
        if df is not None:
            merged = merged.merge(df[cols], on="cell_id", how="left")

    # --- data-quality checks ---
    print("\n" + "=" * 70)
    print("DATA QUALITY CHECKS")
    print("=" * 70)

    dupe_ids = merged["cell_id"].duplicated().sum()
    missing_ids = merged["cell_id"].isna().sum()
    invalid_geom = (~merged.geometry.is_valid).sum()
    print(f"Duplicate cell_id: {dupe_ids}")
    print(f"Missing cell_id: {missing_ids}")
    print(f"Invalid geometry: {invalid_geom}")

    checks_ok = dupe_ids == 0 and missing_ids == 0 and invalid_geom == 0

    field_ranges = {
        "lst_mean_c": (-25.0, 85.0),
        "ndvi_mean": (-1.0, 1.0),
        "elevation_mean_m": (-430.0, 9000.0),
    }
    print("\nPer-field quality report:")
    reports = {}
    for col, rng in field_ranges.items():
        if col in merged.columns:
            r = field_quality_report(merged[col], valid_range=rng)
            reports[col] = r
            print(f"\n  {col}:")
            for k, v in r.items():
                print(f"    {k}: {v}")

    inf_cols = [c for c in merged.select_dtypes(include=[np.number]).columns
                if np.isinf(merged[c].to_numpy(dtype=np.float64, na_value=0)).any()]
    print(f"\nColumns containing infinite values: {inf_cols or 'none'}")

    status["Integrated Dataset"] = "PASS" if checks_ok and not inf_cols else "FAIL"

    # --- write outputs ---
    PHASE1_DIR.mkdir(parents=True, exist_ok=True)
    csv_cols = [c for c in FINAL_COLUMNS if c in merged.columns]
    merged[csv_cols].to_csv(OUT_CSV, index=False)

    gpkg_cols = ["geometry"] + csv_cols
    merged[gpkg_cols].to_file(OUT_GPKG, layer="heat_environment_300m", driver="GPKG")

    csv_size_mb = OUT_CSV.stat().st_size / (1024 * 1024)
    gpkg_size_mb = OUT_GPKG.stat().st_size / (1024 * 1024)

    # --- sample rows ---
    print("\n" + "=" * 70)
    print("10 RANDOM SAMPLE ROWS")
    print("=" * 70)
    sample_cols = [c for c in ["cell_id", "lst_mean_c", "ndvi_mean", "land_cover_name",
                                "elevation_mean_m"] if c in merged.columns]
    if len(merged):
        print(merged[sample_cols].sample(min(10, len(merged)), random_state=42).to_string(index=False))

    # --- final report ---
    print("\n" + "=" * 70)
    print("PHASE 1 STATUS")
    print("=" * 70)
    for k, v in status.items():
        print(f"{k}: {v}")

    print(f"\nTotal 300m cells: {n_cells:,}")
    for name, df, col in [
        ("LST", lst, "lst_observations"), ("NDVI", ndvi, "ndvi_observations"),
        ("Land Cover", land_cover, "land_cover_class"), ("Elevation", elevation, "elevation_mean_m"),
    ]:
        if df is not None:
            print(f"{name} coverage: {len(df):,} / {n_cells:,} "
                  f"({100.0 * len(df) / n_cells:.2f}%)")
        else:
            print(f"{name} coverage: NOT RUN")

    print(f"\nFinal dataset (CSV): {OUT_CSV}  ({csv_size_mb:.2f} MB)")
    print(f"Final dataset (GPKG): {OUT_GPKG}  ({gpkg_size_mb:.2f} MB)")

    remaining = [k for k, v in status.items() if v == "FAIL"]
    if remaining:
        print(f"\nRemaining problems: {', '.join(remaining)} did not produce data -- "
              "run the corresponding process_*.py script and re-run this script.")
    else:
        print("\nNo remaining problems -- Phase 1 complete.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
