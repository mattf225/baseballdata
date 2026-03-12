import os
import json
import pandas as pd
import joblib
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, roc_auc_score

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MODELS_DIR = os.path.join(os.path.dirname(__file__), "trained_models")
if not os.path.exists(MODELS_DIR):
    os.makedirs(MODELS_DIR)


def train_market_model(df, feature_cols, target_col, market_name, data_source: str = ""):
    """
    Trains a Random Forest Binary Classifier and calibrates the probability.
    Saves both the model artifact and a metadata JSON for auditability.
    """
    print(f"\n--- Training Model for {market_name} ({target_col}) ---")

    df_clean = df.dropna(subset=feature_cols).copy()

    if target_col not in df_clean.columns:
        print(f"Skipping {market_name}: {target_col} not found in dataset.")
        return

    X = df_clean[feature_cols]
    y = df_clean[target_col]

    # Stratified split to preserve class distribution for imbalanced targets (e.g. rare HR events)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # class_weight='balanced' corrects for rare positive events
    clf = RandomForestClassifier(
        n_estimators=100, max_depth=3, random_state=42, class_weight='balanced'
    )

    # cv=5 provides more reliable calibration vs cv=3, especially on smaller datasets
    calibrated_clf = CalibratedClassifierCV(clf, method='isotonic', cv=5)

    print(f"Fitting model on {len(X_train)} rows...")
    calibrated_clf.fit(X_train, y_train)

    y_pred_proba = calibrated_clf.predict_proba(X_test)[:, 1]

    auc   = roc_auc_score(y_test, y_pred_proba)
    brier = brier_score_loss(y_test, y_pred_proba)

    print(f"Training Complete. Diagnostics:")
    print(f"  ROC AUC Score: {auc:.4f}")
    print(f"  Brier Score (Calibration error): {brier:.4f}")

    # Save model artifact
    model_path = os.path.join(MODELS_DIR, f"{market_name}_model.pkl")
    joblib.dump(calibrated_clf, model_path)
    print(f"Saved calibrated model to {model_path}")

    # Save metadata for auditability (what data + when trained this model)
    metadata = {
        "market": market_name,
        "target": target_col,
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "data_source": data_source,
        "training_rows": len(X_train),
        "test_rows": len(X_test),
        "roc_auc": round(auc, 4),
        "brier_score": round(brier, 4),
        "features": feature_cols,
        "positive_class_rate": round(float(y.mean()), 4),
    }
    meta_path = os.path.join(MODELS_DIR, f"{market_name}_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)


def main():
    print("Initiating B.L.A.S.T. Machine Learning Training Pipeline...")

    # --------------------------------------------------------------------------------
    # 1. Train Batter Models
    # --------------------------------------------------------------------------------
    batter_csv = os.path.join(DATA_DIR, "mlb_training_dataset.csv")
    if os.path.exists(batter_csv):
        df_batter = pd.read_csv(batter_csv)
        batter_features = [
            'rolling_10_PA', 'rolling_10_AB', 'rolling_10_H',
            'rolling_10_HR', 'rolling_10_SO', 'rolling_10_TB'
        ]
        batter_targets = {
            'batter_home_runs':       'Target_HR',
            'batter_hits':            'Target_Hit',
            'batter_total_bases_1.5': 'Target_TB_Over_1_5',
            'batter_strikeouts':      'Target_SO',
        }
        for market, target in batter_targets.items():
            train_market_model(df_batter, batter_features, target, market, data_source=batter_csv)
    else:
        print(f"Batter dataset not found at {batter_csv}")

    # --------------------------------------------------------------------------------
    # 2. Train Pitcher Models
    # --------------------------------------------------------------------------------
    pitcher_csv = os.path.join(DATA_DIR, "mlb_pitcher_training_dataset.csv")
    if os.path.exists(pitcher_csv):
        df_pitcher = pd.read_csv(pitcher_csv)
        pitcher_features = [
            'rolling_5_BF', 'rolling_5_SO', 'rolling_5_BBA',
            'rolling_5_HA', 'rolling_5_Outs'
        ]
        pitcher_targets = {
            'pitcher_strikeouts':    'Target_SO_Over_4_5',
            'pitcher_outs':          'Target_Outs_Over_15_5',
            'pitcher_hits_allowed':  'Target_HA_Over_4_5',
            'pitcher_walks_allowed': 'Target_BBA_Over_1_5',
        }
        for market, target in pitcher_targets.items():
            train_market_model(df_pitcher, pitcher_features, target, market, data_source=pitcher_csv)
    else:
        print(f"Pitcher dataset not found at {pitcher_csv}")


if __name__ == "__main__":
    main()
