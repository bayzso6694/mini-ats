import json
import os
import pickle
import random
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

BASE_DIR = Path(__file__).resolve().parent
DATASET_PATH = BASE_DIR / "dataset.csv"
ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", str(BASE_DIR / "artifacts")))
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

SKILLS_POOL = [
    "python",
    "java",
    "sql",
    "aws",
    "docker",
    "kubernetes",
    "fastapi",
    "django",
    "react",
    "node",
    "pandas",
    "scikit-learn",
    "nlp",
    "rest",
    "microservices",
]

DEGREES = ["bachelor", "master", "phd"]


def _generate_text(skills: list[str], years: int, degree: str, role: str) -> str:
    skill_phrase = ", ".join(skills)
    return (
        f"Candidate with {years} years of experience in {skill_phrase}. "
        f"Built APIs and services for {role}. "
        f"Education: {degree}. Delivered production systems and collaborated cross-functionally."
    )


def _build_dataset(rows: int = 500) -> pd.DataFrame:
    role_templates = [
        "backend engineering",
        "data engineering",
        "platform development",
        "ml operations",
        "web engineering",
    ]

    samples = []
    for _ in range(rows):
        required_count = random.randint(4, 7)
        required_skills = random.sample(SKILLS_POOL, required_count)
        resume_count = random.randint(3, 8)
        resume_skills = random.sample(SKILLS_POOL, resume_count)

        years_exp = random.randint(0, 12)
        min_exp = random.randint(0, 8)
        degree = random.choice(DEGREES)
        edu_level = {"bachelor": 0, "master": 1, "phd": 2}[degree]
        role = random.choice(role_templates)

        job_description = (
            f"We need {role} expertise with {', '.join(required_skills)}. "
            f"Minimum {min_exp} years experience."
        )
        resume_text = _generate_text(resume_skills, years_exp, degree, role)

        overlap = len(set(resume_skills).intersection(set(required_skills)))
        skill_match = overlap / max(len(required_skills), 1)
        exp_score = min(years_exp / max(min_exp, 1), 1.5)
        edu_score = edu_level / 2

        latent_fit = 0.55 * skill_match + 0.30 * min(exp_score, 1.0) + 0.15 * edu_score
        latent_fit = max(0.0, min(1.0, latent_fit + np.random.normal(0, 0.08)))
        hired = 1 if latent_fit >= 0.58 else 0

        samples.append(
            {
                "resume_text": resume_text,
                "job_description": job_description,
                "skill_match_score": round(skill_match, 4),
                "years_experience": years_exp,
                "education_level": edu_level,
                "hired": hired,
            }
        )

    return pd.DataFrame(samples)


def _prepare_features(df: pd.DataFrame, vectorizer: TfidfVectorizer) -> tuple[np.ndarray, np.ndarray]:
    resume_matrix = vectorizer.transform(df["resume_text"].tolist())
    job_matrix = vectorizer.transform(df["job_description"].tolist())
    cosine_scores = np.array(
        [
            cosine_similarity(resume_matrix[i], job_matrix[i])[0][0]
            for i in range(resume_matrix.shape[0])
        ]
    )
    base_features = np.column_stack(
        [
            cosine_scores,
            df["skill_match_score"].values,
            df["years_experience"].values,
            df["education_level"].values,
        ]
    )
    return base_features, cosine_scores


def main() -> None:
    required_cols = {
        "resume_text",
        "job_description",
        "skill_match_score",
        "years_experience",
        "education_level",
        "hired",
    }

    regenerate = False
    if not DATASET_PATH.exists():
        regenerate = True
    else:
        df = pd.read_csv(DATASET_PATH)
        if df.empty or not required_cols.issubset(df.columns):
            regenerate = True
        else:
            print(f"Loaded dataset from {DATASET_PATH}")

    if regenerate:
        df = _build_dataset(rows=500)
        df.to_csv(DATASET_PATH, index=False)
        print(f"Generated synthetic dataset at {DATASET_PATH}")

    corpus = pd.concat([df["resume_text"], df["job_description"]]).tolist()
    vectorizer = TfidfVectorizer(max_features=500, stop_words="english")
    vectorizer.fit(corpus)

    base_features, cosine_scores = _prepare_features(df, vectorizer)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(base_features)
    y_class = df["hired"].values

    x_train, x_test, y_train, y_test = train_test_split(
        X_scaled, y_class, test_size=0.2, random_state=RANDOM_SEED, stratify=y_class
    )

    classifier = LogisticRegression(max_iter=500, random_state=RANDOM_SEED)
    classifier.fit(x_train, y_train)
    y_pred = classifier.predict(x_test)

    # Continuous target derived from interpretable features for ranking use-cases.
    fit_score_target = (
        50 * cosine_scores
        + 30 * df["skill_match_score"].values
        + 12 * np.minimum(df["years_experience"].values / 10.0, 1.0)
        + 8 * (df["education_level"].values / 2.0)
    )
    fit_score_target = np.clip(fit_score_target, 0, 100)

    regressor = LinearRegression()
    regressor.fit(X_scaled, fit_score_target)

    tfidf_resume = vectorizer.transform(df["resume_text"].tolist())
    kmeans = KMeans(n_clusters=3, n_init=10, random_state=RANDOM_SEED)
    cluster_ids = kmeans.fit_predict(tfidf_resume)

    cluster_df = pd.DataFrame({"cluster": cluster_ids, "fit": fit_score_target})
    cluster_means = cluster_df.groupby("cluster")["fit"].mean().sort_values(ascending=False)
    ordered_clusters = cluster_means.index.tolist()
    cluster_map = {
        int(ordered_clusters[0]): "Strong Fit",
        int(ordered_clusters[1]): "Moderate Fit",
        int(ordered_clusters[2]): "Weak Fit",
    }

    with open(ARTIFACTS_DIR / "vectorizer.pkl", "wb") as f:
        pickle.dump(vectorizer, f)
    with open(ARTIFACTS_DIR / "classifier.pkl", "wb") as f:
        pickle.dump(classifier, f)
    with open(ARTIFACTS_DIR / "regressor.pkl", "wb") as f:
        pickle.dump(regressor, f)
    with open(ARTIFACTS_DIR / "scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)
    with open(ARTIFACTS_DIR / "kmeans.pkl", "wb") as f:
        pickle.dump(kmeans, f)
    with open(ARTIFACTS_DIR / "cluster_map.pkl", "wb") as f:
        pickle.dump(cluster_map, f)

    with open(ARTIFACTS_DIR / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "accuracy": accuracy_score(y_test, y_pred),
                "classification_report": classification_report(y_test, y_pred, output_dict=True),
                "cluster_distribution": pd.Series(cluster_ids).value_counts().sort_index().to_dict(),
            },
            f,
            indent=2,
        )

    print("Training complete")
    print(f"Accuracy: {accuracy_score(y_test, y_pred):.4f}")
    print("Classification report:")
    print(classification_report(y_test, y_pred))
    print("Cluster distribution:")
    print(pd.Series(cluster_ids).value_counts().sort_index())


if __name__ == "__main__":
    main()
