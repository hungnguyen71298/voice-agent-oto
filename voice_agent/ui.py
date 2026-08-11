"""Live demo dashboard: a web page fed by server-sent events.

The microphone stays on the machine running the pipeline. This serves a read-only
view of what the agent is doing — transcript, tool calls, vehicle state, FAL — so a
demo can be projected without anyone squinting at a terminal.

Deliberately one-way. Putting the browser in the audio path would add a network hop
to the number the brief grades, so the page observes and never participates. That
also means SSE is enough and no WebSocket library is needed; aiohttp already ships
with Pipecat.
"""
import asyncio
import contextlib
import json

from aiohttp import web
from loguru import logger
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    TranscriptionFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from . import config
from .tools.vehicle import STATE

STATIC = config.ROOT / "voice_agent" / "static"

_clients: list[asyncio.Queue] = []
_on_reset = None  # set by app.py; the page cannot reach vehicle state or the LLM context
_history: list[dict] = []
_MAX_HISTORY = 60  # a browser opened mid-demo should see the conversation so far


def emit(kind: str, **data) -> None:
    """Broadcast one event to every open page. Safe to call when nobody is watching."""
    event = {"kind": kind, **data}
    if kind not in ("state", "reset", "mic"):  # snapshots and one-shot signals are not history
        _history.append(event)
        del _history[:-_MAX_HISTORY]
    for q in _clients:
        # put_nowait, not await: a stalled browser tab must never block the audio
        # pipeline. An overflowing queue drops events for that tab alone.
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(event)


def emit_state() -> None:
    """Push the current vehicle state. Called after anything that can change it."""
    emit("state", **STATE)


def summarise(result: dict) -> str:
    """One line describing a tool result, for the dashboard.

    Tool results have no common shape — control tools return `speech`, errors return
    `message`, and `search_manual` returns only `results`. Indexing any single key here
    crashed the pipeline on the first knowledge-base question.
    """
    if speech := result.get("speech"):
        return speech
    if message := result.get("message"):
        return message
    if (hits := result.get("results")) is not None:
        return f"{len(hits)} kết quả" if hits else "không tìm thấy"
    return result.get("status", "ok")


class UIProbe(FrameProcessor):
    """Turn pipeline frames into dashboard events.

    Sits at the tail of the pipeline, where both the transcript coming down from STT
    and the spoken text coming out of TTS have already passed through.
    """

    def __init__(self):
        super().__init__()
        self._said = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, UserStartedSpeakingFrame):
            emit("listening")
        elif isinstance(frame, TranscriptionFrame):
            emit("user", text=frame.text)
        elif isinstance(frame, TTSTextFrame):
            self._said += frame.text
        elif isinstance(frame, BotStoppedSpeakingFrame):
            if self._said.strip():
                emit("bot", text=self._said.strip())
            self._said = ""
        elif isinstance(frame, InterruptionFrame):
            # Pipecat broadcasts one of these every time the user starts speaking, even
            # into silence, to flush whatever is queued. Only a non-empty `_said` means
            # the bot really was mid-sentence — that is the barge-in worth showing.
            if self._said.strip():
                emit("interrupted")
            self._said = ""
        await self.push_frame(frame, direction)


_muted = False


class MicGate(FrameProcessor):
    """Drops microphone audio while muted. Sits between the transport and the VAD.

    Dropping here rather than closing the device keeps the pipeline, the dashboard and
    the conversation context alive — unmuting is instant and nothing is rebuilt. VAD
    sees no audio at all, so a muted mic cannot trigger a turn: worth having because
    Whisper invents text out of room noise (it returns YouTube sign-off lines it learnt
    from subtitles), and that costs an API call for something nobody said.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if _muted and isinstance(frame, InputAudioRawFrame):
            return
        await self.push_frame(frame, direction)


# Whisper learnt Vietnamese from subtitles, so handed near-silence it returns the
# sign-off lines that end a video. Match whole phrases only: "theo dõi" on its own would
# also swallow "hệ thống theo dõi áp suất lốp", which is a real question about this car.
# ponytail: a phrase not on this list still gets through — upgrade is a wake word, or an
# energy gate in front of STT. The dashboard mute button covers the gap meanwhile.
HALLUCINATIONS = (
    "cảm ơn các bạn đã theo dõi",
    "hẹn gặp lại",
    "đăng ký kênh",
    "ghiền mì gõ",
    "subscribe",
    "bỏ lỡ những video",
)


def is_hallucination(text: str) -> bool:
    """True for subtitle boilerplate no driver ever says to a car."""
    return any(phrase in text.lower() for phrase in HALLUCINATIONS)


class SilenceFilter(FrameProcessor):
    """Drops what Whisper invented out of silence, before it becomes a turn.

    Sits between STT and the aggregator. The transcription is already paid for by then,
    but the turn never opens: no LLM call, no reply read aloud, nothing on the dashboard.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and is_hallucination(frame.text):
            logger.info(f"Bỏ câu Whisper tự bịa lúc im lặng: {frame.text!r}")
            return
        await self.push_frame(frame, direction)


async def _mic(_request: web.Request) -> web.Response:
    """Toggle the microphone from the dashboard."""
    global _muted
    _muted = not _muted
    emit("mic", muted=_muted)
    print(f"  🎙 mic {'tắt' if _muted else 'bật'}", flush=True)
    return web.json_response({"muted": _muted})


def set_reset_handler(handler) -> None:
    """Register what the dashboard's reset button should do."""
    global _on_reset
    _on_reset = handler


async def _reset(_request: web.Request) -> web.Response:
    """Start the demo over: vehicle state, conversation history, and the page.

    Resetting only the page would be worse than no button at all — the agent would
    still remember the previous turns while the screen claimed a fresh start.
    """
    _history.clear()
    if _on_reset:
        await _on_reset()
    emit("reset")
    emit_state()
    return web.json_response({"ok": True})


async def _events(request: web.Request) -> web.StreamResponse:
    """SSE stream. One queue per connected page."""
    response = web.StreamResponse(headers={
        "Content-Type": "text/event-stream", "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no"})  # tells any reverse proxy not to buffer the stream
    await response.prepare(request)
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    _clients.append(queue)
    try:
        for event in [*_history, {"kind": "state", **STATE}, {"kind": "mic", "muted": _muted}]:
            await response.write(f"data: {json.dumps(event)}\n\n".encode())
        while True:
            event = await queue.get()
            await response.write(f"data: {json.dumps(event)}\n\n".encode())
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        _clients.remove(queue)
    return response


async def start(port: int, host: str = "127.0.0.1") -> web.AppRunner | None:
    """Serve the dashboard in the background. Returns None if `port` is 0."""
    if not port:
        return None
    app = web.Application()
    app.router.add_get("/events", _events)
    app.router.add_post("/reset", _reset)
    app.router.add_post("/mic", _mic)
    # No-cache: the page is edited during a demo and a stale copy from the browser
    # cache looks exactly like a feature that was never added.
    app.router.add_get("/", lambda _: web.FileResponse(
        STATIC / "index.html", headers={"Cache-Control": "no-store"}))
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    logger.info(f"Dashboard on http://{host}:{port}")
    return runner
