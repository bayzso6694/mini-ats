# Backend

FastAPI + SQLAlchemy + Celery worker integration.

Key files:
- `main.py`: app startup, routers, CORS, WebSocket endpoint, Redis pub/sub listener
- `models.py`: Job and Candidate tables
- `routers/jobs.py`: job CRUD endpoints
- `routers/candidates.py`: resume upload and ranking endpoints
- `worker/tasks.py`: async PDF parsing + scoring task

Run with Docker Compose from project root.
