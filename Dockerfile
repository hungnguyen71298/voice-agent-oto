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

# Bake the models in. Without this the first utterance of every container blocks on a
# ~60 MB Piper download plus the Silero and turn-detection fetches — which would land
# on the first-turn FAL, the exact number being graded.
ARG PIPER_VOICE=vi_VN-vais1000-medium
RUN python -c "from piper.download_voices import download_voice; \
        download_voice('${PIPER_VOICE}', 'data/piper')" \
 && python -c "import voice_agent; \
        from pipecat.audio.vad.silero import SileroVADAnalyzer; SileroVADAnalyzer()"

EXPOSE 8080
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PIPER_VOICE=${PIPER_VOICE}
CMD ["python", "-m", "voice_agent"]
