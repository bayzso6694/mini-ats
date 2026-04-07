import json
import os
import pickle
import re
import string
from pathlib import Path

import numpy as np
import pdfplumber
import redis
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Candidate, Job
from worker.celery_app import celery

ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "/artifacts"))
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "/uploads"))
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
PUBSUB_CHANNEL = os.getenv("RANKING_CHANNEL", "ranking_updates")


def _clean_text(text: str) -> str:
    table = str.maketrans("", "", string.punctuation)
    return " ".join(text.lower().translate(table).split())


def _extract_pdf_text(path: Path) -> str:
    chunks = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n".join(chunks).strip()


def _extract_years(text: str) -> float:
    matches = re.findall(r"(\d{1,2})\s*\+?\s*years", text.lower())
    if not matches:
        return 0.0
    return float(max(int(m) for m in matches))


def _extract_education_level(text: str) -> int:
    lowered = text.lower()
    if "phd" in lowered or "doctorate" in lowered:
        return 2
    if "master" in lowered or "m.s" in lowered or "mba" in lowered:
        return 1
    if "bachelor" in lowered or "b.s" in lowered or "btech" in lowered:
        return 0
    return 0


def _skill_match_score(job_skills_text: str, resume_text: str) -> float:
    job_skills = {
        skill.strip().lower()
        for skill in re.split(r"[,;|]", job_skills_text)
        if skill.strip()
    }
    if not job_skills:
        return 0.0
    resume_tokens = set(re.findall(r"[a-zA-Z0-9\-\+\.]+", resume_text.lower()))
    overlap = len(job_skills.intersection(resume_tokens))
    return overlap / len(job_skills)


def _load_artifacts() -> dict:
    artifact_files = {
        "vectorizer": "vectorizer.pkl",
        "classifier": "classifier.pkl",
        "regressor": "regressor.pkl",
        "scaler": "scaler.pkl",
        "kmeans": "kmeans.pkl",
        "cluster_map": "cluster_map.pkl",
    }
    loaded = {}
    for key, filename in artifact_files.items():
        with open(ARTIFACTS_DIR / filename, "rb") as f:
            loaded[key] = pickle.load(f)
    return loaded


def _publish_update(job_id: int, candidate_id: int, status: str) -> None:
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    payload = {
        "event": "ranking_updated",
        "job_id": job_id,
        "candidate_id": candidate_id,
        "status": status,
    }
    client.publish(PUBSUB_CHANNEL, json.dumps(payload))


@celery.task(name="score_resume")
def score_resume(candidate_id: int, job_id: int) -> dict:
    db: Session = SessionLocal()
    try:
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        job = db.query(Job).filter(Job.id == job_id).first()

        if not candidate or not job:
            return {"ok": False, "reason": "candidate_or_job_not_found"}

        pdf_path = UPLOADS_DIR / candidate.resume_filename
        if not pdf_path.exists():
            candidate.status = "error"
            db.commit()
            _publish_update(job_id, candidate_id, "error")
            return {"ok": False, "reason": "pdf_not_found"}

        try:
            raw_text = _extract_pdf_text(pdf_path)
            cleaned_text = _clean_text(raw_text)
        except Exception:
            candidate.status = "error"
            db.commit()
            _publish_update(job_id, candidate_id, "error")
            return {"ok": False, "reason": "pdf_parse_failed"}

        artifacts = _load_artifacts()

        vectorizer = artifacts["vectorizer"]
        classifier = artifacts["classifier"]
        regressor = artifacts["regressor"]
        scaler = artifacts["scaler"]
        kmeans = artifacts["kmeans"]
        cluster_map = artifacts["cluster_map"]

        resume_vec = vectorizer.transform([cleaned_text])
        job_vec = vectorizer.transform([_clean_text(job.description)])
        cos_sim = float(cosine_similarity(resume_vec, job_vec)[0][0])

        skill_score = float(_skill_match_score(job.required_skills, cleaned_text))
        years_exp = float(_extract_years(cleaned_text))
        edu_level = int(_extract_education_level(cleaned_text))

        features = np.array([[cos_sim, skill_score, years_exp, edu_level]])
        scaled = scaler.transform(features)

        hire_probability = float(classifier.predict_proba(scaled)[0][1])
        fit_score = float(np.clip(regressor.predict(scaled)[0], 0, 100))

        cluster_id = int(kmeans.predict(resume_vec)[0])
        cluster_label = str(cluster_map.get(cluster_id, "Moderate Fit"))

        candidate.resume_text = cleaned_text
        candidate.hire_probability = hire_probability
        candidate.fit_score = fit_score
        candidate.cluster_label = cluster_label
        candidate.status = "scored"
        db.commit()

        _publish_update(job_id, candidate_id, "scored")
        return {
            "ok": True,
            "candidate_id": candidate_id,
            "job_id": job_id,
            "fit_score": fit_score,
            "hire_probability": hire_probability,
            "cluster_label": cluster_label,
        }
    except Exception as exc:
        db.rollback()
        if db.query(Candidate).filter(Candidate.id == candidate_id).first():
            candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
            candidate.status = "error"
            db.commit()
            _publish_update(job_id, candidate_id, "error")
        return {"ok": False, "reason": str(exc)}
    finally:
        db.close()
