"""Dashboard event bus and UIProbe.

The dashboard is a demo aid, but it sits inside the audio pipeline, so the thing worth
testing is that it can never hurt the pipeline: no swallowed frames, no exception from
a stalled browser tab.
"""
import asyncio

import pytest
from pipecat.frames.frames import (
    AggregationType,
    BotStoppedSpeakingFrame,
    InterruptionFrame,
    TranscriptionFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from voice_agent import ui


@pytest.fixture(autouse=True)
def clean_bus():
    """Module-level client list and history leak between tests otherwise."""
    ui._clients.clear()
    ui._history.clear()
    yield
    ui._clients.clear()
    ui._history.clear()


def drain(queue: asyncio.Queue) -> list[dict]:
    return [queue.get_nowait() for _ in range(queue.qsize())]


def said(text: str) -> TTSTextFrame:
    """A chunk of text on its way to the speaker."""
    return TTSTextFrame(text=text, aggregated_by=AggregationType.WORD)


# --- event bus -----------------------------------------------------------------------

def test_emit_reaches_every_client():
    a, b = asyncio.Queue(), asyncio.Queue()
    ui._clients += [a, b]
    ui.emit("user", text="xin chào")
    assert drain(a) == drain(b) == [{"kind": "user", "text": "xin chào"}]


def test_emit_without_clients_does_not_raise():
    """The pipeline runs fine with nobody watching."""
    ui.emit("user", text="xin chào")


def test_a_stalled_client_cannot_block_the_pipeline():
    """A browser tab that stopped reading must lose events, not stall the audio path."""
    full = asyncio.Queue(maxsize=1)
    ui._clients.append(full)
    for i in range(50):
        ui.emit("user", text=str(i))  # must not raise
    assert full.qsize() == 1


def test_history_lets_a_late_page_catch_up():
    ui.emit("user", text="câu một")
    ui.emit("bot", text="trả lời")
    assert [e["kind"] for e in ui._history] == ["user", "bot"]


def test_history_is_bounded():
    for i in range(ui._MAX_HISTORY + 25):
        ui.emit("user", text=str(i))
    assert len(ui._history) == ui._MAX_HISTORY
    assert ui._history[-1]["text"] == str(ui._MAX_HISTORY + 24)  # newest kept, oldest dropped


def test_state_is_not_replayed():
    """State is a snapshot; a replayed old one would show the wrong vehicle state."""
    ui.emit("user", text="x")
    ui.emit_state()
    assert [e["kind"] for e in ui._history] == ["user"]


def test_emit_state_reports_current_vehicle_state():
    q = asyncio.Queue()
    ui._clients.append(q)
    ui.emit_state()
    event = drain(q)[0]
    assert event["kind"] == "state"
    assert set(event) >= {"ac", "fan", "window"}


# --- summarise -----------------------------------------------------------------------
# Tool results have no shared shape. Indexing a key that only some of them carry crashed
# the pipeline on the first knowledge-base question, so every shape gets a case here.

@pytest.mark.parametrize("result,expected", [
    ({"status": "success", "speech": "Đã giảm còn 22 độ"}, "Đã giảm còn 22 độ"),
    ({"status": "error", "message": "Mức quạt phải từ 0 đến 5"}, "Mức quạt phải từ 0 đến 5"),
    ({"results": [{"text": "a"}, {"text": "b"}]}, "2 kết quả"),
    ({"results": []}, "không tìm thấy"),
    ({"status": "success"}, "success"),
    ({}, "ok"),
])
def test_summarise_handles_every_tool_result_shape(result, expected):
    assert ui.summarise(result) == expected


def test_summarise_matches_every_real_tool():
    """Guards against a new tool returning a shape summarise cannot read."""
    from voice_agent.tools import ALL, dispatch
    sample = {"query": "áp suất lốp", "on": True, "level": 2, "delta": 1,
              "position": "driver", "opening": 50, "temperature": 22}
    for fn in ALL:
        args = {k: v for k, v in sample.items() if k in fn.__annotations__}
        assert isinstance(ui.summarise(dispatch(fn.__name__, args)), str)


# --- UIProbe -------------------------------------------------------------------------

def run(*frames) -> tuple[list[dict], list]:
    """Push frames through a fresh probe; return (events emitted, frames forwarded)."""
    probe, pushed = ui.UIProbe(), []
    q: asyncio.Queue = asyncio.Queue()
    ui._clients.append(q)

    async def fake_push(frame, _direction=None):
        pushed.append(frame)

    probe.push_frame = fake_push

    async def drive():
        for f in frames:
            await probe.process_frame(f, FrameDirection.DOWNSTREAM)

    asyncio.run(drive())
    return drain(q), pushed


def test_frames_are_always_forwarded():
    """The probe only observes — swallowing a frame would mute the pipeline."""
    frames = [UserStartedSpeakingFrame(), TranscriptionFrame(text="a", user_id="", timestamp=""),
              said("b"), BotStoppedSpeakingFrame()]
    _, pushed = run(*frames)
    assert len(pushed) == len(frames)


def test_transcript_becomes_an_event():
    events, _ = run(TranscriptionFrame(text="mở cửa sổ", user_id="", timestamp=""))
    assert {"kind": "user", "text": "mở cửa sổ"} in events


def test_spoken_text_is_joined_and_emitted_once_the_reply_ends():
    """TTS emits text word by word; the page wants one line per reply."""
    events, _ = run(said("Đã giảm "), said("còn 22 độ"),
                    BotStoppedSpeakingFrame())
    assert [e for e in events if e["kind"] == "bot"] == [{"kind": "bot", "text": "Đã giảm còn 22 độ"}]


def test_nothing_is_emitted_for_a_silent_reply():
    events, _ = run(BotStoppedSpeakingFrame())
    assert [e for e in events if e["kind"] == "bot"] == []


def test_barge_in_drops_the_half_spoken_sentence():
    """The driver interrupted, so that half sentence was never heard — don't show it."""
    events, _ = run(said("Áp suất lốp tiêu"), InterruptionFrame(),
                    BotStoppedSpeakingFrame())
    assert [e["kind"] for e in events] == ["interrupted"]


def test_speaking_into_silence_is_not_reported_as_barge_in():
    """Pipecat interrupts on every user turn start; only mid-sentence counts."""
    events, _ = run(said("xong"), BotStoppedSpeakingFrame(), InterruptionFrame())
    assert [e["kind"] for e in events] == ["bot"]


def test_consecutive_replies_do_not_bleed_into_each_other():
    events, _ = run(said("một"), BotStoppedSpeakingFrame(),
                    said("hai"), BotStoppedSpeakingFrame())
    assert [e["text"] for e in events if e["kind"] == "bot"] == ["một", "hai"]


# --- reset ---------------------------------------------------------------------------
# The button has to clear all three: the car, the agent's memory, and the page. Clearing
# only the page is worse than no button — the screen would claim a fresh start while the
# agent still remembered the previous turns.

def test_reset_clears_history_and_announces_itself():
    import asyncio as _asyncio

    from voice_agent.tools import vehicle
    q = _asyncio.Queue()
    ui._clients.append(q)
    ui.emit("user", text="cũ")
    vehicle.set_ac(True, 30)

    called = []
    ui.set_reset_handler(lambda: called.append(True) or _asyncio.sleep(0))
    _asyncio.run(ui._reset(None))

    assert called, "the handler app.py installs must run"
    assert ui._history == [], "old turns must not survive into a new demo"
    kinds = [e["kind"] for e in drain(q)]
    assert "reset" in kinds and "state" in kinds
    ui.set_reset_handler(None)


def test_reset_signal_is_not_replayed_to_late_joiners():
    """A tab opened later must not be told to wipe itself."""
    ui.emit("reset")
    assert ui._history == []


def test_vehicle_reset_restores_defaults():
    from voice_agent.tools import vehicle
    vehicle.set_ac(True, 30)
    vehicle.set_fan(5)
    vehicle.set_window("driver", 100)
    vehicle.reset_state()
    assert vehicle.STATE == vehicle.DEFAULTS


def test_vehicle_reset_does_not_alias_the_defaults():
    """A shallow copy would let the next command mutate DEFAULTS itself."""
    from voice_agent.tools import vehicle
    vehicle.reset_state()
    vehicle.set_ac(True, 30)
    assert vehicle.DEFAULTS["ac"] == {"on": False, "temp": 24}
