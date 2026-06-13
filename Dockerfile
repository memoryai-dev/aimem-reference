FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server

EXPOSE 9420

CMD ["sh", "-c", "uvicorn server.main:app --host ${AIMEM_HOST:-0.0.0.0} --port ${AIMEM_PORT:-9420}"]
