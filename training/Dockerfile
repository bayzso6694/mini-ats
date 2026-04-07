FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir pandas==2.2.3 scikit-learn==1.6.1 numpy==2.2.3

COPY train.py /app/train.py
COPY dataset.csv /app/dataset.csv

CMD ["python", "train.py"]
