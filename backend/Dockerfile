FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY ai_core /app/ai_core

EXPOSE 8000

CMD ["sh", "-c", "if [ \"${NO_HIGH_QUALITY:-0}\" = \"1\" ]; then python init_db.py --no-high-quality; else python init_db.py; fi && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
