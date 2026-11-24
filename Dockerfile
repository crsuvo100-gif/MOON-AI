# MOON-AI Docker — auto-generated for [python]
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-optional.txt pyproject.toml ./
# Core deps are mandatory. Optional extras are best-effort: MOON degrades
# gracefully when voice/vision/cloud extras are unavailable, and several of
# them (pyaudio, f5-tts, torch) need build toolchains absent from slim images.
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements-optional.txt || true

COPY . .
RUN pip install --no-cache-dir -e .

ENV MOON_PORT=8777
ENV PYTHONUNBUFFERED=1

EXPOSE 8777

# `pip install -e .` installs into the system interpreter (no .venv in image).
CMD ["python", "main.py", "terminal"]
