
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent
HANDOFF = ROOT / "backend" / "data" / "phase2" / "ml_handoff"
ENV = HANDOFF / "01_environment_300m_with_weather_link.parquet"
WEATHER = HANDOFF / "02_weather_2022_2025_with_point_id.parquet"
THERMAL = HANDOFF / "04_thermal_features_point_hour.parquet"
MAPPING = HANDOFF / "03_weather_to_300m_mapping.parquet"

if not all(p.exists() for p in [ENV, WEATHER, THERMAL, MAPPING]):
    missing = [str(p) for p in [ENV, WEATHER, THERMAL, MAPPING] if not p.exists()]
    raise FileNotFoundError("Missing required handoff files:\n" + "\n".join(missing))

OUT = HANDOFF

print("=" * 72)
print("HEATSENTINEL — HEAT INDEX TARGET + ML TRAINING DATA")
print("=" * 72)

# ---------------------------------------------------------------------
# 1. Load existing prepared data
# ---------------------------------------------------------------------
print("\n[1/6] Loading prepared datasets...")
env = pd.read_parquet(ENV)
weather = pd.read_parquet(WEATHER)
thermal = pd.read_parquet(THERMAL)
mapping = pd.read_parquet(MAPPING)

print(f"  300m environment rows : {len(env):,}")
print(f"  Weather rows           : {len(weather):,}")
print(f"  Thermal rows           : {len(thermal):,}")
print(f"  Mapping rows           : {len(mapping):,}")

# ---------------------------------------------------------------------
# 2. Define Heat Index category
# ---------------------------------------------------------------------
# User-selected category thresholds, expressed in Celsius.
# Boundaries are the approximate Celsius conversion of the conventional
# Heat Index bands:
#   <80 F, 80-90 F, 90-105 F, 105-130 F, >130 F
#
# This creates:
#   LOW       < 26.7 C
#   MODERATE  26.7–32.2 C
#   HIGH      32.2–40.6 C
#   VERY_HIGH 40.6–54.4 C
#   EXTREME   > 54.4 C
#
# Do NOT silently use the earlier simplified 27/32/41/54 cutoffs;
# the script stores the exact thresholds used here.
print("\n[2/6] Creating Heat Index target labels...")

hi = pd.to_numeric(thermal["heat_index_c"], errors="coerce")

labels = ["LOW", "MODERATE", "HIGH", "VERY_HIGH", "EXTREME"]

# Use pandas.cut so missing Heat Index values remain NaN and there is
# no NumPy string/float dtype conflict.
thermal["heat_index_category"] = pd.cut(
    hi,
    bins=[-np.inf, 26.7, 32.2, 40.6, 54.4, np.inf],
    labels=labels,
    right=False,
    include_lowest=True,
    ordered=True,
)

# Save target at weather-point/hour level.
target_cols = [
    "timestamp", "weather_point_id", "latitude", "longitude",
    "heat_index_c", "heat_index_category"
]
target = thermal[target_cols].copy()
target.to_parquet(OUT / "05_heat_index_target_point_hour.parquet", index=False)
target.to_csv(OUT / "05_heat_index_target_point_hour.csv", index=False)

counts = (
    target["heat_index_category"]
    .value_counts(dropna=False)
    .reindex(labels, fill_value=0)
    .rename_axis("heat_index_category")
    .reset_index(name="rows")
)
counts["percentage"] = counts["rows"] / len(target) * 100

print("\n  Target distribution:")
print(counts.to_string(index=False))

# ---------------------------------------------------------------------
# 3. Aggregate static 300m environment to each weather point
# ---------------------------------------------------------------------
# The weather source is ~10–25 km, so expanding every hourly weather
# row to all 618k cells would create billions of rows and falsely imply
# 300m weather resolution.
#
# For a manageable baseline training table, summarize the 300m
# environmental cells assigned to each weather point. This preserves
# the environmental context while respecting the source weather
# resolution.
print("\n[3/6] Aggregating 300m environmental context to weather points...")

static_cols = [
    c for c in [
        "lst_mean_c", "lst_median_c", "lst_min_c", "lst_max_c",
        "lst_std_c", "ndvi_mean", "ndvi_median", "ndvi_min", "ndvi_max",
        "ndvi_std", "land_cover_fraction",
        "elevation_mean_m", "elevation_min_m", "elevation_max_m"
    ] if c in env.columns
]

env2 = env.copy()
env2["cell_id"] = env2["cell_id"].astype(str)
mapping2 = mapping.copy()
mapping2["cell_id"] = mapping2["cell_id"].astype(str)

# Mapping supplies the stable weather_point_id.
cell = env2[["cell_id"] + static_cols].merge(
    mapping2[["cell_id", "weather_point_id"]],
    on="cell_id",
    how="inner",
    validate="one_to_one"
)

agg = cell.groupby("weather_point_id", as_index=False)[static_cols].agg(
    ["mean", "median", "min", "max"]
)
agg.columns = [
    "weather_point_id" if c[0] == "" else f"{c[0]}_{c[1]}"
    for c in agg.columns.to_flat_index()
]
agg = agg.reset_index(drop=True)

# Pandas can create a slightly different first column depending on version;
# make sure the key exists.
if "weather_point_id" not in agg.columns:
    if agg.index.name == "weather_point_id":
        agg = agg.reset_index()
    else:
        first = agg.columns[0]
        agg = agg.rename(columns={first: "weather_point_id"})

print(f"  Weather-point environmental summaries: {len(agg):,}")

# ---------------------------------------------------------------------
# 4. Build final training table
# ---------------------------------------------------------------------
print("\n[4/6] Building ML training table...")

# Thermal contains weather variables + derived thermal indices.
feature_cols = [
    "timestamp",
    "weather_point_id",
    "latitude",
    "longitude",
    "temperature_2m_c",
    "relative_humidity_pct",
    "wind_speed_10m_ms",
    "shortwave_radiation_wm2",
    "heat_index_c",
    "wbgt_shade_proxy_c",
    "heat_index_category",
]

missing_features = [c for c in feature_cols if c not in thermal.columns]
if missing_features:
    raise ValueError(f"Thermal feature columns missing: {missing_features}")

ml = thermal[feature_cols].merge(
    agg,
    on="weather_point_id",
    how="left",
    validate="many_to_one"
)

# Add temporal features that the ML owner can use or drop.
ts = pd.to_datetime(ml["timestamp"])
ml["year"] = ts.dt.year.astype("int16")
ml["month"] = ts.dt.month.astype("int8")
ml["day_of_year"] = ts.dt.dayofyear.astype("int16")
ml["hour"] = ts.dt.hour.astype("int8")
ml["day_of_week"] = ts.dt.dayofweek.astype("int8")

# Cyclic encodings
ml["hour_sin"] = np.sin(2 * np.pi * ml["hour"] / 24)
ml["hour_cos"] = np.cos(2 * np.pi * ml["hour"] / 24)
ml["doy_sin"] = np.sin(2 * np.pi * ml["day_of_year"] / 365.25)
ml["doy_cos"] = np.cos(2 * np.pi * ml["day_of_year"] / 365.25)

# Remove rows with no target.
ml = ml.dropna(subset=["heat_index_category"]).reset_index(drop=True)

ml_path = OUT / "06_ml_training_point_hour_2022_2025.parquet"
ml.to_parquet(ml_path, index=False)

print(f"  ML training rows: {len(ml):,}")
print(f"  ML columns      : {len(ml.columns):,}")

# ---------------------------------------------------------------------
# 5. Training guidance / target definition
# ---------------------------------------------------------------------
print("\n[5/6] Writing ML documentation...")

rules = pd.DataFrame([
    ["LOW", "< 26.7 °C", "Heat Index below 80 °F"],
    ["MODERATE", "26.7–<32.2 °C", "80–<90 °F"],
    ["HIGH", "32.2–<40.6 °C", "90–<105 °F"],
    ["VERY_HIGH", "40.6–<54.4 °C", "105–<130 °F"],
    ["EXTREME", ">=54.4 °C", ">=130 °F"],
], columns=["category", "heat_index_c_range", "reference_band"])

rules.to_csv(OUT / "05_heat_index_target_rules.csv", index=False)

notes = pd.DataFrame([
    ["Target", "heat_index_category"],
    ["Target source", "heat_index_c from current thermal feature pipeline"],
    ["Period", "2022–2025"],
    ["Training table", "06_ml_training_point_hour_2022_2025.parquet"],
    ["Spatial caveat", "Weather is ~10–25 km resolution; this table uses environmental summaries per weather point."],
    ["Important", "This is a baseline ML handoff, not a true 300m hourly weather model."],
    ["Recommended validation", "Use chronological train/validation/test split to avoid temporal leakage."],
    ["Recommended metric", "Macro F1 + per-class precision/recall; inspect confusion matrix and class balance."],
    ["Target validation", "Validate Heat Index calculation and category thresholds before operational deployment."],
], columns=["item", "value"])

notes.to_csv(OUT / "06_ML_TRAINING_NOTES.csv", index=False)

# ---------------------------------------------------------------------
# 6. Add compact information to the Excel workbook
# ---------------------------------------------------------------------
xlsx = OUT / "HeatSentinel_ML_Handoff.xlsx"

with pd.ExcelWriter(
    xlsx,
    engine="openpyxl",
    mode="a",
    if_sheet_exists="replace"
) as writer:
    counts.to_excel(writer, sheet_name="TARGET_DISTRIBUTION", index=False)
    rules.to_excel(writer, sheet_name="TARGET_RULES", index=False)
    notes.to_excel(writer, sheet_name="ML_TRAINING_NOTES", index=False)

print("\n" + "=" * 72)
print("COMPLETE")
print("=" * 72)
print(f"Target file : {target.name}")
print(f"Training file: {ml_path.name}")
print(f"Excel updated: {xlsx.name}")
print("\nIMPORTANT:")
print("The target is generated from the current Heat Index calculation.")
print("Validate the Heat Index implementation/thresholds before production use.")
print("No artificial/random labels were created.")
