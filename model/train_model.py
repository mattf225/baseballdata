import os
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, roc_auc_score

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MODELS_DIR = os.path.join(os.path.dirname(__file__), "trained_models")
if not os.path.exists(MODELS_DIR):
    os.makedirs(MODELS_DIR)

def load_and_prep_data():
    """Loads CSV and handles missing values."""
    csv_path = os.path.join(DATA_DIR, "mlb_training_dataset.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Dataset not found at {csv_path}")
        
    df = pd.read_csv(csv_path)
    
    # Define our input features (X)
    feature_cols = ['rolling_10_PA', 'rolling_10_AB', 'rolling_10_H', 
                    'rolling_10_HR', 'rolling_10_SO', 'rolling_10_TB']
    
    # Drop rows with NaN in features (e.g. players without 10 games of history)
    df = df.dropna(subset=feature_cols)
    
    return df, feature_cols

def train_market_model(df, feature_cols, target_col, market_name):
    """
    Trains an XGBoost Binary Classifier to predict 'Target_HR', 'Target_Hit', etc.
    Crucially: It calibrates the probability so it represents a true mathematical percentage.
    """
    print(f"\n--- Training Model for {market_name} ({target_col}) ---")
    
    X = df[feature_cols]
    y = df[target_col]
    
    # 1. Train-Test Split (80% training, 20% validation)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # 2. Initialize Random Forest Classifier
    # Using shallow trees to prevent overfitting on this small sample scope
    clf = RandomForestClassifier(n_estimators=100, max_depth=3, random_state=42)
    
    # 3. Probability Calibration 
    # Sports betting requires calibrated probabilities. We wrap the RF in an Isotonic scale.
    calibrated_clf = CalibratedClassifierCV(clf, method='isotonic', cv=3)
    
    print(f"Fitting model on {len(X_train)} rows...")
    calibrated_clf.fit(X_train, y_train)
    
    # 4. Evaluation
    y_pred_proba = calibrated_clf.predict_proba(X_test)[:, 1] # Probability of the positive class (1)
    
    # AUC: How well does it rank players? (> 0.5 is better than random)
    auc = roc_auc_score(y_test, y_pred_proba)
    # Brier Score: How mathematically accurate are the % probabilities? (Closer to 0 is perfect)
    brier = brier_score_loss(y_test, y_pred_proba)
    
    print(f"✅ Training Complete. Diagnostics:")
    print(f"  ↪️ ROC AUC Score: {auc:.4f}")
    print(f"  ↪️ Brier Score (Calibration error): {brier:.4f}")
    
    # 5. Export Model Artifact
    model_path = os.path.join(MODELS_DIR, f"{market_name}_model.pkl")
    joblib.dump(calibrated_clf, model_path)
    print(f"💾 Saved calibrated model to {model_path}")

def main():
    print("Initiating B.L.A.S.T. Machine Learning Training Pipeline...")
    try:
        df, feature_cols = load_and_prep_data()
    except FileNotFoundError as e:
        print(e)
        return
        
    print(f"Dataset loaded. Dimensions: {df.shape}")
    
    # We train isolated models for each independent player prop market!
    targets = {
        'batter_home_runs': 'Target_HR',
        'batter_hits': 'Target_Hit',
        'batter_total_bases_1.5': 'Target_TB_Over_1_5',
        'batter_strikeouts': 'Target_SO'
    }
    
    for market, target_col in targets.items():
        if target_col in df.columns:
             train_market_model(df, feature_cols, target_col, market)
        else:
             print(f"Skipping {market}: {target_col} not found in dataset.")

if __name__ == "__main__":
    main()
