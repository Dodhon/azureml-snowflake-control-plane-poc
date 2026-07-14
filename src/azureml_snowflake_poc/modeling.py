"""Deterministic multiclass training and MLflow artifact creation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, log_loss
from sklearn.model_selection import train_test_split

MODEL_IMPLEMENTATION_VERSION = "random-forest-v1"


@dataclass(frozen=True, slots=True)
class TrainingResult:
    model: RandomForestClassifier
    metrics: dict[str, float]
    validation_rows: int


def train_classifier(
    training: pd.DataFrame,
    *,
    feature_columns: list[str],
    label_column: str = "quantity_class",
    random_seed: int = 17,
) -> TrainingResult:
    """Train and evaluate a deterministic exact-class Random Forest candidate."""
    required = [*feature_columns, label_column]
    missing = [column for column in required if column not in training.columns]
    if missing:
        raise ValueError(f"training data is missing columns: {', '.join(missing)}")
    if len(training) < 12:
        raise ValueError("training data requires at least 12 rows for a deterministic holdout")

    features = training.loc[:, feature_columns]
    labels = training[label_column].astype(str)
    if labels.nunique() < 2:
        raise ValueError("training data requires at least two quantity classes")
    train_x, validation_x, train_y, validation_y = train_test_split(
        features,
        labels,
        test_size=0.25,
        random_state=random_seed,
        stratify=labels,
    )
    model = RandomForestClassifier(
        n_estimators=160,
        max_depth=12,
        min_samples_leaf=1,
        random_state=random_seed,
        n_jobs=-1,
    )
    model.fit(train_x, train_y)
    predicted = model.predict(validation_x)
    probabilities = model.predict_proba(validation_x)
    metrics = {
        "accuracy": float(accuracy_score(validation_y, predicted)),
        "macro_f1": float(f1_score(validation_y, predicted, average="macro")),
        "log_loss": float(log_loss(validation_y, probabilities, labels=list(model.classes_))),
    }
    return TrainingResult(model=model, metrics=metrics, validation_rows=len(validation_y))


def save_model_artifact(
    result: TrainingResult,
    output_dir: Path,
    *,
    metadata: dict[str, Any],
) -> None:
    """Write a portable model artifact; AML jobs additionally wrap it as MLflow."""
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(result.model, output_dir / "model.joblib")
    payload = {
        "metrics": dict(sorted(result.metrics.items())),
        "validation_rows": result.validation_rows,
        "metadata": metadata,
    }
    import json

    (output_dir / "metadata.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
