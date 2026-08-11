"""Microphone capture at the device's native rate, resampled in software.

Why this exists: asking PortAudio for 16 kHz mono from a 44.1 kHz four-channel array
makes the *driver* do the conversion, and on the Realtek array tested here it does it
badly enough to change what Whisper hears — "điều hòa" came back as "điện thoại",
"cửa sổ" as "cơ sổ". Capturing at the device's own rate and resampling with SoX keeps
the conversion under our control.

Silero VAD accepts only 8 kHz and 16 kHz and does not resample, so the conversion has
to happen before frames enter the pipeline — an `audio_in_filter` is too late, since it
rewrites the bytes but not the sample rate the frame declares.
"""
import asyncio

import pyaudio
from loguru import logger
from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import InputAudioRawFrame, StartFrame
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.transports.local.audio import (
    LocalAudioInputTransport,
    LocalAudioTransport,
    LocalAudioTransportParams,
)


def match_device(spec: str, devices) -> int | None:
    """First device whose name contains `spec`, ignoring case and output-only devices.

    Args:
        spec: substring of the device name.
        devices: `(index, name, max_input_channels)` triples.
    """
    spec = spec.lower()
    return next((i for i, name, channels in devices
                 if channels and spec in name.lower()), None)


def list_devices(py_audio) -> list[tuple[int, str, int]]:
    """`(index, name, max_input_channels)` for everything PortAudio can see."""
    infos = (py_audio.get_device_info_by_index(i)
             for i in range(py_audio.get_device_count()))
    return [(int(d["index"]), d["name"], int(d["maxInputChannels"])) for d in infos]


def resolve_device(spec: str | None) -> int | None:
    """`config.INPUT_DEVICE` → a PortAudio index. None means the system default.

    Names are resolved at startup rather than baked into `.env` as an index, because
    the index moves between boots and the failure is silent-ish: PortAudio reports
    `Invalid number of channels` for the speaker that took the number over.
    """
    if spec is None or (spec := str(spec).strip()).isdigit():
        return int(spec) if spec else None
    py_audio = pyaudio.PyAudio()
    try:
        index = match_device(spec, list_devices(py_audio))
    finally:
        py_audio.terminate()
    if index is None:
        raise SystemExit(f"INPUT_DEVICE={spec!r} matches no input device.\n"
                         "  python scripts/mic.py   lists every device and its level")
    return index


class NativeRateAudioInput(LocalAudioInputTransport):
    """Capture at `capture_rate`, hand the pipeline `audio_in_sample_rate`."""

    def __init__(self, py_audio, params: LocalAudioTransportParams, capture_rate: int):
        super().__init__(py_audio, params)
        self._capture_rate = capture_rate
        self._resampler = create_stream_resampler()
        self._raw: asyncio.Queue = asyncio.Queue()
        self._resampler_task = None

    async def start(self, frame: StartFrame):
        """Open the device at its native rate rather than the pipeline's."""
        await super(LocalAudioInputTransport, self).start(frame)  # skip the base's open()
        if self._in_stream:
            return
        self._pipeline_rate = self._sample_rate
        logger.info(f"Mic: capturing {self._capture_rate} Hz → {self._pipeline_rate} Hz")
        self._in_stream = self._py_audio.open(
            format=self._py_audio.get_format_from_width(2),
            channels=self._params.audio_in_channels,
            rate=self._capture_rate,
            frames_per_buffer=int(self._capture_rate / 100) * 2,  # 20 ms
            stream_callback=self._audio_in_callback,
            input=True,
            input_device_index=self._params.input_device_index,
        )
        self._resampler_task = self.create_task(self._resample_task())
        self._in_stream.start_stream()
        await self.set_transport_ready(frame)

    async def cleanup(self):
        """Stop the resampler task before the base class closes the stream."""
        if self._resampler_task:
            await self.cancel_task(self._resampler_task)
            self._resampler_task = None
        await super().cleanup()

    def _audio_in_callback(self, in_data, frame_count, time_info, status):
        """PortAudio calls this from its own thread; queue the bytes for the loop.

        Queue rather than `run_coroutine_threadsafe` per chunk: the resampler carries
        state across calls, so two coroutines resampling concurrently interleave into
        it and the audio comes out scrambled. That is not theoretical — it turned
        every transcript into nonsense before this was a queue.
        """
        self.get_event_loop().call_soon_threadsafe(self._raw.put_nowait, in_data)
        return (None, pyaudio.paContinue)

    async def _resample_task(self):
        """The single consumer. One resampler, one caller, order preserved."""
        while True:
            raw = await self._raw.get()
            audio = await self._resampler.resample(raw, self._capture_rate,
                                                   self._pipeline_rate)
            if audio:
                await self.push_audio_frame(InputAudioRawFrame(
                    audio=audio, sample_rate=self._pipeline_rate,
                    num_channels=self._params.audio_in_channels))


class NativeRateAudioTransport(LocalAudioTransport):
    """`LocalAudioTransport` whose input captures at the device's native rate."""

    def __init__(self, params: LocalAudioTransportParams, capture_rate: int):
        super().__init__(params)
        self._capture_rate = capture_rate

    def input(self) -> FrameProcessor:
        """Build the input transport, capturing at the native rate."""
        if not self._input:
            self._input = NativeRateAudioInput(self._pyaudio, self._params,
                                               self._capture_rate)
        return self._input
