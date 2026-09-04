"""
================================================================================
HEAT RISK CLASSIFICATION - RUNNABLE IMPLEMENTATION
Follows the STEP 1-9 structure of the pseudocode, with the bugs fixed.
================================================================================

    pip install requests pandas numpy scikit-learn joblib pythermalcomfort
    python heat_pipeline.py

With no arguments it fetches data first (Open-Meteo, no API key), then trains.
If heat_raw_hourly.csv already exists it skips the fetch.

FIXES APPLIED TO THE PSEUDOCODE  (each marked [FIX n] at the site)

 1. Label is the category H days AHEAD, not the same day. In the original,
    'target' was a threshold on heat_index_mean while heat_index_mean was also
    in FEATURES, so the model just re-derived the if-else. Set HORIZON = 0 to
    reproduce the original behaviour and watch accuracy jump to ~1.0; that
    number is the leak, not skill.
 2. Threshold bands. Original used thresholds['MODERATE'] (32) as the first
    cut, so thresholds['LOW'] (27) was never referenced and every band sat one
    slot too high. VERY_HIGH was also assigned at >=47 then immediately
    overwritten by EXTREME at >=47, making it unreachable. Now uses the NWS
    heat index bands: 27 / 32 / 41 / 54 degC.
 3. Rolling feature names. The loop wrote 'temperature_mean_mean_3' but
    FEATURES asked for 'temperature_mean_3'; 'temperature_max_3' and
    'temperature_max_7' were never created at all. FEATURES is now derived
    from the dataframe instead of hand-listed, so it cannot drift again.
 4. Split is by DATE, not by row fraction. A 70/15/15 row split puts the warm
    months in train and leaves winter in test, so the model is never evaluated
    on a hot day.
 5. get_dummies in predict_future only emits seasons present in the 19-day
    window, which KeyErrors on the missing columns. Now reindexed against the
    training feature list.
 6. Label target uses daily MAX heat index, not daily mean. Heat thresholds
    are defined on instantaneous conditions; a daily mean washes out the
    afternoon peak that actually causes harm.
 7. Metrics. Accuracy on this problem is a trap - "never hot" scores >90%.
    Added POD / FAR / CSI plus persistence and climatology baselines.
 8. Heat index uses the full NWS algorithm. Bare Rothfusz is invalid below
    about 27 degC and returns nonsense there.
"""

import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
import joblib

from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.metrics import (accuracy_score, precision_score, recall_score,
                             f1_score, confusion_matrix, classification_report)

warnings.filterwarnings("ignore")

# ============================== CONFIG ======================================

RAW_CSV = "heat_raw_hourly.csv"

HORIZON = 3               # [FIX 1] forecast lead time in days. 0 = original (leaky)
TRAIN_END = "2021-12-31"  # [FIX 4] split by date so every split spans a summer
VAL_END = "2023-12-31"

RISK_LEVELS = ["LOW", "MODERATE", "HIGH", "VERY_HIGH", "EXTREME"]
ALERT_FROM = 2            # skill scores treat "HIGH or above" as the event

# [FIX 2] NWS heat index category edges in degC. https://www.weather.gov/safety/heat-index
HEAT_INDEX_EDGES = [27.0, 32.0, 41.0, 54.0]

DO_TUNING = False         # STEP 6 is slow; turn on once the rest works

CITIES = {                # matches the cities in transit_stops.csv
    "Delhi": (28.6139, 77.2090),
    "Bengaluru": (12.9716, 77.5946),
    "Kochi": (9.9312, 76.2673),
}
START_YEAR, END_YEAR = 2015, 2025


# ========================= STEP 0: FETCH DATA ===============================

def fetch_data(path=RAW_CSV):
    """Open-Meteo ERA5 archive. No API key. CC BY 4.0."""
    import requests
    session = requests.Session()
    frames = []
    for city, (lat, lon) in CITIES.items():
        for year in range(START_YEAR, END_YEAR + 1):
            params = {
                "latitude": lat, "longitude": lon,
                "start_date": f"{year}-01-01", "end_date": f"{year}-12-31",
                "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,shortwave_radiation",
                "timezone": "Asia/Kolkata",
                "wind_speed_unit": "ms",
            }
            try:
                r = session.get("https://archive-api.open-meteo.com/v1/archive",
                                params=params, timeout=120)
                r.raise_for_status()
                h = r.json()["hourly"]
            except Exception as exc:
                print(f"  !! {city} {year}: {exc}")
                continue
            frames.append(pd.DataFrame({
                "city": city,
                "timestamp": pd.to_datetime(h["time"]),
                "temperature": h["temperature_2m"],
                "humidity": h["relative_humidity_2m"],
                "wind_speed": h["wind_speed_10m"],
                "solar_radiation": h["shortwave_radiation"],
            }))
            print(f"  {city} {year}: {len(frames[-1])} rows")
            time.sleep(1.0)

    df = pd.concat(frames, ignore_index=True)
    df.to_csv(path, index=False)
    print(f"wrote {path}  ({len(df):,} rows)")
    return df


# ======================= THERMAL INDEX FUNCTIONS ============================

def calculate_heat_index(t_c, rh):
    """[FIX 8] Full NWS algorithm: simple average below ~80F, Rothfusz above,
    with the low-RH and high-RH corrections."""
    t = np.asarray(t_c, dtype=float) * 9 / 5 + 32
    rh = np.asarray(rh, dtype=float)

    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    hi = (simple + t) / 2

    roth = (-42.379 + 2.04901523 * t + 10.14333127 * rh
            - 0.22475541 * t * rh - 6.83783e-3 * t * t
            - 5.481717e-2 * rh * rh + 1.22874e-3 * t * t * rh
            + 8.5282e-4 * t * rh * rh - 1.99e-6 * t * t * rh * rh)

    low = (rh < 13) & (t >= 80) & (t <= 112)
    roth = np.where(low, roth - ((13 - rh) / 4)
                    * np.sqrt(np.clip((17 - np.abs(t - 95)) / 17, 0, None)), roth)
    high = (rh > 85) & (t >= 80) & (t <= 87)
    roth = np.where(high, roth + ((rh - 85) / 10) * ((87 - t) / 5), roth)

    return (np.where(hi >= 80, roth, hi) - 32) * 5 / 9


def calculate_wbgt(t_c, rh):
    """Shade WBGT = 0.7*Tw + 0.3*Ta, Tw from Stull (2011). The outdoor form
    needs a black globe temperature, which needs a radiation model - not
    faked here."""
    t = np.asarray(t_c, dtype=float)
    r = np.asarray(rh, dtype=float)
    tw = (t * np.arctan(0.151977 * np.sqrt(r + 8.313659))
          + np.arctan(t + r) - np.arctan(r - 1.676331)
          + 0.00391838 * r ** 1.5 * np.arctan(0.023101 * r) - 4.686035)
    return 0.7 * tw + 0.3 * t


def calculate_utci(t_c, rh, wind_ms):
    """Real UTCI (Brode et al. 2012 polynomial) via pythermalcomfort, with
    mean radiant temperature = air temperature, i.e. shade."""
    try:
        from pythermalcomfort.models import utci
    except ImportError:
        return np.full(len(np.asarray(t_c)), np.nan)
    t = np.asarray(t_c, dtype=float)
    res = utci(tdb=t, tr=t, v=np.clip(np.asarray(wind_ms, dtype=float), 0.5, 17.0),
               rh=np.asarray(rh, dtype=float), limit_inputs=False)
    return np.asarray(res.utci, dtype=float)


# =================== STEP 1: LOAD AND PREPROCESS ============================

def load_and_preprocess(file_path):
    df = pd.read_csv(file_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if "city" not in df.columns:
        df["city"] = "default"
    df = df.sort_values(["city", "timestamp"]).drop_duplicates(subset=["city", "timestamp"])

    for col, default in [("wind_speed", 1.0), ("solar_radiation", 0.0)]:
        if col not in df.columns:
            df[col] = default

    df["temperature"] = df["temperature"].clip(-10, 55)
    df["humidity"] = df["humidity"].clip(1, 100)
    df[["temperature", "humidity", "wind_speed", "solar_radiation"]] = (
        df.groupby("city")[["temperature", "humidity", "wind_speed", "solar_radiation"]]
          .transform(lambda s: s.interpolate(limit_direction="both")))

    df["heat_index"] = calculate_heat_index(df["temperature"], df["humidity"])
    df["wbgt"] = calculate_wbgt(df["temperature"], df["humidity"])
    df["utci"] = calculate_utci(df["temperature"], df["humidity"], df["wind_speed"])
    return df


# ==================== STEP 2: FEATURE ENGINEERING ===========================

def _categorise(hi_max):
    """[FIX 2] Bands applied left to right, no overwrite bug."""
    return np.digitize(np.asarray(hi_max, dtype=float), HEAT_INDEX_EDGES)


def engineer_features(df, horizon=HORIZON, for_prediction=False):
    # 2.1 hourly -> daily. Indices are computed hourly then aggregated, which
    # is the right order: max of an index != index of the maxima.
    df = df.copy()
    df["date"] = df["timestamp"].dt.floor("D")
    daily = df.groupby(["city", "date"]).agg(
        temperature_mean=("temperature", "mean"),
        temperature_max=("temperature", "max"),
        temperature_min=("temperature", "min"),
        humidity_mean=("humidity", "mean"),
        humidity_min=("humidity", "min"),
        heat_index_mean=("heat_index", "mean"),
        heat_index_max=("heat_index", "max"),   # [FIX 6] label is built on max
        wbgt_max=("wbgt", "max"),
        utci_max=("utci", "max"),
        wind_speed_mean=("wind_speed", "mean"),
        solar_radiation_mean=("solar_radiation", "mean"),
        solar_radiation_max=("solar_radiation", "max"),
        n_hours=("temperature", "size"),
    ).reset_index()
    daily = daily[daily["n_hours"] >= 20].drop(columns="n_hours")

    out = []
    for city, g in daily.groupby("city", sort=False):
        g = g.sort_values("date").reset_index(drop=True)

        # 2.2 time features
        doy = g["date"].dt.dayofyear
        g["month"] = g["date"].dt.month
        g["day_sin"] = np.sin(2 * np.pi * doy / 365.25)
        g["day_cos"] = np.cos(2 * np.pi * doy / 365.25)
        g["month_sin"] = np.sin(2 * np.pi * g["month"] / 12)
        g["month_cos"] = np.cos(2 * np.pi * g["month"] / 12)
        for name, months in [("PRE_MONSOON", [3, 4, 5]), ("MONSOON", [6, 7, 8, 9]),
                             ("POST_MONSOON", [10, 11]), ("WINTER", [12, 1, 2])]:
            # [FIX 5] explicit columns instead of get_dummies, so a short
            # prediction window can never produce a missing season column
            g[f"season_{name}"] = g["month"].isin(months).astype(int)

        # today's category: a feature, and the persistence baseline
        g["cat_today"] = _categorise(g["heat_index_max"])

        # 2.3 lags
        for col in ["temperature_max", "humidity_mean", "heat_index_max",
                    "utci_max", "wbgt_max"]:
            for lag in [1, 2, 3, 7]:
                g[f"{col}_lag_{lag}"] = g[col].shift(lag)

        # 2.4 rolling  [FIX 3] names generated once, FEATURES derived from them
        for col in ["temperature_max", "humidity_mean", "heat_index_max", "utci_max"]:
            for w in [3, 7, 14]:
                r = g[col].rolling(w, min_periods=w)
                g[f"{col}_rmean_{w}"] = r.mean()
                g[f"{col}_rmax_{w}"] = r.max()
                g[f"{col}_rstd_{w}"] = r.std()

        # 2.5 interactions and physiological accumulation
        g["temp_humidity"] = g["temperature_mean"] * g["humidity_mean"] / 100
        g["temp_change_1d"] = g["temperature_max"].diff(1)
        g["temp_change_3d"] = g["temperature_max"].diff(3)
        g["heat_index_change"] = g["heat_index_max"].diff(1)
        g["diurnal_range"] = g["temperature_max"] - g["temperature_min"]
        # overnight non-recovery: warm nights are what stop the body cooling
        g["tmin_anomaly_7"] = (g["temperature_min"]
                               - g["temperature_min"].rolling(7, min_periods=7).mean())
        hot = (g["cat_today"] >= ALERT_FROM).astype(int).values
        streak = np.zeros(len(hot), dtype=int)
        for i in range(len(hot)):
            streak[i] = streak[i - 1] + 1 if hot[i] and i else hot[i]
        g["hot_streak"] = streak

        # 2.6 target  [FIX 1] category HORIZON days ahead, built from data
        # that is strictly in the future relative to every feature above
        if not for_prediction:
            g["target"] = g["cat_today"].shift(-horizon) if horizon > 0 else g["cat_today"]
            if horizon > 0:
                ahead = g["date"].shift(-horizon)
                g.loc[(ahead - g["date"]).dt.days != horizon, "target"] = np.nan

        out.append(g)

    df = pd.concat(out, ignore_index=True)
    if not for_prediction:
        df = df.dropna(subset=["target"])
        df["target"] = df["target"].astype(int)
    return df.dropna(subset=[c for c in df.columns if "_rmean_14" in c])


def get_feature_columns(df):
    """[FIX 3] derived, never hand-listed."""
    drop = {"city", "date", "target", "month"}
    return [c for c in df.columns if c not in drop and pd.api.types.is_numeric_dtype(df[c])]


# ======================== STEP 3: SPLIT DATA ================================

def split_data(df, train_end=TRAIN_END, val_end=VAL_END):
    """[FIX 4] by date, so each split contains complete pre-monsoon seasons."""
    features = get_feature_columns(df)
    tr = df[df["date"] <= train_end]
    va = df[(df["date"] > train_end) & (df["date"] <= val_end)]
    te = df[df["date"] > val_end]

    print(f"\nsplits (target = risk category at t+{HORIZON}d)")
    for name, part in [("train", tr), ("val", va), ("test", te)]:
        c = part["target"].value_counts().reindex(range(5), fill_value=0)
        print(f"  {name:5s} n={len(part):5d}  " +
              "  ".join(f"{RISK_LEVELS[i]}={c[i]}" for i in range(5)))
        if len(part) and (part["target"] >= ALERT_FROM).sum() == 0:
            print(f"    WARNING: no HIGH+ days in {name} - move the split dates")
    return (tr[features], tr["target"], va[features], va["target"],
            te[features], te["target"], features, tr, va, te)


# ========================== STEP 4: SCALING =================================

def scale_data(X_train, X_val, X_test):
    """Kept for parity with the spec. Tree ensembles do not need it; it is a
    no-op for them and only matters if you swap in an SVM or a neural net."""
    scaler = StandardScaler()
    return (scaler.fit_transform(X_train), scaler.transform(X_val),
            scaler.transform(X_test), scaler)


# ======================= STEP 5: TRAIN MODELS ===============================

def skill_scores(y_true, y_pred, threshold=ALERT_FROM):
    """[FIX 7] Forecast verification for the event 'category >= HIGH'.
    POD = share of real heat events caught. FAR = share of alerts that were
    wrong. CSI combines both. These are what a met agency actually reports."""
    obs = np.asarray(y_true) >= threshold
    fct = np.asarray(y_pred) >= threshold
    h = int((obs & fct).sum()); m = int((obs & ~fct).sum()); f = int((~obs & fct).sum())
    return {"hits": h, "misses": m, "false_alarms": f,
            "POD": h / (h + m) if h + m else np.nan,
            "FAR": f / (h + f) if h + f else np.nan,
            "CSI": h / (h + m + f) if h + m + f else np.nan}


def _line(name, y_true, y_pred):
    s = skill_scores(y_true, y_pred)
    print(f"  {name:24s} macroF1 {f1_score(y_true, y_pred, average='macro', zero_division=0):.3f}"
          f"  acc {accuracy_score(y_true, y_pred):.3f}"
          f"  POD {s['POD']:.3f}  FAR {s['FAR']:.3f}  CSI {s['CSI']:.3f}"
          f"  (h{s['hits']} m{s['misses']} f{s['false_alarms']})")
    return s


def climatology_baseline(train_df, target_df):
    t = train_df.copy()
    t["doy"] = t["date"].dt.dayofyear
    lookup = {}
    for d in range(1, 367):
        w = t[(t["doy"] >= d - 7) & (t["doy"] <= d + 7)]
        lookup[d] = int(w["target"].mode().iloc[0]) if len(w) else 0
    return target_df["date"].dt.dayofyear.map(lookup).fillna(0).astype(int).values


def train_models(X_train, y_train, X_val, y_val, train_df, val_df):
    print("\nbaselines on validation")
    _line("persistence", y_val, val_df["cat_today"])
    _line("climatology", y_val, climatology_baseline(train_df, val_df))

    models = {
        "RandomForest": RandomForestClassifier(
            n_estimators=500, min_samples_leaf=2,
            class_weight="balanced_subsample", n_jobs=-1, random_state=42),
        "HistGradientBoosting": HistGradientBoostingClassifier(
            max_iter=400, learning_rate=0.06, l2_regularization=1.0, random_state=42),
    }
    try:
        from xgboost import XGBClassifier
        models["XGBoost"] = XGBClassifier(
            n_estimators=400, learning_rate=0.05, max_depth=7, subsample=0.8,
            colsample_bytree=0.8, objective="multi:softprob", num_class=5,
            random_state=42, verbosity=0)
    except ImportError:
        pass
    try:
        from lightgbm import LGBMClassifier
        models["LightGBM"] = LGBMClassifier(
            n_estimators=500, learning_rate=0.05, num_leaves=31,
            class_weight="balanced", random_state=42, verbose=-1)
    except ImportError:
        pass

    print("\nmodels on validation")
    best, best_score, best_name, results = None, -1, None, {}
    for name, model in models.items():
        model.fit(X_train, y_train)
        pred = model.predict(X_val)
        s = _line(name, y_val, pred)
        results[name] = s
        # selected on CSI: a warning system is judged on catching events
        # without crying wolf, not on overall accuracy
        if s["CSI"] == s["CSI"] and s["CSI"] > best_score:
            best, best_score, best_name = model, s["CSI"], name

    print(f"\nselected {best_name} (val CSI {best_score:.3f})")
    return best, best_name, results


# ==================== STEP 6: HYPERPARAMETER TUNING =========================

def tune_hyperparameters(X_train, y_train):
    """TimeSeriesSplit, not plain cv=3 - random folds leak future into past."""
    grid = {"n_estimators": [200, 400], "max_depth": [10, 20, None],
            "min_samples_leaf": [1, 2, 4]}
    gs = GridSearchCV(RandomForestClassifier(class_weight="balanced_subsample",
                                             n_jobs=-1, random_state=42),
                      grid, cv=TimeSeriesSplit(n_splits=3),
                      scoring="f1_macro", n_jobs=-1)
    gs.fit(X_train, y_train)
    print(f"  best params: {gs.best_params_}  cv f1_macro {gs.best_score_:.3f}")
    return gs.best_estimator_


# ====================== STEP 7: EVALUATE ON TEST ============================

def evaluate_model(model, X_test, y_test, test_df, name="model"):
    pred = model.predict(X_test)
    print("\nheld-out test")
    _line("persistence", y_test, test_df["cat_today"])
    _line(name, y_test, pred)
    print("\n" + classification_report(y_test, pred, labels=range(5),
                                       target_names=RISK_LEVELS, zero_division=0))
    print("confusion matrix (rows observed, cols predicted)")
    print(pd.DataFrame(confusion_matrix(y_test, pred, labels=range(5)),
                       index=RISK_LEVELS, columns=RISK_LEVELS))
    return {"accuracy": accuracy_score(y_test, pred),
            "precision": precision_score(y_test, pred, average="weighted", zero_division=0),
            "recall": recall_score(y_test, pred, average="weighted", zero_division=0),
            "f1": f1_score(y_test, pred, average="weighted", zero_division=0),
            **skill_scores(y_test, pred)}


# ====================== STEP 8: PREDICT FUTURE ==============================

def predict_future(history_df, model, feature_cols, horizon=HORIZON):
    """history_df = the last ~30 days of hourly observations. Features are
    built from history only; the model projects HORIZON days forward. No
    forecast weather file needed, which is the point of a lead-time model."""
    feats = engineer_features(history_df, for_prediction=True)
    latest = feats.sort_values("date").groupby("city").tail(1)
    # [FIX 5] align to the training feature list; fill anything absent
    X = latest.reindex(columns=feature_cols, fill_value=0.0)
    pred = model.predict(X)
    proba = model.predict_proba(X)
    rows = []
    for i, (_, row) in enumerate(latest.iterrows()):
        rows.append({
            "city": row["city"],
            "issued_for": row["date"] + pd.Timedelta(days=horizon),
            "based_on": row["date"],
            "predicted_category": RISK_LEVELS[int(pred[i])],
            "confidence": float(proba[i][int(pred[i])]),
            "current_heat_index_max": round(float(row["heat_index_max"]), 1),
            "current_category": RISK_LEVELS[int(row["cat_today"])],
        })
    return pd.DataFrame(rows)


# ========================= STEP 9: MAIN =====================================

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else RAW_CSV
    if not os.path.exists(path):
        print(f"{path} not found - fetching from Open-Meteo")
        fetch_data(path)

    print(f"\nloading {path}")
    raw = load_and_preprocess(path)
    print(f"  {len(raw):,} hourly rows, {raw['city'].nunique()} cities, "
          f"{raw['timestamp'].min().date()} to {raw['timestamp'].max().date()}")

    df = engineer_features(raw)
    Xtr, ytr, Xva, yva, Xte, yte, features, tr, va, te = split_data(df)
    print(f"\n{len(features)} features, {len(df):,} labelled rows")

    if HORIZON == 0:
        print("\n*** HORIZON=0: the label is the same day as the features. "
              "Whatever accuracy prints below is leakage, not skill. ***")

    # scaling kept for spec parity; trees ignore it
    Xtr_s, Xva_s, Xte_s, scaler = scale_data(Xtr, Xva, Xte)

    model, name, _ = train_models(Xtr, ytr, Xva, yva, tr, va)

    if DO_TUNING:
        print("\ntuning RandomForest")
        tuned = tune_hyperparameters(Xtr, ytr)
        if skill_scores(yva, tuned.predict(Xva))["CSI"] > skill_scores(yva, model.predict(Xva))["CSI"]:
            model, name = tuned, "RandomForest (tuned)"
            print("  tuned model wins")

    metrics = evaluate_model(model, Xte, yte, te, name)

    if hasattr(model, "feature_importances_"):
        imp = pd.Series(model.feature_importances_, index=features).sort_values(ascending=False)
        print("\ntop 15 features")
        print(imp.head(15).round(4).to_string())

    joblib.dump({"model": model, "scaler": scaler, "features": features,
                 "risk_levels": RISK_LEVELS, "horizon_days": HORIZON,
                 "heat_index_edges": HEAT_INDEX_EDGES, "test_metrics": metrics},
                "heat_model.joblib")
    print("\nsaved heat_model.joblib")

    # live forecast from the tail of the record
    recent = raw[raw["timestamp"] >= raw["timestamp"].max() - pd.Timedelta(days=40)]
    fc = predict_future(recent, model, features)
    fc.to_csv("future_risk_predictions.csv", index=False)
    print(f"\nforecast (+{HORIZON}d)")
    print(fc.to_string(index=False))


if __name__ == "__main__":
    main()
