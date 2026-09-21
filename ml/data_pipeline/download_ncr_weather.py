#!/usr/bin/env python3
"""
HeatSentinal - Phase 2A: NCR historical weather dataset
=======================================================

NCR boundary  ->  weather sampling grid  ->  Open-Meteo archive download
              ->  quality checks         ->  parquet / csv / metadata

Run from anywhere (paths are resolved from the repository root):

    python ml/data_pipeline/download_ncr_weather.py --dry-run      # plan only
    python ml/data_pipeline/download_ncr_weather.py --max-chunks 1 # smoke test
    python ml/data_pipeline/download_ncr_weather.py                # full run
    python ml/data_pipeline/download_ncr_weather.py                # ...re-run to resume

Design notes
------------
* The weather source (ERA5 / ERA5-Land through Open-Meteo) is COARSE
  (~0.1 deg / ~9-11 km for ERA5-Land, ~0.25 deg / ~25 km for ERA5).
  This script never claims 300 m weather resolution. Weather is associated /
  interpolated to the 300 m grid in a later phase.
* One "chunk" = one calendar year x one batch of sampling points.
  Each finished chunk is written atomically to backend/data/phase2/weather/_chunks/,
  so an interrupted download resumes exactly where it stopped.
* Missing values are NEVER replaced. They stay NaN/null and are reported.
* Phase 1 data (backend/data/phase1/...) is never read or written here.
* No Heat Index / WBGT / UTCI / ML labels are computed in this phase.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import shapely
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# CONFIGURATION  (path convention follows generate_ncr_grid.py:
# backend/data/... relative to the repository root)
# ============================================================

SCRIPT_VERSION = "1.0.0"

REPO_ROOT = Path(
    os.environ.get("HEATSENTINEL_ROOT", Path(__file__).resolve().parents[2])
)

BOUNDARY_REL = "backend/data/ncr_boundary.geojson"
BOUNDARY_FILE = REPO_ROOT / BOUNDARY_REL

OUT_REL = "backend/data/phase2/weather"
OUT_DIR = REPO_ROOT / OUT_REL
CHUNK_DIR = OUT_DIR / "_chunks"

PARQUET_FILE = OUT_DIR / "ncr_weather_2015_2025.parquet"
CSV_FILE = OUT_DIR / "ncr_weather_2015_2025.csv"
METADATA_FILE = OUT_DIR / "weather_metadata.json"
SAMPLING_POINTS_FILE = OUT_DIR / "weather_sampling_points.csv"   # what we asked for
GRID_POINTS_FILE = OUT_DIR / "weather_grid_points.csv"           # what Open-Meteo returned
LOG_FILE = OUT_DIR / "download.log"

API_URL = "https://archive-api.open-meteo.com/v1/archive"
MODEL = "era5_seamless"
TIMEZONE = "Asia/Kolkata"

DEFAULT_START_YEAR = 2015
DEFAULT_END_YEAR = 2025

VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "shortwave_radiation",
]

# Units we ask for, and the unit labels the API must echo back.
REQUEST_UNITS = {"temperature_unit": "celsius", "wind_speed_unit": "ms"}
ACCEPTED_UNIT_LABELS = {
    "temperature_2m": {"°C"},
    "relative_humidity_2m": {"%"},
    "wind_speed_10m": {"m/s"},
    "shortwave_radiation": {"W/m²", "W/m2"},
}

# Physical plausibility bounds - used ONLY for reporting, never for altering data.
PLAUSIBLE_RANGE = {
    "temperature_2m": (-10.0, 55.0),
    "relative_humidity_2m": (0.0, 100.0),
    "wind_speed_10m": (0.0, 40.0),
    "shortwave_radiation": (0.0, 1400.0),
}

OUTPUT_COLUMNS = ["timestamp", "latitude", "longitude"] + VARIABLES
KEY_COLUMNS = ["timestamp", "latitude", "longitude"]

SAMPLING_STEP_DEG = 0.1        # ERA5-Land native grid spacing (finest grid in ERA5-Seamless)
DEFAULT_BATCH_SIZE = 20        # locations per API request
REQUEST_TIMEOUT = (10, 180)    # (connect, read) seconds

log = logging.getLogger("ncr_weather")


# ============================================================
# EXCEPTIONS
# ============================================================

class DailyLimitReached(Exception):
    """API quota exhausted - stop cleanly, resume later."""


class FatalApiError(Exception):
    """Request is wrong (HTTP 4xx other than 429 / unexpected units). Abort."""


class TransientChunkError(Exception):
    """This chunk failed after retries; other chunks may still work."""


# ============================================================
# BOUNDARY + SAMPLING GRID
# ============================================================

def load_boundary():
    if not BOUNDARY_FILE.exists():
        raise FileNotFoundError(f"NCR boundary not found: {BOUNDARY_FILE}")

    gdf = gpd.read_file(BOUNDARY_FILE)
    if gdf.empty:
        raise RuntimeError("NCR boundary is empty.")

    if gdf.crs is None:
        log.warning("Boundary has no CRS - assuming EPSG:4326.")
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        log.info("Reprojecting boundary from %s to EPSG:4326", gdf.crs)
        gdf = gdf.to_crs("EPSG:4326")

    gdf["geometry"] = gdf.geometry.make_valid()
    boundary = gdf.geometry.union_all()
    log.info("Loaded %d boundary feature(s); geometry type: %s", len(gdf), boundary.geom_type)
    return boundary


def build_sampling_points(boundary, step: float, min_overlap: float) -> pd.DataFrame:
    """
    Regular lat/lon lattice aligned to multiples of `step` degrees (the ERA5-Land
    grid nodes). A node is kept only if its step x step footprint intersects the
    NCR boundary, so the whole NCR is covered while points that serve no NCR
    area are dropped.
    """
    half = step / 2.0
    minx, miny, maxx, maxy = boundary.bounds

    lon_idx = np.arange(math.floor((minx - half) / step), math.ceil((maxx + half) / step) + 1)
    lat_idx = np.arange(math.floor((miny - half) / step), math.ceil((maxy + half) / step) + 1)
    lons = np.round(lon_idx * step, 4)
    lats = np.round(lat_idx * step, 4)

    lon_g, lat_g = np.meshgrid(lons, lats)
    lon_f, lat_f = lon_g.ravel(), lat_g.ravel()

    boxes = shapely.box(lon_f - half, lat_f - half, lon_f + half, lat_f + half)
    shapely.prepare(boundary)
    hit = shapely.intersects(boxes, boundary)

    lon_f, lat_f, boxes = lon_f[hit], lat_f[hit], boxes[hit]
    overlap = shapely.area(shapely.intersection(boxes, boundary)) / (step * step)

    if min_overlap > 0:
        keep = overlap >= min_overlap
        lon_f, lat_f, overlap = lon_f[keep], lat_f[keep], overlap[keep]

    pts = pd.DataFrame(
        {
            "requested_latitude": lat_f,
            "requested_longitude": lon_f,
            "footprint_overlap_fraction": np.round(overlap, 4),
            "inside_ncr": shapely.contains_xy(boundary, lon_f, lat_f),
        }
    )
    pts = pts.sort_values(["requested_latitude", "requested_longitude"]).reset_index(drop=True)
    pts.insert(0, "point_id", [f"REQ_{i:04d}" for i in range(1, len(pts) + 1)])

    log.info(
        "Bounding box: lon %.3f..%.3f  lat %.3f..%.3f | candidate lattice %d | kept %d "
        "(%d nodes inside polygon, %d edge nodes whose cell touches NCR)",
        minx, maxx, miny, maxy, len(lat_idx) * len(lon_idx), len(pts),
        int(pts.inside_ncr.sum()), int((~pts.inside_ncr).sum()),
    )
    if pts.empty:
        raise RuntimeError("No sampling points generated - check the boundary file.")
    return pts


def prepare_plan(pts: pd.DataFrame, args) -> str:
    """Freeze the sampling plan so resumed runs always use identical batches."""
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    plan = {
        "step_deg": args.step,
        "batch_size": args.batch_size,
        "min_overlap": args.min_overlap,
        "model": MODEL,
        "variables": VARIABLES,
        "timezone": TIMEZONE,
        "points": pts[["requested_latitude", "requested_longitude"]].values.tolist(),
    }
    digest = hashlib.sha1(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    plan_file = CHUNK_DIR / "sampling_plan.json"

    if plan_file.exists():
        old = json.loads(plan_file.read_text())
        if old.get("digest") != digest:
            raise SystemExit(
                "\nThe sampling plan (boundary / step / batch size / model) differs from the one "
                f"used for the existing chunks in\n  {CHUNK_DIR}\n"
                "Resuming would mix incompatible chunks. Either restore the original settings, "
                "or delete that _chunks folder to start a fresh download.\n"
            )
    else:
        plan_file.write_text(json.dumps({"digest": digest, "n_points": len(pts), **{
            k: v for k, v in plan.items() if k != "points"}}, indent=2))
    return digest


# ============================================================
# HTTP
# ============================================================

def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5, connect=5, read=5, backoff_factor=2.0,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": f"HeatSentinal-Phase2A/{SCRIPT_VERSION}"})
    return session


def _reason(resp: requests.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and "reason" in body:
            return str(body["reason"])
    except ValueError:
        pass
    return (resp.text or "")[:300]


def request_json(session: requests.Session, params: dict):
    """GET with explicit handling of Open-Meteo rate limits (HTTP 429)."""
    net_failures = 0
    hourly_waits = 0
    while True:
        try:
            resp = session.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as exc:
            net_failures += 1
            if net_failures > 3:
                raise TransientChunkError(f"network failure: {exc}") from exc
            wait = 30 * net_failures
            log.warning("Network error (%s). Waiting %ds then retrying...", exc.__class__.__name__, wait)
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            try:
                payload = resp.json()
            except ValueError as exc:
                raise TransientChunkError("API returned invalid JSON") from exc
            if isinstance(payload, dict) and payload.get("error"):
                raise FatalApiError(f"API error: {payload.get('reason', 'unknown')}")
            return payload

        reason = _reason(resp)

        if resp.status_code == 429:
            low = reason.lower()
            if "daily" in low:
                raise DailyLimitReached(reason)
            if "hourly" in low:
                hourly_waits += 1
                if hourly_waits > 12:
                    raise DailyLimitReached(f"still rate-limited after 2h of waiting: {reason}")
                log.warning("Hourly quota reached. Sleeping 10 min (%d/12)...", hourly_waits)
                time.sleep(600)
            elif "minutely" in low:
                log.warning("Per-minute quota reached. Sleeping 65 s...")
                time.sleep(65)
            else:
                log.warning("HTTP 429 (%s). Sleeping 90 s...", reason)
                time.sleep(90)
            continue

        if 400 <= resp.status_code < 500:
            raise FatalApiError(f"HTTP {resp.status_code}: {reason}")
        raise TransientChunkError(f"HTTP {resp.status_code}: {reason}")


# ============================================================
# CHUNKS
# ============================================================

def hours_in_year(year: int) -> int:
    return ((date(year, 12, 31) - date(year, 1, 1)).days + 1) * 24


def chunk_paths(year: int, batch: int):
    stem = f"y{year}_b{batch:03d}"
    return CHUNK_DIR / f"{stem}.parquet", CHUNK_DIR / f"{stem}.meta.json"


def chunk_done(year: int, batch: int) -> bool:
    data, meta = chunk_paths(year, batch)
    return data.exists() and meta.exists()      # meta is written last


def save_chunk(year: int, batch: int, df: pd.DataFrame, meta: dict) -> None:
    data, mfile = chunk_paths(year, batch)
    tmp_d = data.with_name(data.name + ".tmp")
    tmp_m = mfile.with_name(mfile.name + ".tmp")
    df.to_parquet(tmp_d, index=False)
    os.replace(tmp_d, data)
    tmp_m.write_text(json.dumps(meta, indent=1))
    os.replace(tmp_m, mfile)                    # chunk counts as done only after this


def fetch_chunk(session, batch_pts: pd.DataFrame, year: int):
    params = {
        "latitude": ",".join(f"{v:.4f}" for v in batch_pts.requested_latitude),
        "longitude": ",".join(f"{v:.4f}" for v in batch_pts.requested_longitude),
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "hourly": ",".join(VARIABLES),
        "models": MODEL,
        "timezone": TIMEZONE,
        "format": "json",
        **REQUEST_UNITS,
    }
    payload = request_json(session, params)
    locations = payload if isinstance(payload, list) else [payload]
    if len(locations) != len(batch_pts):
        raise TransientChunkError(
            f"expected {len(batch_pts)} locations, API returned {len(locations)}"
        )

    expected_times = pd.date_range(f"{year}-01-01 00:00", f"{year}-12-31 23:00", freq="h")
    frames, loc_meta = [], []

    for loc, (_, req) in zip(locations, batch_pts.iterrows()):
        hourly = loc.get("hourly")
        if not hourly or "time" not in hourly:
            raise TransientChunkError("response has no hourly block")

        units = loc.get("hourly_units", {})
        for var in VARIABLES:
            if var not in hourly:
                raise TransientChunkError(f"variable missing from response: {var}")
            label = units.get(var)
            if label not in ACCEPTED_UNIT_LABELS[var]:
                raise FatalApiError(
                    f"Unexpected unit for {var}: {label!r} (expected one of "
                    f"{sorted(ACCEPTED_UNIT_LABELS[var])})"
                )

        times = pd.DatetimeIndex(pd.to_datetime(hourly["time"]))
        if not times.equals(expected_times):
            raise TransientChunkError(
                f"timestamps for {year} incomplete/misaligned ({len(times)} vs {len(expected_times)})"
            )

        lat = round(float(loc["latitude"]), 4)
        lon = round(float(loc["longitude"]), 4)
        df = pd.DataFrame(
            {
                "timestamp": times.tz_localize(TIMEZONE),
                "latitude": lat,
                "longitude": lon,
            }
        )
        missing = {}
        for var in VARIABLES:
            arr = np.array(hourly[var], dtype="float64")     # JSON null -> NaN (kept, not filled)
            df[var] = arr.astype("float32")
            missing[var] = int(np.isnan(arr).sum())
        frames.append(df)
        loc_meta.append(
            {
                "point_id": req.point_id,
                "requested_latitude": float(req.requested_latitude),
                "requested_longitude": float(req.requested_longitude),
                "latitude": lat,
                "longitude": lon,
                "elevation": loc.get("elevation"),
                "rows": len(df),
                "missing": missing,
            }
        )

    meta = {
        "year": year,
        "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api_url": API_URL,
        "model": MODEL,
        "locations": loc_meta,
    }
    return pd.concat(frames, ignore_index=True)[OUTPUT_COLUMNS], meta


def estimate_weighted_calls(n_points: int, years: list[int]) -> float:
    """Rough estimate of Open-Meteo 'weighted API calls' (long ranges count as many calls)."""
    n_days = sum(hours_in_year(y) // 24 for y in years)
    return n_points * (n_days / 14.0) * (len(VARIABLES) / 10.0)


def download_all(session, batches, years, args) -> str:
    todo = [(y, b) for y in years for b in range(len(batches)) if not chunk_done(y, b)]
    total = len(years) * len(batches)
    log.info("Chunks: %d total | %d already complete | %d to download", total, total - len(todo), len(todo))
    if not todo:
        return "complete"

    started = time.time()
    done_now = 0
    failures = []

    for y, b in todo:
        if args.max_chunks and done_now >= args.max_chunks:
            log.info("--max-chunks %d reached; stopping.", args.max_chunks)
            return "partial"
        idx = total - len(todo) + done_now + len(failures) + 1
        try:
            df, meta = fetch_chunk(session, batches[b], y)
        except DailyLimitReached as exc:
            log.error("API quota exhausted: %s", exc)
            log.error("Progress is saved. Re-run the same command later (quota resets) to resume.")
            return "quota"
        except FatalApiError as exc:
            log.error("Fatal API error on year %d batch %d: %s", y, b, exc)
            raise
        except TransientChunkError as exc:
            log.error("Chunk y%d b%03d failed after retries: %s (will be retried on next run)", y, b, exc)
            failures.append((y, b))
            continue

        save_chunk(y, b, df, meta)
        done_now += 1
        avg = (time.time() - started) / done_now
        remaining = len(todo) - done_now - len(failures)
        missing_total = sum(sum(l["missing"].values()) for l in meta["locations"])
        log.info(
            "[%d/%d] year %d batch %d/%d ok | %d locations | %s rows | missing values: %d | ETA %.0f min",
            idx, total, y, b + 1, len(batches), len(batches[b]), f"{len(df):,}",
            missing_total, remaining * avg / 60.0,
        )
        time.sleep(args.sleep)

    if failures:
        log.error("%d chunk(s) failed: %s. Re-run to retry them.", len(failures), failures)
        return "failed"
    return "complete"


# ============================================================
# ASSEMBLY + QUALITY CHECKS
# ============================================================

class Stats:
    def __init__(self):
        self.v = {k: {"n": 0, "missing": 0, "min": np.inf, "max": -np.inf, "sum": 0.0, "oor": 0}
                  for k in VARIABLES}
        self.rows = 0
        self.rows_all_missing = 0
        self.dup_rows = 0
        self.year_mismatch = 0
        self.loc_counts: dict = {}
        self.t_min = None
        self.t_max = None

    def update(self, df: pd.DataFrame, year: int, dup_before_drop: int):
        self.rows += len(df)
        self.dup_rows += dup_before_drop
        self.year_mismatch += int((df["timestamp"].dt.year != year).sum())
        self.rows_all_missing += int(df[VARIABLES].isna().all(axis=1).sum())
        for var in VARIABLES:
            s = df[var].astype("float64")
            valid = s.dropna()
            d = self.v[var]
            d["missing"] += int(s.isna().sum())
            if len(valid):
                lo, hi = PLAUSIBLE_RANGE[var]
                d["n"] += len(valid)
                d["sum"] += float(valid.sum())
                d["min"] = min(d["min"], float(valid.min()))
                d["max"] = max(d["max"], float(valid.max()))
                d["oor"] += int(((valid < lo) | (valid > hi)).sum())
        for (la, lo_), n in df.groupby(["latitude", "longitude"]).size().items():
            self.loc_counts[(la, lo_)] = self.loc_counts.get((la, lo_), 0) + int(n)
        tmin, tmax = df["timestamp"].min(), df["timestamp"].max()
        self.t_min = tmin if self.t_min is None else min(self.t_min, tmin)
        self.t_max = tmax if self.t_max is None else max(self.t_max, tmax)

    def mean(self, var):
        d = self.v[var]
        return d["sum"] / d["n"] if d["n"] else float("nan")


def load_chunk_metadata(n_batches: int, years: list[int]):
    """Read sidecars; verify that every year returned identical grid cells per batch."""
    ref, downloaded = {}, []
    for b in range(n_batches):
        for y in years:
            _, mfile = chunk_paths(y, b)
            m = json.loads(mfile.read_text())
            downloaded.append(m["downloaded_utc"])
            coords = [(l["latitude"], l["longitude"]) for l in m["locations"]]
            if b not in ref:
                ref[b] = (coords, m["locations"])
            elif coords != ref[b][0]:
                raise RuntimeError(
                    f"Batch {b}: Open-Meteo returned different grid cells in {y} than in earlier years."
                )
    return ref, sorted(downloaded)


def build_grid_points(ref: dict, per_loc_rows: dict, boundary) -> pd.DataFrame:
    rows, seen = [], set()
    for b in sorted(ref):
        for l in ref[b][1]:
            key = (l["latitude"], l["longitude"])
            if key in seen:
                continue                       # two requests snapped to the same cell
            seen.add(key)
            rows.append(
                {
                    "latitude": l["latitude"],
                    "longitude": l["longitude"],
                    "elevation_m": l["elevation"],
                    "requested_point_id": l["point_id"],
                    "requested_latitude": l["requested_latitude"],
                    "requested_longitude": l["requested_longitude"],
                }
            )
    g = pd.DataFrame(rows).sort_values(["latitude", "longitude"]).reset_index(drop=True)
    g.insert(0, "weather_point_id", [f"WX_{i:04d}" for i in range(1, len(g) + 1)])
    g["inside_ncr"] = shapely.contains_xy(boundary, g.longitude.values, g.latitude.values)
    g["n_hourly_records"] = [per_loc_rows.get((la, lo), 0) for la, lo in zip(g.latitude, g.longitude)]
    return g


def nearest_distance_check(boundary, grid: pd.DataFrame, spacing=0.02) -> dict:
    """Distance (km) from a dense lattice of points inside NCR to the nearest weather point."""
    minx, miny, maxx, maxy = boundary.bounds
    xs, ys = np.arange(minx, maxx, spacing), np.arange(miny, maxy, spacing)
    X, Y = np.meshgrid(xs, ys)
    X, Y = X.ravel(), Y.ravel()
    inside = shapely.contains_xy(boundary, X, Y)
    X, Y = X[inside], Y[inside]
    plat, plon = grid.latitude.values, grid.longitude.values
    dmin = np.empty(len(X))
    for s in range(0, len(X), 2000):
        e = s + 2000
        dx = (X[s:e, None] - plon[None, :]) * 111.32 * np.cos(np.radians(Y[s:e, None]))
        dy = (Y[s:e, None] - plat[None, :]) * 110.57
        dmin[s:e] = np.sqrt(dx * dx + dy * dy).min(axis=1)
    return {"n_probe": int(len(X)), "max_km": float(dmin.max()),
            "p95_km": float(np.percentile(dmin, 95)), "mean_km": float(dmin.mean())}


def assemble(boundary, pts, batches, years, args):
    n_batches = len(batches)
    missing = [(y, b) for y in years for b in range(n_batches) if not chunk_done(y, b)]
    if missing:
        raise RuntimeError(f"{len(missing)} chunk(s) not downloaded yet - cannot assemble.")

    log.info("Assembling final dataset from %d chunks...", len(years) * n_batches)
    ref, downloaded = load_chunk_metadata(n_batches, years)

    stats = Stats()
    tmp_parquet = PARQUET_FILE.with_name(PARQUET_FILE.name + ".tmp")
    tmp_csv = CSV_FILE.with_name(CSV_FILE.name + ".tmp")
    for p in (tmp_parquet, tmp_csv):
        if p.exists():
            p.unlink()

    writer, first_csv = None, True
    for y in years:
        df = pd.concat(
            [pd.read_parquet(chunk_paths(y, b)[0]) for b in range(n_batches)], ignore_index=True
        )
        dup = int(df.duplicated(KEY_COLUMNS).sum())
        if dup:
            log.warning("Year %d: %d duplicate (timestamp, lat, lon) rows - identical cells requested "
                        "twice; keeping the first occurrence.", y, dup)
            df = df.drop_duplicates(KEY_COLUMNS, keep="first")
        df = df.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
        stats.update(df, y, dup)

        table = pa.Table.from_pandas(df[OUTPUT_COLUMNS], preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(tmp_parquet, table.schema, compression="snappy")
        writer.write_table(table)

        if not args.skip_csv:
            out = df[OUTPUT_COLUMNS].copy()
            for var in VARIABLES:
                out[var] = out[var].astype("float64").round(2)
            out.to_csv(tmp_csv, mode="a", header=first_csv, index=False)
            first_csv = False
        log.info("  year %d written (%s rows)", y, f"{len(df):,}")
        del df

    writer.close()
    os.replace(tmp_parquet, PARQUET_FILE)
    if not args.skip_csv:
        os.replace(tmp_csv, CSV_FILE)

    grid = build_grid_points(ref, stats.loc_counts, boundary)
    grid.to_csv(GRID_POINTS_FILE, index=False)
    return stats, grid, downloaded


def run_quality_checks(stats: Stats, grid: pd.DataFrame, boundary, years, step: float):
    results = []

    def check(name, ok, detail, warn_only=False):
        status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
        results.append({"check": name, "status": status, "detail": detail})
        log.info("[%s] %s - %s", status, name, detail)

    total_hours = sum(hours_in_year(y) for y in years)
    n_pts = len(grid)

    # 1. missing values
    for var in VARIABLES:
        d = stats.v[var]
        pct = 100.0 * d["missing"] / max(stats.rows, 1)
        check(f"1. missing values: {var}", d["missing"] == 0,
              f"{d['missing']:,} missing ({pct:.4f}%) - left as NaN, not filled", warn_only=True)
    check("1. rows with ALL variables missing", stats.rows_all_missing == 0,
          f"{stats.rows_all_missing:,} rows", warn_only=True)

    # 2. duplicates
    check("2. duplicate (timestamp, lat, lon)", stats.dup_rows == 0,
          f"{stats.dup_rows:,} duplicate rows found (dropped, first kept)", warn_only=True)
    check("2. timestamps fall in their year", stats.year_mismatch == 0,
          f"{stats.year_mismatch:,} out-of-year timestamps")

    # 3-6. ranges
    for n, var in zip("3456", VARIABLES):
        d = stats.v[var]
        lo, hi = PLAUSIBLE_RANGE[var]
        check(f"{n}. {var} range", d["oor"] == 0 and d["n"] > 0,
              f"observed {d['min']:.2f} .. {d['max']:.2f}; plausible {lo}..{hi}; "
              f"{d['oor']:,} value(s) outside plausible bounds (kept unchanged)")

    # completeness: hours per location
    incomplete = {k: v for k, v in stats.loc_counts.items() if v != total_hours}
    check("completeness: hours per weather point", not incomplete,
          f"expected {total_hours:,} per point; {len(incomplete)} point(s) differ")
    check("completeness: total records", stats.rows == n_pts * total_hours,
          f"{stats.rows:,} rows vs expected {n_pts * total_hours:,}")

    # 7. spatial coverage
    half = step / 2.0
    lon, lat = grid.longitude.values, grid.latitude.values
    boxes = shapely.box(lon - half, lat - half, lon + half, lat + half)
    touches = shapely.intersects(boxes, boundary)
    inside = grid.inside_ncr.values
    check("7. every weather cell footprint intersects NCR", bool(touches.all()),
          f"{int(touches.sum())}/{n_pts} intersect; {int(inside.sum())} points lie inside the polygon, "
          f"{int((~inside).sum())} are edge points just outside (kept because their cell covers NCR area)")

    union = shapely.union_all(boxes)
    unc = shapely.difference(boundary, union)
    a_b = gpd.GeoSeries([boundary], crs="EPSG:4326").to_crs("EPSG:6933").area.iloc[0] / 1e6
    a_u = gpd.GeoSeries([unc], crs="EPSG:4326").to_crs("EPSG:6933").area.iloc[0] / 1e6
    check("7. NCR area covered by weather cells", a_u / a_b < 1e-4,
          f"uncovered {a_u:.3f} km2 of {a_b:,.0f} km2 ({100 * a_u / a_b:.4f}%)")

    nd = nearest_distance_check(boundary, grid)
    half_diag = 0.5 * math.hypot(step * 111.32 * math.cos(math.radians(28.5)), step * 110.57)
    check("7. nearest weather point to any NCR location", nd["max_km"] <= half_diag * 1.15,
          f"max {nd['max_km']:.1f} km, p95 {nd['p95_km']:.1f} km, mean {nd['mean_km']:.1f} km "
          f"(half-cell diagonal ~{half_diag:.1f} km)", warn_only=True)

    passed = all(r["status"] != "FAIL" for r in results)
    return results, passed, nd


def write_metadata(stats, grid, downloaded, qc, passed, nd, years, args):
    metadata = {
        "dataset": "HeatSentinal Phase 2A - NCR historical weather",
        "script": f"ml/data_pipeline/download_ncr_weather.py v{SCRIPT_VERSION}",
        "source": "Open-Meteo Historical Weather API (ECMWF ERA5 / ERA5-Land reanalysis)",
        "api_endpoint": API_URL,
        "model_reanalysis": MODEL,
        "start_date": f"{years[0]}-01-01",
        "end_date": f"{years[-1]}-12-31",
        "variables": {
            "temperature_2m": "degC",
            "relative_humidity_2m": "%",
            "wind_speed_10m": "m/s",
            "shortwave_radiation": "W/m2",
        },
        "timezone": TIMEZONE,
        "timestamp_note": "Hourly, timezone-aware (Asia/Kolkata, UTC+05:30, no DST). Values are hourly reanalysis output.",
        "weather_native_resolution": {
            "era5_land": "0.1 deg (~9-11 km)",
            "era5": "0.25 deg (~25 km)",
            "note": ("ERA5-Seamless combines ERA5-Land (0.1 deg) and ERA5 (0.25 deg); which grid a variable "
                     "comes from is decided by Open-Meteo and is not reported per variable in the response. "
                     "Treat the effective weather resolution as ~10-25 km."),
            "sampling_grid_spacing_deg": args.step,
        },
        "number_of_weather_locations": int(len(grid)),
        "number_of_hourly_records": int(stats.rows),
        "hours_per_location": int(sum(hours_in_year(y) for y in years)),
        "download_timestamp": {
            "first_chunk_utc": downloaded[0],
            "last_chunk_utc": downloaded[-1],
            "assembled_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "ncr_boundary_path": BOUNDARY_REL,
        "output_files": {
            "parquet": f"{OUT_REL}/{PARQUET_FILE.name}",
            "csv": None if args.skip_csv else f"{OUT_REL}/{CSV_FILE.name}",
            "weather_grid_points": f"{OUT_REL}/{GRID_POINTS_FILE.name}",
            "sampling_points_requested": f"{OUT_REL}/{SAMPLING_POINTS_FILE.name}",
        },
        "spatial_sampling": {
            "method": ("Regular lat/lon lattice aligned to the ERA5-Land grid; a node is kept if its "
                       f"{args.step} deg x {args.step} deg cell intersects the NCR boundary."),
            "min_overlap_fraction": args.min_overlap,
            "batch_size": args.batch_size,
            "nearest_weather_point_km": nd,
        },
        "variable_statistics": {
            var: {
                "min": None if stats.v[var]["n"] == 0 else stats.v[var]["min"],
                "max": None if stats.v[var]["n"] == 0 else stats.v[var]["max"],
                "mean": None if stats.v[var]["n"] == 0 else stats.mean(var),
                "missing": stats.v[var]["missing"],
            }
            for var in VARIABLES
        },
        "quality_checks": qc,
        "quality_passed": passed,
        "missing_value_policy": "Missing values are preserved as null/NaN. Nothing is imputed or replaced by zero.",
        "notes": [
            "Weather is COARSE resolution (~10-25 km). It does NOT have 300 m resolution.",
            "In a later phase these weather points will be spatially associated / interpolated to the "
            "300 m x 300 m NCR grid (Phase 1 dataset) - e.g. nearest point or inverse-distance weighting.",
            "Coordinates in the dataset are the grid-cell coordinates returned by Open-Meteo, not the requested ones.",
            "No Heat Index, WBGT, UTCI, ML labels or model training are computed in this phase.",
            "Phase 1 data (backend/data/phase1) was not read or modified.",
            "Open-Meteo data is licensed CC BY 4.0 - attribute Open-Meteo and Copernicus/ECMWF ERA5 when publishing.",
        ],
    }
    METADATA_FILE.write_text(json.dumps(metadata, indent=2, default=str))
    return metadata


def print_report(stats, grid, years, args, passed):
    def line(var):
        d = stats.v[var]
        return (f"min {d['min']:.2f} | max {d['max']:.2f} | mean {stats.mean(var):.2f} "
                f"| missing {d['missing']:,}")

    n = 40
    print("\n" + "=" * n)
    print("NCR WEATHER DATASET COMPLETE")
    print("=" * 28)
    print(f"\nSource: Open-Meteo Historical Weather API ({MODEL}, ERA5/ERA5-Land reanalysis)")
    print(f"Period: {years[0]}-01-01 to {years[-1]}-12-31 ({TIMEZONE})")
    print(f"Timestamps in data: {stats.t_min} -> {stats.t_max}")
    print(f"Weather points: {len(grid):,}")
    print(f"Hourly records: {stats.rows:,}")
    print(f"Temperature coverage: {line('temperature_2m')}  [degC]")
    print(f"Humidity coverage: {line('relative_humidity_2m')}  [%]")
    print(f"Wind coverage: {line('wind_speed_10m')}  [m/s]")
    print(f"Radiation coverage: {line('shortwave_radiation')}  [W/m2]")
    print(f"Quality checks: {'ALL PASSED' if passed else 'FAILURES - see log above'}")
    print("\nOutput:")
    print(f"{OUT_REL}/{PARQUET_FILE.name}")
    print(f"{OUT_REL}/{CSV_FILE.name}" if not args.skip_csv else "(CSV skipped: --skip-csv)")
    print(f"{OUT_REL}/{METADATA_FILE.name}")
    print(f"{OUT_REL}/{GRID_POINTS_FILE.name}   (actual Open-Meteo grid-cell coordinates)")
    print("\nNote: weather resolution is ~10-25 km, NOT 300 m.")
    print("Next phase (not run here): associate weather to the 300 m grid.")
    print("=" * n)


# ============================================================
# MAIN
# ============================================================

def parse_args():
    p = argparse.ArgumentParser(description="HeatSentinal Phase 2A - NCR historical weather download")
    p.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    p.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="locations per API request")
    p.add_argument("--step", type=float, default=SAMPLING_STEP_DEG, help="sampling grid spacing in degrees")
    p.add_argument("--min-overlap", type=float, default=0.0,
                   help="drop edge cells whose overlap with NCR is below this fraction (default keeps all)")
    p.add_argument("--sleep", type=float, default=1.0, help="seconds to pause between requests")
    p.add_argument("--max-chunks", type=int, default=0, help="download at most N new chunks then stop (testing)")
    p.add_argument("--dry-run", action="store_true", help="build sampling grid + print plan, no downloads")
    p.add_argument("--assemble-only", action="store_true", help="skip downloading; assemble finished chunks")
    p.add_argument("--skip-csv", action="store_true", help="do not write the (very large) CSV")
    return p.parse_args()


def setup_logging():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    root = logging.getLogger("ncr_weather")
    root.setLevel(logging.INFO)
    root.handlers.clear()
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, encoding="utf-8")):
        h.setFormatter(fmt)
        root.addHandler(h)


def main() -> int:
    args = parse_args()
    setup_logging()
    years = list(range(args.start_year, args.end_year + 1))

    print("=" * 70)
    print("NCR HISTORICAL WEATHER DOWNLOADER  (Phase 2A)")
    print("=" * 70)

    boundary = load_boundary()
    pts = build_sampling_points(boundary, args.step, args.min_overlap)
    pts.to_csv(SAMPLING_POINTS_FILE, index=False)

    prepare_plan(pts, args)
    for tmp in CHUNK_DIR.glob("*.tmp"):
        tmp.unlink()

    batches = [pts.iloc[i:i + args.batch_size].reset_index(drop=True)
               for i in range(0, len(pts), args.batch_size)]
    n_req = len(years) * len(batches)
    log.info("Plan: %d points x %d years -> %d batches x %d years = %d requests",
             len(pts), len(years), len(batches), len(years), n_req)
    log.info("Approx. weighted API cost: ~%s calls. Open-Meteo's free tier has hourly/daily quotas, "
             "so a full run can take several days; the script waits/stops safely and resumes.",
             f"{estimate_weighted_calls(len(pts), years):,.0f}")

    if args.dry_run:
        log.info("Dry run: sampling points saved to %s", SAMPLING_POINTS_FILE)
        return 0

    if not args.assemble_only:
        session = build_session()
        try:
            state = download_all(session, batches, years, args)
        except FatalApiError:
            return 1
        except KeyboardInterrupt:
            log.warning("Interrupted. Finished chunks are saved; re-run to resume.")
            return 130
        if state == "quota":
            return 2
        if state in ("partial", "failed"):
            done = sum(chunk_done(y, b) for y in years for b in range(len(batches)))
            log.info("Progress: %d/%d chunks complete. Not assembling yet.", done, n_req)
            return 0 if state == "partial" else 3

    try:
        stats, grid, downloaded = assemble(boundary, pts, batches, years, args)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 3

    qc, passed, nd = run_quality_checks(stats, grid, boundary, years, args.step)
    write_metadata(stats, grid, downloaded, qc, passed, nd, years, args)
    print_report(stats, grid, years, args, passed)
    return 0 if passed else 4


if __name__ == "__main__":
    sys.exit(main())
