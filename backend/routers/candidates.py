import json
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
import redis
from sqlalchemy.orm import Session

from database import get_db
from models import Candidate, Job
from schemas import CandidateResponse, ShortlistDecisionUpdate
from worker.tasks import score_resume

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "/uploads"))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
PUBSUB_CHANNEL = os.getenv("RANKING_CHANNEL", "ranking_updates")

router = APIRouter(prefix="/candidates", tags=["candidates"])


def _publish_update(job_id: int, candidate_id: int, status: str, event: str = "ranking_updated") -> None:
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    payload = {
        "event": event,
        "job_id": job_id,
        "candidate_id": candidate_id,
        "status": status,
    }
    client.publish(PUBSUB_CHANNEL, json.dumps(payload))


@router.post("/upload", response_model=CandidateResponse)
def upload_candidate_resume(
    job_id: int = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", file.filename)
    stored_filename = f"{uuid.uuid4()}_{safe_name}"
    destination = UPLOADS_DIR / stored_filename

    with open(destination, "wb") as out:
        out.write(file.file.read())

    candidate = Candidate(
        job_id=job_id,
        name=name,
        email=email,
        resume_filename=stored_filename,
        status="pending",
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)

    score_resume.delay(candidate.id, job_id)
    return candidate


@router.get("/{job_id}", response_model=list[CandidateResponse])
def list_candidates(job_id: int, db: Session = Depends(get_db)):
    return (
        db.query(Candidate)
        .filter(Candidate.job_id == job_id)
        .order_by(Candidate.fit_score.desc().nullslast(), Candidate.created_at.asc())
        .all()
    )


@router.get("/{job_id}/rankings")
def ranked_candidates(job_id: int, db: Session = Depends(get_db)):
    candidates = (
        db.query(Candidate)
        .filter(Candidate.job_id == job_id)
        .order_by(Candidate.fit_score.desc().nullslast(), Candidate.created_at.asc())
        .all()
    )
    ranked = []
    for idx, c in enumerate(candidates, start=1):
        ranked.append(
            {
                "rank": idx,
                "id": c.id,
                "name": c.name,
                "email": c.email,
                "fit_score": c.fit_score,
                "hire_probability": c.hire_probability,
                "cluster_label": c.cluster_label,
                "status": c.status,
                "shortlist_status": c.shortlist_status,
            }
        )
    return ranked


@router.patch("/{candidate_id}/shortlist", response_model=CandidateResponse)
def update_shortlist_decision(
    candidate_id: int,
    payload: ShortlistDecisionUpdate,
    db: Session = Depends(get_db),
):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    candidate.shortlist_status = payload.decision
    db.commit()
    db.refresh(candidate)

    _publish_update(
        job_id=candidate.job_id,
        candidate_id=candidate.id,
        status=candidate.status,
        event="shortlist_updated",
    )
    return candidate
