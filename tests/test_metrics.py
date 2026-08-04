"""LatencyProbe — FAL is the graded metric, an error here invalidates the whole result.

These tests call `process_frame` directly and only stub `push_frame`. They do not
re-implement the measurement logic; doing so would make them pass even with a broken probe.
"""
import asyncio

from pipecat.frames.frames import (
    InterruptionFrame,
    TTSAudioRawFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from voice_agent.metrics import LatencyProbe


def audio():
    return TTSAudioRawFrame(audio=b"\x00\x00", sample_rate=24000, num_channels=1)


def run(*frames) -> tuple[LatencyProbe, list]:
    """Push frames through a fresh probe; return the probe and the frames it forwarded."""
    probe, pushed = LatencyProbe(), []

    async def fake_push(frame, _direction=None):
        pushed.append(frame)

    probe.push_frame = fake_push

    async def drive():
        for f in frames:
            await probe.process_frame(f, FrameDirection.DOWNSTREAM)

    asyncio.run(drive())
    return probe, pushed


def test_measures_one_turn():
    p, _ = run(UserStoppedSpeakingFrame(), audio())
    assert len(p.samples) == 1
    assert p.samples[0] >= 0


def test_frames_are_always_forwarded():
    """The probe only observes — swallowing a frame would mute the whole pipeline."""
    _, pushed = run(UserStoppedSpeakingFrame(), audio(), audio())
    assert len(pushed) == 3


def test_only_the_first_audio_frame_counts():
    """One reply emits hundreds of audio frames; only the first one is the FAL."""
    p, _ = run(UserStoppedSpeakingFrame(), audio(), audio(), audio())
    assert len(p.samples) == 1


def test_audio_without_a_user_turn_is_ignored():
    """The agent speaking on its own (a greeting) is not a reply to a turn."""
    p, _ = run(audio(), audio())
    assert p.samples == []


def test_barge_in_discards_the_turn_in_flight():
    """After an interruption, stale audio must not be recorded as an impossibly fast FAL."""
    p, _ = run(UserStoppedSpeakingFrame(), InterruptionFrame(), audio())
    assert p.samples == []
    assert p.discarded == 1


def test_measurement_resumes_after_barge_in():
    p, _ = run(UserStoppedSpeakingFrame(), InterruptionFrame(),
               UserStoppedSpeakingFrame(), audio())
    assert len(p.samples) == 1
    assert p.discarded == 1


def test_consecutive_turns():
    p, _ = run(UserStoppedSpeakingFrame(), audio(),
               UserStoppedSpeakingFrame(), audio(),
               UserStoppedSpeakingFrame(), audio())
    assert len(p.samples) == 3


def test_summary_is_empty_before_any_measurement():
    assert LatencyProbe().summary() == {}


def test_summary_statistics():
    p = LatencyProbe()
    p.samples = [100.0, 200.0, 300.0, 400.0, 500.0]
    s = p.summary()
    assert (s["n"], s["p50"], s["max"], s["p95"], s["discarded"]) == (5, 300.0, 500.0, 500.0, 0)


def test_p95_with_a_single_sample_does_not_wrap():
    """n=1 must not index at -1."""
    p = LatencyProbe()
    p.samples = [123.0]
    assert p.summary()["p95"] == 123.0
