
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent
ENV = ROOT / "backend" / "data" / "phase1" / "heat_environment_300m.csv"
WEATHER = ROOT / "backend" / "data" / "phase2" / "weather" / "ncr_weather_2015_2025.parquet"
WEATHER_POINTS = ROOT / "backend" / "data" / "phase2" / "weather" / "weather_grid_points.csv"
OUT = ROOT / "backend" / "data" / "phase2" / "ml_handoff"
OUT.mkdir(parents=True, exist_ok=True)

print("="*70)
print("HEATSENTINEL ML HANDOFF BUILDER")
print("="*70)

for p in [ENV, WEATHER, WEATHER_POINTS]:
    if not p.exists():
        raise FileNotFoundError(f"Missing required file: {p}")

print("\n[1/6] Loading 300m environment dataset...")
env = pd.read_csv(ENV)
required_env = [
    "cell_id","lst_mean_c","lst_median_c","lst_min_c","lst_max_c","lst_std_c",
    "lst_observations","ndvi_mean","ndvi_median","ndvi_min","ndvi_max","ndvi_std",
    "ndvi_observations","land_cover_class","land_cover_fraction","land_cover_name",
    "elevation_mean_m","elevation_min_m","elevation_max_m"
]
missing = [c for c in required_env if c not in env.columns]
if missing:
    raise ValueError(f"Environment columns missing: {missing}")

# The environment CSV has no coordinates in the current schema.
# Derive 300m cell centroids from the Phase-1 GPKG.
gpkg = ROOT / "backend" / "data" / "phase1" / "heat_environment_300m.gpkg"
if not gpkg.exists():
    raise FileNotFoundError(f"Missing GPKG needed for cell coordinates: {gpkg}")

import geopandas as gpd
g = gpd.read_file(gpkg)
if "cell_id" not in g.columns or "geometry" not in g.columns:
    raise ValueError("Phase-1 GPKG must contain cell_id and geometry.")

# Compute centroids in a metric CRS first, then transform to WGS84.
g = g[["cell_id","geometry"]].copy()
if g.crs is None:
    raise ValueError("Phase-1 GPKG has no CRS.")
g_metric = g.to_crs(6933)
cent = g_metric.geometry.centroid.to_crs(4326)
coords = pd.DataFrame({
    "cell_id": g_metric["cell_id"].astype(str),
    "latitude": cent.y.to_numpy(),
    "longitude": cent.x.to_numpy()
})
env["cell_id"] = env["cell_id"].astype(str)
env = env.merge(coords, on="cell_id", how="left", validate="one_to_one")
if env[["latitude","longitude"]].isna().any().any():
    raise ValueError("Some environment cells could not be assigned coordinates.")

print(f"  Environment cells: {len(env):,}")

print("[2/6] Loading weather points and building nearest-cell mapping...")
wp = pd.read_csv(WEATHER_POINTS)
wp_lat = next((c for c in ["latitude","lat"] if c in wp.columns), None)
wp_lon = next((c for c in ["longitude","lon"] if c in wp.columns), None)
if wp_lat is None or wp_lon is None:
    raise ValueError(f"Weather point coordinates not found. Columns: {wp.columns.tolist()}")

wp = wp[[wp_lat, wp_lon]].drop_duplicates().reset_index(drop=True)
wp["weather_point_id"] = [f"WP_{i+1:03d}" for i in range(len(wp))]

def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dphi/2)**2 + np.cos(p1)*np.cos(p2)*np.sin(dl/2)**2
    return 2*r*np.arcsin(np.sqrt(a))

wlat = wp[wp_lat].to_numpy(dtype=float)
wlon = wp[wp_lon].to_numpy(dtype=float)
clat = env["latitude"].to_numpy(dtype=float)
clon = env["longitude"].to_numpy(dtype=float)

nearest_idx = np.empty(len(env), dtype=np.int32)
nearest_dist = np.empty(len(env), dtype=np.float32)
chunk = 25000
for start in range(0, len(env), chunk):
    end = min(start + chunk, len(env))
    d = haversine_km(
        clat[start:end, None], clon[start:end, None],
        wlat[None, :], wlon[None, :]
    )
    idx = np.argmin(d, axis=1)
    nearest_idx[start:end] = idx
    nearest_dist[start:end] = d[np.arange(end-start), idx]

mapping = pd.DataFrame({
    "cell_id": env["cell_id"].values,
    "latitude": clat,
    "longitude": clon,
    "weather_point_id": wp.iloc[nearest_idx]["weather_point_id"].to_numpy(),
    "weather_latitude": wlat[nearest_idx],
    "weather_longitude": wlon[nearest_idx],
    "nearest_weather_distance_km": nearest_dist
})
mapping.to_parquet(OUT / "03_weather_to_300m_mapping.parquet", index=False)
mapping.to_csv(OUT / "03_weather_to_300m_mapping.csv", index=False)

print(f"  Mapping rows: {len(mapping):,}")

print("[3/6] Creating static ML feature table...")
static = env[required_env + ["latitude","longitude"]].copy()
static = static.merge(
    mapping[["cell_id","weather_point_id","nearest_weather_distance_km"]],
    on="cell_id", how="left", validate="one_to_one"
)
static.to_parquet(OUT / "01_environment_300m_with_weather_link.parquet", index=False)
static.to_csv(OUT / "01_environment_300m_with_weather_link.csv", index=False)

print("[4/6] Preparing 2022–2025 weather dataset...")
weather = pd.read_parquet(WEATHER)
weather["timestamp"] = pd.to_datetime(weather["timestamp"], errors="coerce")
if weather["timestamp"].isna().any():
    raise ValueError("Weather dataset contains invalid timestamps.")

# Attach stable weather point IDs.
wp2 = wp.rename(columns={wp_lat:"latitude", wp_lon:"longitude"})
weather["latitude"] = pd.to_numeric(weather["latitude"], errors="coerce")
weather["longitude"] = pd.to_numeric(weather["longitude"], errors="coerce")
weather = weather.merge(
    wp2[["latitude","longitude","weather_point_id"]],
    on=["latitude","longitude"], how="left"
)
if weather["weather_point_id"].isna().any():
    raise ValueError("Could not assign weather_point_id to every weather row.")

weather.to_parquet(OUT / "02_weather_2022_2025_with_point_id.parquet", index=False)

print("[5/6] Calculating thermal features at weather-point/hour level...")
T = pd.to_numeric(weather["temperature_2m"], errors="coerce")
RH = pd.to_numeric(weather["relative_humidity_2m"], errors="coerce")
W = pd.to_numeric(weather["wind_speed_10m"], errors="coerce")
SW = pd.to_numeric(weather["shortwave_radiation"], errors="coerce")

# Heat Index: Rothfusz-style approximation for hot/humid conditions.
Tf = T * 9/5 + 32
mask = (Tf >= 80) & (RH >= 40)
hi_f = (
    -42.379 + 2.04901523*Tf + 10.14333127*RH
    - 0.22475541*Tf*RH - 0.00683783*Tf**2
    - 0.05481717*RH**2 + 0.00122874*Tf**2*RH
    + 0.00085282*Tf*RH**2 - 0.00000199*Tf**2*RH**2
)
heat_index = pd.Series(np.where(mask, (hi_f - 32)*5/9, T), index=weather.index)

# Stull wet-bulb approximation + simple shade-WBGT proxy.
twb = (
    T*np.arctan(0.151977*np.sqrt(RH+8.313659))
    + np.arctan(T+RH)
    - np.arctan(RH-1.676331)
    + 0.00391838*(RH**1.5)*np.arctan(0.023101*RH)
    - 4.686035
)
wbgt_proxy = 0.7*twb + 0.3*T

thermal = weather[["timestamp","latitude","longitude","weather_point_id"]].copy()
thermal["temperature_2m_c"] = T
thermal["relative_humidity_pct"] = RH
thermal["wind_speed_10m_ms"] = W
thermal["shortwave_radiation_wm2"] = SW
thermal["heat_index_c"] = heat_index
thermal["wbgt_shade_proxy_c"] = wbgt_proxy
thermal["heat_index_note"] = "Rothfusz-style approximation; validate before operational use"
thermal["wbgt_note"] = "Approximate shade WBGT proxy; not full globe/wet-bulb/radiant WBGT"
thermal.to_parquet(OUT / "04_thermal_features_point_hour.parquet", index=False)

print("[6/6] Creating Excel handoff workbook...")
xlsx = OUT / "HeatSentinel_ML_Handoff.xlsx"

data_dictionary = pd.DataFrame([
    ["cell_id","300m NCR cell identifier","Spatial key"],
    ["lst_mean_c","Mean land surface temperature, °C","Environment feature"],
    ["ndvi_mean","Mean NDVI","Vegetation feature"],
    ["land_cover_class","Land-cover class","Categorical feature"],
    ["elevation_mean_m","Mean elevation, m","Terrain feature"],
    ["weather_point_id","Nearest weather point ID","Join key"],
    ["nearest_weather_distance_km","Distance to nearest weather point, km","Spatial-quality feature"],
    ["timestamp","Hourly weather timestamp, Asia/Kolkata","Temporal key"],
    ["temperature_2m","2m air temperature, °C","Weather feature"],
    ["relative_humidity_2m","2m relative humidity, %","Weather feature"],
    ["wind_speed_10m","10m wind speed, m/s","Weather feature"],
    ["shortwave_radiation","Shortwave radiation, W/m²","Weather feature"],
    ["heat_index_c","Approximate Heat Index, °C","Derived thermal feature"],
    ["wbgt_shade_proxy_c","Approximate shade WBGT proxy, °C","Derived thermal feature; validate"],
], columns=["column","description","role"])

target_definition = pd.DataFrame([
    ["TARGET STATUS","NOT GENERATED","No artificial labels created by this script."],
    ["Suggested target","Heat-risk class","ML owner must define scientifically and document thresholds/source."],
    ["Potential classes","LOW / MODERATE / HIGH / VERY_HIGH / EXTREME","Use only after validated target definition."],
    ["Data period","2022-01-01 to 2025-12-31","Current downloaded weather period."],
    ["Spatial resolution","300m environment; ~10–25 km weather","Weather is linked to nearest point, not true 300m weather."],
], columns=["item","value","note"])

readme = pd.DataFrame([
    ["Purpose","HeatSentinel ML handoff; data preparation only"],
    ["Training","Not performed by this script"],
    ["Environment source",str(ENV.relative_to(ROOT))],
    ["Weather source",str(WEATHER.relative_to(ROOT))],
    ["Weather period","2022–2025"],
    ["300m cells",len(env)],
    ["Weather rows",len(weather)],
    ["Weather points",len(wp)],
    ["Important","Thermal features are approximate and should be validated before operational use."],
    ["Important","No target labels are fabricated."],
], columns=["item","value"])

with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
    # This sheet is under Excel's 1,048,576-row limit.
    static.to_excel(writer, sheet_name="ML_STATIC_300M", index=False)
    mapping.to_excel(writer, sheet_name="GRID_MAPPING", index=False)
    data_dictionary.to_excel(writer, sheet_name="DATA_DICTIONARY", index=False)
    target_definition.to_excel(writer, sheet_name="TARGET_DEFINITION", index=False)
    readme.to_excel(writer, sheet_name="README", index=False)

print("\n" + "="*70)
print("DONE")
print("="*70)
print(f"Output folder: {OUT}")
for p in sorted(OUT.iterdir()):
    if p.is_file():
        print(f"  {p.name:48s} {p.stat().st_size/1024/1024:8.2f} MB")
print("\nFull hourly weather/thermal data stays in Parquet because Excel has a 1,048,576-row sheet limit.")
