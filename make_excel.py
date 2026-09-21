import pandas as pd
from pathlib import Path

SRC = Path("backend/data/phase2/weather/ncr_weather_2015_2025.parquet")
df = pd.read_parquet(SRC)
df["timestamp"] = df["timestamp"].dt.tz_localize(None)   # Excel tz-aware time support nahi karta

# Sheet 1: Delhi ke sabse paas wale weather point ka hourly data
d2 = (df["latitude"] - 28.61) ** 2 + (df["longitude"] - 77.21) ** 2
p = df.loc[d2.idxmin(), ["latitude", "longitude"]]
hourly = df[(df.latitude == p.latitude) & (df.longitude == p.longitude)]

# Sheet 2: saare NCR points ka DAILY summary (Excel me fit hota hai)
df["date"] = df["timestamp"].dt.date
daily = df.groupby(["date", "latitude", "longitude"], as_index=False).agg(
    temp_max=("temperature_2m", "max"), temp_mean=("temperature_2m", "mean"),
    humidity_mean=("relative_humidity_2m", "mean"),
    wind_mean=("wind_speed_10m", "mean"),
    radiation_max=("shortwave_radiation", "max"))

print("hourly rows:", len(hourly), "| daily rows:", len(daily))
if len(daily) > 1_000_000:
    raise SystemExit("Daily sheet Excel limit se bada hai - --start-year chhota karo.")
with pd.ExcelWriter("ncr_weather_2022_2025.xlsx") as w:
    hourly.to_excel(w, sheet_name="hourly_delhi_point", index=False)
    daily.to_excel(w, sheet_name="daily_all_points", index=False)
print("saved ncr_weather_2022_2025.xlsx")
