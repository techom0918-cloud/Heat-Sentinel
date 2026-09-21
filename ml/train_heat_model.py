"""
HeatSentinel -- Heat Index Category classifier (XGBoost / LightGBM / Random Forest).

Run from the repo root with ONE command:

    python ml/train_heat_model.py

Optional (faster trial run on a laptop, uses a random fraction of rows
in EVERY split -- the chronological split itself is unchanged):

    python ml/train_heat_model.py --sample-frac 0.25

Required packages:

    pip install pandas pyarrow numpy scikit-learn xgboost lightgbm matplotlib joblib shap

IMPORTANT HONESTY NOTES (read before presenting results):
  * heat_index_category is computed from heat_index_c, and heat_index_c
    is itself a formula of air temperature + relative humidity. So a
    model given temperature + humidity is largely RE-LEARNING THAT
    FORMULA -- very high scores are expected and are NOT evidence of
    forecasting skill. This is a baseline classifier, not a forecaster.
  * Weather comes from ~10-25 km grid points (118 points). The
    environmental features (LST, NDVI, land cover, elevation) come
    from the 300m grid but are SUMMARISED per weather point here. The
    predictions are therefore at weather-point level, not 300m.
  * EXTREME (heat index >= 54.4 C) has ZERO samples in 2022-2025, so
    the model cannot learn or predict it.
"""

import argparse
import json
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

from evaluate_model import (
    compute_metrics, save_confusion_matrix_plot, text_report,
)

# ============================================================
# SECTION 0 -- PATHS AND SETTINGS
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = (REPO_ROOT / "backend" / "data" / "phase2" / "ml_handoff"
             / "06_ml_training_point_hour_2022_2025.parquet")

MODEL_DIR = REPO_ROOT / "backend" / "models"
MODEL_PATH = MODEL_DIR / "heat_index_model.joblib"
OUTPUT_DIR = REPO_ROOT / "outputs" / "ml"

TARGET = "heat_index_category"
ALL_CLASSES = ["LOW", "MODERATE", "HIGH", "VERY_HIGH", "EXTREME"]

TRAIN_YEARS = [2022]
VAL_YEARS = [2023]
TEST_YEARS = [2024, 2025]

RANDOM_STATE = 42

# Columns that must NEVER be used as inputs:
LEAKAGE_COLUMNS = [
    "heat_index_category",   # the target itself
    "heat_index_c",          # the target is just this value binned
    "wbgt_shade_proxy_c",    # another derived thermal index (same T/RH family)
]
ID_OR_TIME_COLUMNS = [
    "timestamp",             # raw timestamp (we use hour/month/etc. instead)
    "weather_point_id",      # an ID, not a physical quantity
    "year",                  # used only for the split; would not generalise
]


# ============================================================
# SECTION 1 -- AUTOMATIC FEATURE SELECTION (from the real schema)
# ============================================================

def select_features(all_columns):
    """Pick input features by reading the actual column names.

    Rules (simple on purpose):
      * weather: the 4 raw weather variables
      * temporal: month, day, hour, weekday + their sin/cos versions
      * location: latitude, longitude
      * environment: for each 300m variable the table stores many
        summaries (mean/median/min/max of mean/median/min/max...).
        These are almost identical to each other, so we keep only
        the columns ending in "_mean" (average over the 300m cells
        linked to the weather point). This avoids ~40 redundant copies.
    """
    weather = ["temperature_2m_c", "relative_humidity_pct",
               "wind_speed_10m_ms", "shortwave_radiation_wm2"]
    temporal = ["month", "day_of_year", "hour", "day_of_week",
                "hour_sin", "hour_cos", "doy_sin", "doy_cos"]
    location = ["latitude", "longitude"]

    env_prefixes = ("lst_", "ndvi_", "land_cover_", "elevation_")
    environment = [c for c in all_columns
                   if c.startswith(env_prefixes) and c.endswith("_mean")]

    features = [c for c in weather + temporal + location + environment
                if c in all_columns
                and c not in LEAKAGE_COLUMNS
                and c not in ID_OR_TIME_COLUMNS]
    return features


# ============================================================
# SECTION 2 -- LOAD DATA
# ============================================================

def load_data(feature_names, sample_frac=1.0):
    """Load only the columns we need (memory-friendly) as float32."""
    columns = ["timestamp", "weather_point_id", "year", TARGET] + feature_names
    parquet = pq.ParquetFile(DATA_FILE)

    # Read one chunk at a time and shrink it immediately (float64 -> float32,
    # text -> category). Reading everything at once as float64 needs ~2x the
    # memory and can crash a normal laptop.
    parts = []
    for batch in parquet.iter_batches(batch_size=500_000, columns=columns):
        chunk = batch.to_pandas()
        float_cols = chunk.select_dtypes("float64").columns
        chunk[float_cols] = chunk[float_cols].astype("float32")
        chunk[TARGET] = chunk[TARGET].astype(str).astype("category")
        chunk["weather_point_id"] = chunk["weather_point_id"].astype("category")
        if sample_frac < 1.0:
            chunk = chunk.sample(frac=sample_frac, random_state=RANDOM_STATE)
        parts.append(chunk)

    df = pd.concat(parts, ignore_index=True)
    # concat can turn mismatched categories back into text -- re-shrink
    df[TARGET] = df[TARGET].astype(str).astype("category")
    df["weather_point_id"] = df["weather_point_id"].astype(str).astype("category")
    return df


def inspect_data(df):
    print("\nShape:", df.shape)
    print("\nData types:")
    print(df.dtypes.to_string())
    print("\nMissing values (columns with any):")
    missing = df.isna().sum()
    print(missing[missing > 0].to_string() if missing.any() else "  none")
    print("\nDuplicate (weather_point_id, timestamp) rows:",
          int(df.duplicated(["weather_point_id", "timestamp"]).sum()))
    print("\nTarget distribution (all years):")
    counts = df[TARGET].value_counts().reindex(ALL_CLASSES, fill_value=0)
    print(pd.DataFrame({"count": counts,
                        "percent": (counts / len(df) * 100).round(2)}).to_string())


# ============================================================
# SECTION 3 -- CHRONOLOGICAL SPLIT
# ============================================================

def split_by_year(df):
    train = df[df["year"].isin(TRAIN_YEARS)]
    val = df[df["year"].isin(VAL_YEARS)]
    test = df[df["year"].isin(TEST_YEARS)]
    return train, val, test


def print_split(name, part):
    counts = part[TARGET].value_counts().reindex(ALL_CLASSES, fill_value=0)
    dist = ", ".join(f"{c}={n:,}" for c, n in counts.items())
    print(f"  {name:<11} rows={len(part):>10,}   {dist}")


# ============================================================
# SECTION 4 -- MODELS (simple, fixed parameters)
# ============================================================

def build_models():
    return {
        "XGBoost": XGBClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            objective="multi:softprob", tree_method="hist",
            random_state=RANDOM_STATE, n_jobs=-1,
        ),
        "LightGBM": LGBMClassifier(
            n_estimators=200, learning_rate=0.05, num_leaves=31,
            class_weight="balanced", importance_type="gain",
            random_state=RANDOM_STATE, n_jobs=-1, verbose=-1,
        ),
        "RandomForest": RandomForestClassifier(
            n_estimators=200, max_depth=15, min_samples_leaf=5,
            class_weight="balanced",
            random_state=RANDOM_STATE, n_jobs=-1,
        ),
    }


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-frac", type=float, default=1.0,
                        help="Use a random fraction of rows (1.0 = all rows).")
    args = parser.parse_args()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- Section 1: schema + feature selection ----------
    print("=" * 70)
    print("SECTION 1 -- LOAD + INSPECT")
    print("=" * 70)
    all_columns = pq.ParquetFile(DATA_FILE).schema_arrow.names
    print(f"File: {DATA_FILE}")
    print(f"All columns in file ({len(all_columns)}): {all_columns}")

    features = select_features(all_columns)
    print(f"\nSelected {len(features)} input features: {features}")
    print(f"Excluded as leakage: {LEAKAGE_COLUMNS}")
    print(f"Excluded as ID/time: {ID_OR_TIME_COLUMNS}")
    print("Note: no land-cover CLASS column exists in this table (only "
          "land_cover_fraction_*), so there is no categorical feature to encode.")

    df = load_data(features, args.sample_frac)
    if args.sample_frac < 1.0:
        print(f"\n*** Using a {args.sample_frac:.0%} random sample of rows ***")
    inspect_data(df)

    # ---------- Section 2: preprocessing ----------
    print("\n" + "=" * 70)
    print("SECTION 2 -- PREPROCESSING")
    print("=" * 70)
    before = len(df)
    df = df[df[TARGET].isin(ALL_CLASSES)]
    print(f"Rows removed for missing/invalid target: {before - len(df):,}")

    # ---------- Section 3: chronological split ----------
    print("\n" + "=" * 70)
    print("SECTION 3 -- CHRONOLOGICAL SPLIT")
    print("=" * 70)
    train_df, val_df, test_df = split_by_year(df)
    print(f"Train={TRAIN_YEARS}  Validation={VAL_YEARS}  Test={TEST_YEARS}")
    print_split("Train", train_df)
    print_split("Validation", val_df)
    print_split("Test", test_df)

    # Classes the model can actually learn = classes present in training
    class_names = [c for c in ALL_CLASSES if (train_df[TARGET] == c).any()]
    missing_classes = [c for c in ALL_CLASSES if c not in class_names]
    if missing_classes:
        print(f"\nLIMITATION: {missing_classes} have ZERO training samples. "
              "The model cannot learn or predict them.")
    class_to_id = {c: i for i, c in enumerate(class_names)}

    # Missing values: median of the TRAINING set only (no leakage from val/test)
    imputer = SimpleImputer(strategy="median")
    X_train = imputer.fit_transform(train_df[features]).astype("float32")
    X_val = imputer.transform(val_df[features]).astype("float32")
    X_test = imputer.transform(test_df[features]).astype("float32")

    y_train = train_df[TARGET].astype(str).map(class_to_id).to_numpy()
    y_val = val_df[TARGET].astype(str).map(class_to_id).to_numpy()
    y_test = test_df[TARGET].astype(str).map(class_to_id).to_numpy()
    del df, train_df, val_df, test_df  # free memory

    # ---------- Section 4 + 5: train with class weights ----------
    print("\n" + "=" * 70)
    print("SECTION 4/5 -- TRAIN MODELS (class-weighted, no oversampling)")
    print("=" * 70)
    sample_weight = compute_sample_weight("balanced", y_train)

    models = build_models()
    rows, reports, val_preds, test_preds = [], [], {}, {}
    for name, model in models.items():
        print(f"\nTraining {name} ...", flush=True)
        if name == "XGBoost":
            model.fit(X_train, y_train, sample_weight=sample_weight)
        else:
            model.fit(X_train, y_train)  # LightGBM/RF use class_weight="balanced"

        val_preds[name] = model.predict(X_val)
        test_preds[name] = model.predict(X_test)

        for split, y_true, y_pred in [("validation", y_val, val_preds[name]),
                                      ("test", y_test, test_preds[name])]:
            m = compute_metrics(y_true, y_pred, class_names)
            rows.append({"model": name, "split": split, **m})
            reports.append(f"\n{'#' * 70}\n{name} -- {split.upper()}\n{'#' * 70}\n"
                           + text_report(y_true, y_pred, class_names))
        val_row = rows[-2]
        print(f"  validation: accuracy={val_row['accuracy']:.4f}  "
              f"macro_f1={val_row['macro_f1']:.4f}  weighted_f1={val_row['weighted_f1']:.4f}")

    # ---------- Section 6: evaluation tables ----------
    print("\n" + "=" * 70)
    print("SECTION 6 -- EVALUATION (all models, all metrics)")
    print("=" * 70)
    comparison = pd.DataFrame(rows)
    comparison.to_csv(OUTPUT_DIR / "model_comparison.csv", index=False)
    with pd.option_context("display.width", 200, "display.max_columns", 50):
        print(comparison.round(4).to_string(index=False))
    for r in reports:
        print(r)

    # ---------- Section 7: select on VALIDATION macro F1 ----------
    val_only = comparison[comparison["split"] == "validation"]
    best_name = val_only.sort_values("macro_f1", ascending=False).iloc[0]["model"]
    best_model = models[best_name]
    best_val = val_only.set_index("model").loc[best_name]
    best_test = comparison[(comparison.split == "test")].set_index("model").loc[best_name]

    test_report_text = text_report(y_test, test_preds[best_name], class_names)
    print("\n" + "=" * 70)
    print("SECTION 7 -- MODEL SELECTION (by validation macro F1 only)")
    print("=" * 70)
    print(f"SELECTED MODEL:\n{best_name}\n")
    print(f"VALIDATION MACRO F1:\n{best_val['macro_f1']:.4f}\n")
    print(f"TEST MACRO F1:\n{best_test['macro_f1']:.4f}\n")
    print(f"TEST CLASSIFICATION REPORT:\n{test_report_text}")

    with open(OUTPUT_DIR / "classification_report.txt", "w", encoding="utf-8") as f:
        f.write(f"SELECTED MODEL: {best_name} (chosen by validation macro F1)\n")
        f.write(f"Train={TRAIN_YEARS} Validation={VAL_YEARS} Test={TEST_YEARS}\n")
        if missing_classes:
            f.write(f"LIMITATION: no training samples for {missing_classes}\n")
        f.write("\n".join(reports))

    save_confusion_matrix_plot(
        y_test, test_preds[best_name], class_names,
        f"{best_name} -- test set {TEST_YEARS[0]}-{TEST_YEARS[-1]}",
        OUTPUT_DIR / "confusion_matrix.png",
    )

    # ---------- Section 8: feature importance ----------
    print("\n" + "=" * 70)
    print("SECTION 8 -- FEATURE IMPORTANCE")
    print("=" * 70)
    importance = (pd.DataFrame({"feature": features,
                                "importance": best_model.feature_importances_})
                  .sort_values("importance", ascending=False))
    importance["importance_pct"] = (importance["importance"]
                                    / importance["importance"].sum() * 100).round(2)
    importance.to_csv(OUTPUT_DIR / "feature_importance.csv", index=False)
    print(importance.head(15).to_string(index=False))

    top = importance.head(20).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.barh(top["feature"], top["importance_pct"])
    ax.set_xlabel("Importance (% of total)")
    ax.set_title(f"{best_name} -- top 20 features")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "feature_importance.png", dpi=150)
    plt.close(fig)

    # ---------- Section 9: SHAP ----------
    print("\n" + "=" * 70)
    print("SECTION 9 -- SHAP")
    print("=" * 70)
    try:
        import shap
        rng = np.random.default_rng(RANDOM_STATE)
        n_shap = 500 if best_name == "RandomForest" else 2000  # RF SHAP is slow
        idx = rng.choice(len(X_test), size=min(n_shap, len(X_test)), replace=False)
        X_shap = pd.DataFrame(X_test[idx], columns=features)

        explainer = shap.TreeExplainer(best_model)
        sv = np.asarray(explainer.shap_values(X_shap))
        # Normalise shape to (samples, features, classes)
        if sv.ndim == 3 and sv.shape[0] == len(class_names):
            sv = np.transpose(sv, (1, 2, 0))

        per_class = [sv[:, :, k] for k in range(sv.shape[2])]
        shap.summary_plot(per_class, X_shap, plot_type="bar",
                          class_names=class_names, max_display=15, show=False)
        plt.title(f"SHAP global importance -- {best_name} (n={len(X_shap)} test rows)")
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / "shap_summary.png", dpi=150)
        plt.close()

        shap_global = (pd.DataFrame({"feature": features,
                                     "mean_abs_shap": np.abs(sv).mean(axis=(0, 2))})
                       .sort_values("mean_abs_shap", ascending=False))
        shap_global.to_csv(OUTPUT_DIR / "shap_global_importance.csv", index=False)
        print(shap_global.head(10).to_string(index=False))
    except ImportError:
        print("SHAP not installed -- skipped. Install with:  pip install shap")

    # ---------- Section 10: save model + metadata ----------
    print("\n" + "=" * 70)
    print("SECTION 10 -- SAVE MODEL")
    print("=" * 70)
    bundle = {
        "model": best_model,
        "model_name": best_name,
        "imputer": imputer,              # same missing-value handling at inference
        "feature_names": features,       # exact column order the model expects
        "class_names": class_names,      # label id -> category name
    }
    joblib.dump(bundle, MODEL_PATH, compress=3)

    with open(MODEL_DIR / "feature_names.json", "w") as f:
        json.dump(features, f, indent=2)

    metadata = {
        "model_name": best_name,
        "target_column": TARGET,
        "target_classes_all": ALL_CLASSES,
        "target_classes_learned": class_names,
        "classes_with_no_training_data": missing_classes,
        "training_period": TRAIN_YEARS,
        "validation_period": VAL_YEARS,
        "test_period": TEST_YEARS,
        "sample_frac_used": args.sample_frac,
        "features_used": features,
        "excluded_leakage_columns": LEAKAGE_COLUMNS,
        "missing_value_handling": "median imputation fitted on training years only",
        "class_imbalance_handling": "balanced class/sample weights (no oversampling)",
        "selection_metric": "validation macro F1",
        "metrics": {
            "validation": {k: round(float(v), 4) for k, v in best_val.items() if k != "split"},
            "test": {k: round(float(v), 4) for k, v in best_test.items() if k != "split"},
        },
        "caveats": [
            "Target is a deterministic formula of temperature + humidity; "
            "high scores mean the model re-learned that formula, not forecasting skill.",
            "Weather resolution is ~10-25 km (118 points); 300m environmental "
            "features are summarised per weather point.",
            "EXTREME has zero samples in 2022-2025 and cannot be predicted.",
        ],
    }
    with open(MODEL_DIR / "model_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Model:     {MODEL_PATH}")
    print(f"Metadata:  {MODEL_DIR / 'model_metadata.json'}")
    print(f"Features:  {MODEL_DIR / 'feature_names.json'}")
    print(f"Outputs:   {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
