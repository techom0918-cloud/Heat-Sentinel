# HeatSentinel — Heat Index Category Classifier

Predicts `LOW / MODERATE / HIGH / VERY_HIGH / EXTREME` from weather,
time and environmental features using XGBoost, LightGBM and Random Forest.

## Install

```
pip install pandas pyarrow numpy scikit-learn xgboost lightgbm matplotlib joblib shap
```

## Run (from repo root)

```
python ml/train_heat_model.py            # full pipeline (all rows)
python ml/train_heat_model.py --sample-frac 0.25   # quicker trial run
python ml/evaluate_model.py              # re-check saved model on test set
python ml/predict_heat_model.py          # demo prediction
```

## Pipeline in one paragraph (viva version)

1. **Load** `06_ml_training_point_hour_2022_2025.parquet` (4.14M rows = 118 weather points × hourly, 2022–2025).
2. **Features** are chosen from the real column names: 4 weather variables, 8 time variables, lat/lon, and the `_mean` summary of each 300m environmental variable (LST, NDVI, land-cover fraction, elevation).
3. **Leakage removed**: `heat_index_category` (target), `heat_index_c` (target before binning), `wbgt_shade_proxy_c` (another derived thermal index). IDs, raw timestamp and `year` are also dropped.
4. **Missing values** (environment features missing for some weather points) → median, **fitted on 2022 only**.
5. **Chronological split**: train 2022, validate 2023, test 2024–2025. No random shuffling.
6. **Imbalance**: balanced class weights / sample weights. No oversampling, no synthetic labels.
7. **Train** 3 models with simple fixed parameters → pick the one with the best **validation macro F1** → report it once on the test set.
8. **Explain**: feature importance + SHAP. **Save**: model, imputer, feature list, class list, metadata.

## Limitations — say these out loud

- **The target is a formula.** `heat_index_category` = binned `heat_index_c`, which is computed from temperature + humidity. The model mostly re-learns that formula, which is why accuracy is ~99%. This is a *baseline classifier*, not a forecast of future heat.
- **EXTREME has zero samples** in 2022–2025 (max heat index ≈ 49.9 °C < 54.4 °C threshold). The model cannot predict EXTREME.
- **Resolution.** Weather is ~10–25 km (118 grid points). The 300m environmental features are summarised per weather point, so predictions are at weather-point level, **not** 300m.
- Environmental features barely matter (<1% importance) because they are static per point and the target depends on T and RH.

## Files

```
backend/models/heat_index_model.joblib   model + imputer + feature names + classes
backend/models/model_metadata.json
backend/models/feature_names.json
outputs/ml/model_comparison.csv          all metrics, all models, val + test
outputs/ml/classification_report.txt
outputs/ml/confusion_matrix.png          selected model, test set
outputs/ml/feature_importance.csv / .png
outputs/ml/shap_summary.png (+ shap_global_importance.csv)
```
