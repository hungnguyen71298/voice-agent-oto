"""Config reading.

Only one thing here needs guarding, and it was found by cloning the repo fresh and
following the README: a placeholder key that reads as a real one.
"""
import pytest

from voice_agent.config import _real_key


@pytest.mark.parametrize("value,expected", [
    ("sk-or-v1-abc123", "sk-or-v1-abc123"),
    ("  sk-or-v1-abc123  ", "sk-or-v1-abc123"),  # a copy-paste picks up whitespace
    ("sk-or-v1-...", ""),                        # straight out of .env.example
    ("tvly-...", ""),
    ("", ""),
])
def test_an_unedited_placeholder_counts_as_no_key(value, expected, monkeypatch):
    """`cp .env.example .env` and forget to edit: the agent must refuse to start.

    Before this, it started, printed its banner, opened the microphone, and failed every
    turn with a 401 buried in debug logs — indistinguishable from a broken microphone.
    """
    monkeypatch.setenv("SOME_API_KEY", value)
    assert _real_key("SOME_API_KEY") == expected


def test_a_missing_variable_is_not_an_error(monkeypatch):
    monkeypatch.delenv("SOME_API_KEY", raising=False)
    assert _real_key("SOME_API_KEY") == ""
