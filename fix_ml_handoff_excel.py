
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
H = ROOT / "backend" / "data" / "phase2" / "ml_handoff"
XLSX = H / "HeatSentinel_ML_Handoff.xlsx"

static_file = H / "01_environment_300m_with_weather_link.parquet"
mapping_file = H / "03_weather_to_300m_mapping.parquet"
target_file = H / "05_heat_index_target_point_hour.parquet"
rules_file = H / "05_heat_index_target_rules.csv"
notes_file = H / "06_ML_TRAINING_NOTES.csv"

for p in [static_file, mapping_file, target_file, rules_file, notes_file]:
    if not p.exists():
        raise FileNotFoundError(p)

print("Creating a fresh valid Excel workbook...")

static = pd.read_parquet(static_file)
mapping = pd.read_parquet(mapping_file)
target = pd.read_parquet(target_file)
rules = pd.read_csv(rules_file)
notes = pd.read_csv(notes_file)

labels = ["LOW", "MODERATE", "HIGH", "VERY_HIGH", "EXTREME"]
dist = (
    target["heat_index_category"]
    .astype("string")
    .value_counts()
    .reindex(labels, fill_value=0)
    .rename_axis("heat_index_category")
    .reset_index(name="rows")
)
dist["percentage"] = dist["rows"] / len(target) * 100

data_dictionary = pd.DataFrame([
    ["cell_id", "300m NCR cell identifier", "Spatial key"],
    ["lst_mean_c", "Mean land surface temperature (°C)", "Environment feature"],
    ["ndvi_mean", "Mean NDVI", "Environment feature"],
    ["land_cover_class", "Land-cover class", "Environment feature"],
    ["land_cover_name", "Land-cover name", "Environment feature"],
    ["elevation_mean_m", "Mean elevation (m)", "Environment feature"],
    ["weather_point_id", "Nearest weather point ID", "Join key"],
    ["nearest_weather_distance_km", "Distance to nearest weather point (km)", "Spatial quality"],
    ["timestamp", "Hourly timestamp", "Temporal key"],
    ["temperature_2m_c", "2m air temperature (°C)", "Weather feature"],
    ["relative_humidity_pct", "Relative humidity (%)", "Weather feature"],
    ["wind_speed_10m_ms", "10m wind speed (m/s)", "Weather feature"],
    ["shortwave_radiation_wm2", "Shortwave radiation (W/m²)", "Weather feature"],
    ["heat_index_c", "Calculated Heat Index (°C)", "Derived feature"],
    ["heat_index_category", "Heat Index target category", "TARGET"],
], columns=["column", "description", "role"])

target_definition = pd.DataFrame([
    ["LOW", "< 26.7 °C"],
    ["MODERATE", "26.7–<32.2 °C"],
    ["HIGH", "32.2–<40.6 °C"],
    ["VERY_HIGH", "40.6–<54.4 °C"],
    ["EXTREME", ">=54.4 °C"],
], columns=["category", "heat_index_range_c"])

readme = pd.DataFrame([
    ["Purpose", "HeatSentinel ML handoff workbook"],
    ["Weather period", "2022–2025"],
    ["Environment cells", f"{len(static):,}"],
    ["Weather/target rows", f"{len(target):,}"],
    ["Target", "heat_index_category"],
    ["Important", "Weather source resolution is approximately 10–25 km; it is linked to 300m environmental cells and is not 300m weather."],
    ["Important", "Validate the Heat Index calculation and category thresholds before operational deployment."],
])

with pd.ExcelWriter(XLSX, engine="openpyxl", mode="w") as writer:
    static.to_excel(writer, sheet_name="ML_STATIC_300M", index=False)
    mapping.to_excel(writer, sheet_name="GRID_MAPPING", index=False)
    data_dictionary.to_excel(writer, sheet_name="DATA_DICTIONARY", index=False)
    target_definition.to_excel(writer, sheet_name="TARGET_DEFINITION", index=False)
    readme.to_excel(writer, sheet_name="README", index=False)
    dist.to_excel(writer, sheet_name="TARGET_DISTRIBUTION", index=False)
    rules.to_excel(writer, sheet_name="TARGET_RULES", index=False)
    notes.to_excel(writer, sheet_name="ML_TRAINING_NOTES", index=False)

print(f"Done: {XLSX}")
print(f"Size: {XLSX.stat().st_size / 1024 / 1024:.2f} MB")
print("\nTarget distribution:")
print(dist.to_string(index=False))
