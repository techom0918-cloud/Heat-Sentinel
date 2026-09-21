"""
HeatSentinel -- evaluation helpers.

Used by train_heat_model.py, and can also be run on its own to
re-evaluate the SAVED model on the untouched test period (2024-2025):

    python ml/evaluate_model.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # save plots to file, no GUI window needed
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

# Classes we care about most for heat-health warnings
DANGER_CLASSES = ["HIGH", "VERY_HIGH", "EXTREME"]


# ============================================================
# 1. COMPUTE METRICS
# ============================================================

def compute_metrics(y_true, y_pred, class_names):
    """Return a flat dict of metrics for one model on one split.

    y_true / y_pred are integer labels (0..K-1); class_names[i] is the
    name of label i.
    """
    labels = list(range(len(class_names)))

    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0
    )

    metrics = {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_precision": float(np.mean(precision)),
        "macro_recall": float(np.mean(recall)),
        "macro_f1": f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0),
        "weighted_f1": f1_score(y_true, y_pred, labels=labels, average="weighted", zero_division=0),
    }

    # Per-class recall/precision for the dangerous heat categories
    for i, name in enumerate(class_names):
        if name in DANGER_CLASSES:
            metrics[f"{name}_precision"] = float(precision[i])
            metrics[f"{name}_recall"] = float(recall[i])
            metrics[f"{name}_f1"] = float(f1[i])

    return metrics


def text_report(y_true, y_pred, class_names):
    """Classification report + confusion matrix as plain text."""
    labels = list(range(len(class_names)))
    report = classification_report(
        y_true, y_pred, labels=labels, target_names=class_names,
        digits=4, zero_division=0,
    )
    cm = confusion_matrix(y_true, y_pred, labels=labels)

    lines = [report, "Confusion matrix (rows = TRUE, columns = PREDICTED):"]
    header = " " * 12 + "".join(f"{n:>12}" for n in class_names)
    lines.append(header)
    for i, name in enumerate(class_names):
        lines.append(f"{name:>12}" + "".join(f"{v:>12,}" for v in cm[i]))
    return "\n".join(lines)


# ============================================================
# 2. CONFUSION MATRIX PLOT
# ============================================================

def save_confusion_matrix_plot(y_true, y_pred, class_names, title, out_path):
    labels = list(range(len(class_names)))
    cm = confusion_matrix(y_true, y_pred, labels=labels)

    # Row-normalise so each row shows "of the true X, what % was predicted as ..."
    with np.errstate(invalid="ignore", divide="ignore"):
        cm_pct = cm / cm.sum(axis=1, keepdims=True) * 100

    fig, ax = plt.subplots(figsize=(7, 6))
    ax.imshow(np.nan_to_num(cm_pct), cmap="Oranges", vmin=0, vmax=100)
    ax.set_xticks(labels, class_names, rotation=30, ha="right")
    ax.set_yticks(labels, class_names)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title)

    for i in labels:
        for j in labels:
            ax.text(j, i, f"{cm[i, j]:,}\n({np.nan_to_num(cm_pct[i, j]):.1f}%)",
                    ha="center", va="center", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ============================================================
# 3. STANDALONE: RE-EVALUATE SAVED MODEL ON TEST SET
# ============================================================

if __name__ == "__main__":
    import joblib

    from train_heat_model import (  # reuse the SAME loading/splitting code
        MODEL_PATH, load_data, split_by_year,
    )

    bundle = joblib.load(MODEL_PATH)
    df = load_data(bundle["feature_names"])
    _, _, test_df = split_by_year(df)

    class_names = bundle["class_names"]
    class_to_id = {c: i for i, c in enumerate(class_names)}

    X_test = bundle["imputer"].transform(test_df[bundle["feature_names"]])
    y_test = test_df["heat_index_category"].astype(str).map(class_to_id).to_numpy()
    y_pred = bundle["model"].predict(X_test)

    print(f"Model: {bundle['model_name']}")
    print(compute_metrics(y_test, y_pred, class_names))
    print(text_report(y_test, y_pred, class_names))
