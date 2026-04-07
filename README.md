# Mini ATS (Dockerized)

A complete mini Applicant Tracking System that supports:
- Job creation by recruiters
- Multi-PDF resume uploads
- Asynchronous parsing and scoring
- Live ranking updates over WebSocket
- Recruiter shortlist/reject decisions from dashboard
- Reproducible full-stack run via Docker Compose

## Architecture

```text
              +-------------------+
              |  training service |
              |   train.py        |
              +---------+---------+
                        |
                        | writes .pkl artifacts
                        v
+-----------+      +----+-----------------+      +-------------------+
| frontend  | <--> | FastAPI backend      | <--> | PostgreSQL        |
| (nginx)   | HTTP | REST + WebSocket     |      | jobs/candidates   |
+-----------+      +----+-----------------+      +-------------------+
                        |
                        | enqueue score task
                        v
                 +------+------+
                 | Celery worker|
                 | PDF parse +  |
                 | ML scoring   |
                 +------+------+
                        |
                        | broker + pub/sub
                        v
                     +--+--+
                     |Redis|
                     +-----+
```

## ML Models Used

| Model | Type | Purpose | Artifact |
|---|---|---|---|
| TF-IDF Vectorizer | Text featurization | Convert JD and resume text to vectors | `vectorizer.pkl` |
| Logistic Regression | Classification | Predict hire probability (0-1) | `classifier.pkl` |
| Linear Regression | Regression | Predict fit score (0-100) | `regressor.pkl` |
| KMeans (k=3) | Clustering | Segment candidates into fit tiers | `kmeans.pkl` + `cluster_map.pkl` |
| StandardScaler | Feature scaling | Normalize numeric feature vector | `scaler.pkl` |

Features used for supervised models:
- cosine similarity (JD vs resume TF-IDF)
- skill match score
- years of experience
- education level

## Project Structure

```text
project/
  training/
    train.py
    dataset.csv
    Dockerfile
    artifacts/
  backend/
    main.py
    database.py
    models.py
    schemas.py
    Dockerfile
    requirements.txt
    routers/
      jobs.py
      candidates.py
    worker/
      celery_app.py
      tasks.py
  frontend/
    index.html
    style.css
    app.js
  docker-compose.yml
  README.md
```

## Run Everything

```bash
docker-compose up --build
```

Services:
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API docs: http://localhost:8000/docs

## How to Use

1. Open frontend at http://localhost:3000
2. Create a job in the Create Job section
3. In Upload Resumes:
   - Select the job
   - Enter candidate name and email base
   - Select multiple PDF files
   - Upload
4. Open Live Rankings section:
   - Select same job
   - Watch table auto-refresh when scoring completes

Status flow:
- `pending` -> candidate queued/scoring in progress
- `scored` -> candidate scored and ranked
- `error` -> parse/processing failure

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/jobs` | Create a job |
| GET | `/jobs` | List jobs |
| GET | `/jobs/{job_id}` | Get one job with candidates |
| POST | `/candidates/upload` | Upload one resume and queue scoring |
| GET | `/candidates/{job_id}` | List candidates for job ordered by fit score |
| GET | `/candidates/{job_id}/rankings` | Ranked response for dashboard |
| PATCH | `/candidates/{candidate_id}/shortlist` | Update shortlist decision (`none`/`shortlisted`/`rejected`) |
| WS | `/ws/{job_id}` | Live ranking updates |

## Notes

- `training` auto-generates `dataset.csv` with 500 synthetic rows if it is missing.
- Artifacts are saved in shared Docker volume `artifacts` and consumed by backend/worker.
- Uploaded PDFs are stored in shared Docker volume `uploads`.
- Worker parses PDFs with `pdfplumber` and updates DB asynchronously.

## Troubleshooting

- If backend starts before artifacts are available, check training logs:
  ```bash
  docker-compose logs training
  ```
- To inspect worker scoring:
  ```bash
  docker-compose logs -f worker
  ```
- To reset everything including volumes:
  ```bash
  docker-compose down -v
  ```
