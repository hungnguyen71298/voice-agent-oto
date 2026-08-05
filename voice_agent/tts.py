"""Vietnamese text-to-speech, and the choice between two of them.

`build()` returns the engine named by `TTS_ENGINE`. See `config.py` for the measured
TTFB table that picked the default; the short version is that Piper runs locally and
Edge sounds better but is rate-limited by Microsoft.

Only `EdgeTTSService` is implemented here — Piper's is Pipecat's own.
"""
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass

import av
import edge_tts
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame
from pipecat.services.piper.tts import PiperTTSService
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts

from . import config

EDGE_SAMPLE_RATE = 24000  # audio-24khz-48kbitrate-mono-mp3, the only format Edge returns
_MAX_ATTEMPTS = 3


def build() -> TTSService:
    """Construct the TTS engine named by `TTS_ENGINE`.

    Piper downloads its voice model on first run (~60 MB) into `PIPER_DIR`.
    """
    if config.TTS_ENGINE == "edge":
        return EdgeTTSService(voice=config.EDGE_VOICE, rate=config.EDGE_RATE)
    if config.TTS_ENGINE != "piper":
        raise ValueError(f"TTS_ENGINE must be 'piper' or 'edge', got {config.TTS_ENGINE!r}")
    config.PIPER_DIR.mkdir(parents=True, exist_ok=True)
    # ponytail: the in-process `piper-tts` package is GPL-3.0. Fine for running and
    # evaluating this; if it ever ships inside a proprietary head unit, switch to
    # PiperHttpTTSService against a separately installed Piper server.
    return PiperTTSService(download_dir=config.PIPER_DIR, use_cuda=config.PIPER_CUDA,
                           settings=PiperTTSService.Settings(voice=config.PIPER_VOICE))


@dataclass
class EdgeTTSSettings(TTSSettings):
    """Settings for EdgeTTSService."""


class EdgeTTSService(TTSService):
    """Streaming Vietnamese TTS via Microsoft Edge's read-aloud voices.

    Voices: ``vi-VN-HoaiMyNeural`` (female), ``vi-VN-NamMinhNeural`` (male).
    """

    Settings = EdgeTTSSettings
    _settings: Settings

    def __init__(self, *, voice: str = "vi-VN-HoaiMyNeural", rate: str = "+0%", **kwargs):
        """Initialize the Edge TTS service.

        Args:
            voice: Edge voice short name.
            rate: Speaking rate as an SSML-style percentage, e.g. ``"+15%"``. Speeding
                the voice up shortens the utterance but does not change TTFB.
            **kwargs: Passed to `TTSService`.
        """
        super().__init__(push_start_frame=True, push_stop_frames=True,
                         settings=self.Settings(model=None, voice=voice, language=None), **kwargs)
        self._rate = rate

    def can_generate_metrics(self) -> bool:
        """Report that this service emits TTFB and usage metrics."""
        return True

    async def _pcm_chunks(self, text: str) -> AsyncIterator[bytes]:
        """Yield 16-bit mono PCM as the MP3 arrives, decoding incrementally.

        Decoding per network chunk rather than after the last one is the whole point:
        buffering the full MP3 first would hand back the 3.5 s behaviour of Gemini TTS.
        """
        decoder = av.CodecContext.create("mp3", "r")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=EDGE_SAMPLE_RATE)
        async for chunk in self._mp3_chunks(text):
            for packet in decoder.parse(chunk):
                for frame in decoder.decode(packet):
                    for out in resampler.resample(frame):
                        yield bytes(out.planes[0])
        for frame in decoder.decode(None):  # flush the decoder's internal delay
            for out in resampler.resample(frame):
                yield bytes(out.planes[0])

    async def _mp3_chunks(self, text: str) -> AsyncIterator[bytes]:
        """Yield raw MP3 from Edge, retrying a handshake that produced no audio.

        Measured roughly one failure per twenty utterances: the socket opens, Edge sends
        metadata, then closes without a single audio frame. Retrying is safe precisely
        because it happens before any audio has been yielded — the driver hears one
        slightly later answer instead of silence.
        """
        for attempt in range(_MAX_ATTEMPTS):
            got_audio = False
            try:
                comm = edge_tts.Communicate(text, self._settings.voice, rate=self._rate)
                async for chunk in comm.stream():
                    if chunk["type"] == "audio" and chunk["data"]:
                        got_audio = True
                        yield chunk["data"]
                return
            except edge_tts.exceptions.NoAudioReceived:
                if got_audio or attempt == _MAX_ATTEMPTS - 1:
                    raise
                logger.warning(f"{self}: Edge returned no audio, retry {attempt + 1}")

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        """Synthesize `text`, yielding audio frames as they decode.

        Args:
            text: Text to speak.
            context_id: Identifier Pipecat uses to discard frames after a barge-in.
        """
        try:
            await self.start_tts_usage_metrics(text)
            async for frame in self._stream_audio_frames_from_iterator(
                self._pcm_chunks(text), in_sample_rate=EDGE_SAMPLE_RATE, context_id=context_id
            ):
                await self.stop_ttfb_metrics()
                yield frame
        except Exception as e:
            # Never raise: a dead TTS turn must not take the pipeline down mid-drive.
            logger.error(f"{self} exception: {e}")
            yield ErrorFrame(error=f"Edge TTS failed: {e}")
        finally:
            await self.stop_ttfb_metrics()
