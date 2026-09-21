# Phase 1 -- Environmental Dataset (Delhi-NCR, 300m)

## Why this exists

The pipeline that previously failed with `Successful observations: 0` /
`RuntimeError: No LST observations available` does not exist anywhere in
this repo's git history (checked all branches) -- it must have been a
local, uncommitted script. Everything below is a fresh implementation,
built to avoid the failure modes that produce that exact silent-zero
symptom (see `process_landsat_lst.py`'s docstring for the full list).

## Two things to know before you run this

1. **Dynamic World V1 is not on Microsoft Planetary Computer.** I verified
   this by searching PC's STAC catalog directly. `process_land_cover.py`
   defaults to PC's `io-lulc-9-class` (Esri/Impact Observatory) with a
   documented class remap onto the same 0-8 schema you specified. The one
   real gap: Esri's "Rangeland" merges grass + shrub/scrub, so your class
   2 (`grass`) will read ~0 cells under this source. If you need true
   Dynamic World, that requires a Google-Earth-Engine version of this
   script instead -- say so and I'll build it.
2. **I could not run or verify Tasks 3-6 myself.** The sandbox this was
   built in blocks `planetarycomputer.microsoft.com` at the network
   level (confirmed: `x-deny-reason: host_not_allowed`). Everything below
   is written, syntax-checked, and the aggregation math is validated
   end-to-end against your real 618,373-cell grid using a synthetic
   raster with a known value (see chat) -- but the actual STAC
   search/read/mask against real Landsat/Sentinel/NASADEM/land-cover data
   has only run against your machine's network, not mine. Run it and send
   me the console output if anything looks off.

## Install (once)

```
pip install -r requirements-phase1.txt
```

## Run order

```
python generate_ncr_grid.py        # only if backend\data\ncr_300m_grid.gpkg doesn't exist yet
python process_landsat_lst.py
python process_sentinel_ndvi.py
python process_land_cover.py
python process_elevation.py
python build_phase1_dataset.py
```

Each `process_*.py` is independently resumable: it caches completed
scenes/tiles under `backend/data/phase1/<feature>/cache/` and a
`checkpoint.json` next to it. Re-running after an interruption skips
whatever already succeeded. Delete a feature's `cache/` + checkpoint to
force a clean re-run of just that one.

`build_phase1_dataset.py` only reads the CSVs the four scripts above
produce -- no network calls -- so it's cheap to re-run after any of them.
It prints the PASS/FAIL table, per-field coverage/min/max/mean/median,
duplicate/invalid-geometry checks, and 10 random sample rows, then writes:

```
backend/data/phase1/heat_environment_300m.gpkg
backend/data/phase1/heat_environment_300m.csv
```

## Status as of this handoff (run in this sandbox where possible)

| Task | Status |
|---|---|
| NCR Boundary | **PASS** -- 1 feature, EPSG:4326, valid geometry, 55,224.82 km² |
| 300m Grid | **PASS** -- generated fresh (didn't exist in the repo checkout): 618,373 cells |
| Landsat LST | NOT RUN here (network-blocked) -- code written, unit-tested, geometry validated |
| Sentinel-2 NDVI | NOT RUN here (network-blocked) -- same |
| Land Cover | NOT RUN here (network-blocked) -- same, + Dynamic World caveat above |
| Elevation | NOT RUN here (network-blocked) -- same |
| Integrated Dataset | Merge/verification logic run for real against the actual grid (0% feature coverage, as expected with no source data yet) |

Run the five scripts above on your machine, then send me the console
output (or just say "Phase 1 done") and I'll review the actual
coverage/quality numbers with you.
