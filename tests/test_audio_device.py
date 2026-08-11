"""Resolving `INPUT_DEVICE` to a PortAudio index.

The bug this guards: `.env` held index 5, a reboot renumbered the devices, 5 became a
speaker, and the agent died with `[Errno -9998] Invalid number of channels`. Matching by
name survives the renumbering — as long as it skips output-only devices, since the same
name often appears on both sides.
"""
import pytest

from voice_agent.audio import match_device, resolve_device

# (index, name, max_input_channels) — the listing from the machine this broke on, where
# the same microphone appears once per host API, plus the speaker presumed to have taken
# over index 5 (the mic that used to hold it was simply gone from the listing).
DEVICES = [
    (0, "Microsoft Sound Mapper - Input", 2),
    (5, "Speakers (Realtek(R) Audio)", 0),
    (6, "Primary Sound Capture Driver", 2),
    (7, "Microphone Array (Realtek(R) Audio)", 2),
    (14, "Microphone Array (Realtek(R) Audio)", 2),
]


@pytest.mark.parametrize("spec,expected", [
    ("Primary Sound Capture Driver", 6),
    ("primary sound capture", 6),           # case and partial both fine
    ("Microphone Array", 7),                # duplicate names: lowest index wins
    ("Realtek(R) Audio", 7),                # never 5 — it has no input channels
    ("no such device", None),
])
def test_match_device(spec, expected):
    assert match_device(spec, DEVICES) == expected


@pytest.mark.parametrize("spec,expected", [(None, None), ("6", 6), ("  6  ", 6)])
def test_resolve_device_passes_indices_through_without_touching_portaudio(spec, expected):
    """An index needs no enumeration, so this path works headless and in CI."""
    assert resolve_device(spec) == expected
