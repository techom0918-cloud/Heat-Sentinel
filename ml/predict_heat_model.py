"""
HeatSentinel -- predict Heat Index Category with the saved model.

    python ml/predict_heat_model.py      (runs a small demo)

In your own code:

    from predict_heat_model import predict_heat_index_category
    result = predict_heat_index_category({"temperature_2m_c": 41.0, ...})
"""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

MODEL_PATH = (Path(__file__).resolve().parent.parent
              / "backend" / "models" / "heat_index_model.joblib")

_bundle = None  # loaded once, then reused


def _load():
    global _bundle
    if _bundle is None:
        _bundle = joblib.load(MODEL_PATH)
    return _bundle


def predict_heat_index_category(input_data):
    """input_data: a dict (one row) or a list of dicts / DataFrame (many rows).

    Missing features are allowed -- they are filled with the SAME training
    medians used during training. Extra keys are ignored.

    Returns (for one row):
        {"predicted_category": "HIGH", "probabilities": {"LOW": 0.01, ...}}
    For many rows, a list of such dicts.
    """
    bundle = _load()
    features = bundle["feature_names"]
    classes = bundle["class_names"]

    single = isinstance(input_data, dict)
    df = pd.DataFrame([input_data] if single else input_data)

    # Put columns in the exact training order; unknown ones become NaN -> imputed
    X = df.reindex(columns=features).astype("float32")
    X = bundle["imputer"].transform(X)

    proba = bundle["model"].predict_proba(X)
    results = []
    for row in proba:
        results.append({
            "predicted_category": classes[int(np.argmax(row))],
            "probabilities": {c: round(float(p), 4) for c, p in zip(classes, row)},
        })
    return results[0] if single else results


if __name__ == "__main__":
    # Demo: a hot, humid June afternoon near Delhi
    example = {
        "temperature_2m_c": 38.0,
        "relative_humidity_pct": 55.0,
        "wind_speed_10m_ms": 2.0,
        "shortwave_radiation_wm2": 750.0,
        "month": 6, "day_of_year": 170, "hour": 14, "day_of_week": 2,
        "hour_sin": np.sin(2 * np.pi * 14 / 24), "hour_cos": np.cos(2 * np.pi * 14 / 24),
        "doy_sin": np.sin(2 * np.pi * 170 / 365.25), "doy_cos": np.cos(2 * np.pi * 170 / 365.25),
        "latitude": 28.61, "longitude": 77.21,
        # environmental features left out on purpose -> filled with training medians
    }
    print(predict_heat_index_category(example))
