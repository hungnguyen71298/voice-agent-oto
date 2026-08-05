"""Drive the real pipeline end to end with recorded speech instead of a microphone.

    python scripts/e2e.py                    # run the scripted conversation
    python scripts/e2e.py --keep-audio out   # also write what the agent said to out/

This is not `bench.py`. Bench times the three network calls by hand; this builds the
actual Pipecat pipeline from `app.build_task()` — same VAD, same turn detection, same
tool dispatch, same LatencyProbe, same dashboard events — and only swaps the microphone
and speaker for files. What it proves is that the product works, not that the APIs do.

Audio is fed in real time on purpose. Pushing it faster would make Silero see the end of
each utterance early, and the FAL printed here would be a number no driver could get.

Exit code is 0 only if every checked behaviour held, so this doubles as a smoke test
before a demo.
"""
import argparse
import asyncio
import pathlib
import sys
import time
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from pipecat.frames.frames import (  # noqa: E402
    EndFrame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    StartFrame,
)
from pipecat.transports.base_input import BaseInputTransport  # noqa: E402
from pipecat.transports.base_output import BaseOutputTransport  # noqa: E402
from pipecat.transports.base_transport import BaseTransport  # noqa: E402

from voice_agent import app, config, ui  # noqa: E402
from voice_agent.tools import vehicle  # noqa: E402

SAMPLE_RATE = 16000
CHUNK_MS = 20
TRAILING_SILENCE_S = 1.6  # long enough for Silero to call the turn over

# Each turn declares what it proves, and `check(turn)` decides whether it did. The turn
# it receives carries the tools that ran and what the agent said, both taken from the
# dashboard event stream — so a turn cannot pass by accident, the way "no window opened"
# passed while the agent was actually searching the internet for a misheard phrase.
CONVERSATION = [
    ("Bật điều hòa hai mươi tư độ", "điều khiển thiết bị",
     lambda t: "set_ac" in t.tools and vehicle.STATE["ac"] == {"on": True, "temp": 24}),

    ("Giảm thêm hai độ nữa", "tham chiếu ngữ cảnh lượt trước",
     lambda t: "adjust_ac_temperature" in t.tools and vehicle.STATE["ac"]["temp"] == 22),

    ("Mở cửa sổ", "hỏi lại khi thiếu thông tin",
     lambda t: not t.tools and "?" in t.said and vehicle.STATE["window"]["driver"] == 0),

    ("Ghế lái", "hiểu câu trả lời cho câu hỏi lại",
     lambda t: "set_window" in t.tools and vehicle.STATE["window"]["driver"] > 0),

    ("Áp suất lốp bao nhiêu là đúng", "tra sổ tay",
     lambda t: "search_manual" in t.tools and len(t.said) > 20),
]


class Turn:
    """What actually happened during one utterance, read off the dashboard event bus."""

    def __init__(self):
        self.tools: list[str] = []
        self.said = ""
        self.heard = ""
        self.replied = False

    def absorb(self, event: dict):
        if event["kind"] == "tool":
            self.tools.append(event["name"])
        elif event["kind"] == "bot":
            self.said += (" " if self.said else "") + event["text"]
        elif event["kind"] == "user":
            self.heard = event["text"]


class FileAudioInput(BaseInputTransport):
    """A microphone that is really a WAV file.

    Subclasses the same base the local transport uses, so VAD, turn detection and
    interruption behave exactly as they do live — only the capture device is gone.
    """

    async def start(self, frame: StartFrame):
        await super().start(frame)
        # The base class only builds its audio queue and VAD task once the transport
        # declares itself ready — the local transport does that after opening PortAudio.
        # Without this line, push_audio_frame raises AttributeError and takes the
        # pipeline down with it.
        await self.set_transport_ready(frame)

    async def feed(self, pcm: bytes, sample_rate: int):
        """Push `pcm` in at the speed a microphone would deliver it."""
        step = sample_rate * CHUNK_MS // 1000 * 2
        for offset in range(0, len(pcm), step):
            await self.push_audio_frame(InputAudioRawFrame(
                audio=pcm[offset:offset + step], sample_rate=sample_rate, num_channels=1))
            await asyncio.sleep(CHUNK_MS / 1000)

    async def silence(self, seconds: float, sample_rate: int):
        await self.feed(b"\x00" * int(sample_rate * seconds) * 2, sample_rate)


class CapturedAudioOutput(BaseOutputTransport):
    """A speaker that is really a buffer."""

    def __init__(self, params, **kwargs):
        super().__init__(params, **kwargs)
        self.spoken: list[bytes] = []

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self.set_transport_ready(frame)

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        self.spoken.append(frame.audio)
        return True


class FileTransport(BaseTransport):
    """Pairs the two above so `app.build_task()` can use it like any other transport."""

    def __init__(self, params):
        super().__init__()
        self._in = FileAudioInput(params)
        self._out = CapturedAudioOutput(params)

    def input(self):
        return self._in

    def output(self):
        return self._out


DRIVER_AUDIO = pathlib.Path(__file__).resolve().parent.parent / "data" / "samples" / "e2e"


async def say(text: str, index: int) -> bytes:
    """Render one line of the driver's speech to 16 kHz PCM, cached on disk.

    Cached because this is the test's *input*: it has to be byte-identical on every run
    and available offline. Commit the WAVs and the run stops depending on any TTS at all.

    Edge first, Piper as fallback. Piper is fine for long sentences but Whisper hears its
    short ones as nonsense — "Mở cửa sổ" came back as "Phương Cư Thủ" — which fails the
    run for a reason that has nothing to do with the agent.
    """
    cached = DRIVER_AUDIO / f"driver-{index:02d}.wav"
    if cached.exists():
        with wave.open(str(cached), "rb") as w:
            return w.readframes(w.getnframes())

    cached.parent.mkdir(parents=True, exist_ok=True)
    try:
        from voice_agent.tts import EDGE_SAMPLE_RATE, EdgeTTSService
        edge = EdgeTTSService(voice=config.EDGE_VOICE)
        edge._sample_rate = EDGE_SAMPLE_RATE
        raw = b"".join([c async for c in edge._pcm_chunks(text)])
        pcm = downsample(raw, EDGE_SAMPLE_RATE, SAMPLE_RATE)
    except Exception as e:
        print(f"   (Edge unavailable: {type(e).__name__}; using Piper)", flush=True)
        from piper import PiperVoice
        voice = PiperVoice.load(config.PIPER_DIR / f"{config.PIPER_VOICE}.onnx")
        raw = b"".join(c.audio_int16_bytes for c in voice.synthesize(text))
        pcm = downsample(raw, voice.config.sample_rate, SAMPLE_RATE)

    write_wav(cached, pcm, SAMPLE_RATE)
    return pcm


def downsample(pcm: bytes, src: int, dst: int) -> bytes:
    """Nearest-neighbour resample. Good enough: Silero and Whisper both tolerate it."""
    import array
    samples = array.array("h")
    samples.frombytes(pcm)
    ratio = src / dst
    out = array.array("h", (samples[min(int(i * ratio), len(samples) - 1)]
                            for i in range(int(len(samples) / ratio))))
    return out.tobytes()


def write_wav(path: pathlib.Path, pcm: bytes, rate: int):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


async def main(keep_audio: pathlib.Path | None) -> int:
    if not config.OPENROUTER_KEY:
        sys.exit("OPENROUTER_API_KEY is missing or still the placeholder.\n"
                 "  cp .env.example .env   then paste a real key from https://openrouter.ai/keys")

    print(f"STT={config.STT_MODEL}  LLM={config.LLM_MODEL}  "
          f"TTS={config.TTS_ENGINE}/{config.PIPER_VOICE}\n", flush=True)
    print("Rendering the driver's lines...", flush=True)
    lines = [(text, why, check, await say(text, i))
             for i, (text, why, check) in enumerate(CONVERSATION)]

    transport = FileTransport(app.transport_params())
    task, probe = app.build_task(transport=transport)
    runner = asyncio.create_task(app.run_task(task, auto_end=False))
    await asyncio.sleep(3)  # let the pipeline reach StartFrame before speaking into it

    # Listening on the same bus the browser uses also proves the dashboard feed works.
    events: asyncio.Queue = asyncio.Queue()
    ui._clients.append(events)

    failures = []
    for text, why, check, pcm in lines:
        spoken_before = len(transport._out.spoken)
        samples_before = len(probe.samples)
        print(f"\n🎤 {text}", flush=True)
        await transport._in.feed(pcm, SAMPLE_RATE)
        await transport._in.silence(TRAILING_SILENCE_S, SAMPLE_RATE)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and len(probe.samples) == samples_before:
            await asyncio.sleep(0.1)
        await asyncio.sleep(2.5)  # let the reply finish before the next line starts

        turn = Turn()
        while not events.empty():
            turn.absorb(events.get_nowait())
        turn.replied = len(transport._out.spoken) > spoken_before
        measured = len(probe.samples) > samples_before
        ok = measured and turn.replied and check(turn)
        print(f"   nghe: {turn.heard or '—'}", flush=True)
        print(f"   nói : {turn.said or '—'}", flush=True)
        print(f"   tool: {', '.join(turn.tools) or '—'}", flush=True)
        print(f"   xe  : {vehicle.describe_state()}", flush=True)
        print(f"   {'✅' if ok else '❌'} {why}"
              f"{'' if measured else '  (không đo được FAL)'}"
              f"{'' if turn.replied else '  (không phát ra tiếng)'}", flush=True)
        if not ok:
            failures.append(why)

    await task.queue_frame(EndFrame())
    await asyncio.wait_for(runner, timeout=20)

    if keep_audio:
        keep_audio.mkdir(parents=True, exist_ok=True)
        write_wav(keep_audio / "agent.wav", b"".join(transport._out.spoken),
                  transport._out.sample_rate or 24000)
        write_wav(keep_audio / "driver.wav",
                  b"".join(pcm for _, _, _, pcm in lines), SAMPLE_RATE)
        print(f"\nAudio: {keep_audio}/driver.wav, {keep_audio}/agent.wav")

    if summary := probe.summary():
        print(f"\nFAL n={summary['n']}  p50={summary['p50']:.0f}ms  "
              f"p95={summary['p95']:.0f}ms  max={summary['max']:.0f}ms")
    print(f"{len(CONVERSATION) - len(failures)}/{len(CONVERSATION)} lượt đạt"
          + (f" — hỏng: {failures}" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--keep-audio", type=pathlib.Path, metavar="DIR",
                   help="write driver.wav and agent.wav here")
    sys.exit(asyncio.run(main(p.parse_args().keep_audio)))
