# Training

`train.py` does the full training pipeline:
- Generates synthetic `dataset.csv` (500 rows) if missing
- Fits TF-IDF vectorizer
- Trains Logistic Regression classifier
- Trains Linear Regression regressor
- Trains KMeans clustering model
- Fits StandardScaler
- Saves all artifacts as pickle files

Artifacts are written to `ARTIFACTS_DIR` (default `training/artifacts`, Docker uses `/artifacts`).
