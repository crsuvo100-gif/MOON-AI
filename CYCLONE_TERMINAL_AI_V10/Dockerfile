# MOON-AI Docker — auto-generated for [python]
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-optional.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-optional.txt

COPY . .
RUN pip install --no-cache-dir -e .

ENV MOON_PORT=8777
ENV PYTHONUNBUFFERED=1

EXPOSE 8777

CMD ["./.venv/bin/python", "main.py", "terminal"]
