FROM python:3.12-slim

# portaudio: required by sounddevice (mic/speaker). ffmpeg: used by pipecat to resample.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libportaudio2 ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY voice_agent/ voice_agent/
COPY data/ data/
COPY scripts/ scripts/

ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
CMD ["python", "-m", "voice_agent"]
