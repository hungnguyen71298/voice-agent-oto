"""Vehicle mock and dispatch.

Every test checks BOTH the returned value AND the mutation on STATE — a correct
return dict with wrong state has happened for real here (set_ac switched the AC on
before validating the temperature).
"""
import copy

import pytest

from voice_agent import tools
from voice_agent.tools import vehicle
from voice_agent.tools.vehicle import STATE, adjust_fan, set_ac, set_fan, set_window


@pytest.fixture(autouse=True)
def reset_state():
    """Each test starts from clean state — STATE is a module global and never resets itself."""
    before = copy.deepcopy(STATE)
    STATE.update(copy.deepcopy({"ac": {"on": False, "temp": 24}, "fan": {"level": 0},
                                "window": {"driver": 0, "passenger": 0}}))
    yield
    STATE.clear()
    STATE.update(before)


def assert_no_mutation(call):
    """Call `call`, assert it returned an error and left STATE untouched."""
    before = copy.deepcopy(STATE)
    r = call()
    assert r["status"] == "error", f"expected error, got {r}"
    assert STATE == before, f"error path mutated state: {before} -> {STATE}"


# --- dispatch: a bad LLM call returns an error, never raises, never mutates ---------

@pytest.mark.parametrize("name,args", [
    ("teleport_car", {}),                                 # tool does not exist
    ("set_ac", {"onn": True}),                            # misspelled parameter
    ("set_ac", {}),                                       # required parameter missing
    ("set_ac", {"on": "có"}),                             # wrong type
    ("set_fan", {"level": "hai"}),                        # wrong type
    ("set_ac", {"on": True, "temperature": 99}),          # out of range
    ("set_fan", {"level": 9}),                            # out of range
    ("set_window", {"position": "rear", "opening": 50}),  # unknown window
])
def test_dispatch_error_never_raises_never_mutates(name, args):
    assert_no_mutation(lambda: tools.dispatch(name, args))


def test_dispatch_reaches_the_right_function():
    assert tools.dispatch("set_ac", {"on": True, "temperature": 22})["temp"] == 22
    assert STATE["ac"] == {"on": True, "temp": 22}


# --- air conditioning ---------------------------------------------------------------

def test_set_temperature():
    assert set_ac(True, 22)["temp"] == 22
    assert STATE["ac"] == {"on": True, "temp": 22}


def test_relative_temperature_change():
    """Brief scenario 2: "turn on the AC" then "drop it two more degrees"."""
    set_ac(True, 22)
    assert tools.dispatch("adjust_ac_temperature", {"delta": -2})["temp"] == 20
    assert STATE["ac"]["temp"] == 20


def test_temperature_is_clamped():
    set_ac(True, 22)
    assert vehicle.adjust_ac_temperature(-99)["temp"] == 16
    assert vehicle.adjust_ac_temperature(99)["temp"] == 30


def test_turning_ac_off_keeps_temperature():
    set_ac(True, 22)
    assert set_ac(False)["temp"] == 22
    assert STATE["ac"] == {"on": False, "temp": 22}


# --- fan -----------------------------------------------------------------------------

def test_relative_fan_change():
    """Brief scenario 2: "turn on the fan" then "two steps higher"."""
    set_fan(1)
    assert tools.dispatch("adjust_fan", {"delta": 2})["level"] == 3
    assert STATE["fan"]["level"] == 3


def test_fan_level_is_clamped():
    set_fan(4)
    assert adjust_fan(9)["level"] == 5
    assert adjust_fan(-99)["level"] == 0


# --- windows -------------------------------------------------------------------------

def test_window_is_clamped_and_isolated():
    assert set_window("driver", 150)["driver"] == 100
    assert STATE["window"] == {"driver": 100, "passenger": 0}


def test_describe_state_is_readable():
    set_ac(True, 22)
    s = vehicle.describe_state()
    assert "bật" in s and "22" in s


# --- the `speech` shortcut -----------------------------------------------------------
# app.py speaks `speech` verbatim and suppresses the follow-up LLM call. That makes the
# field load-bearing: a missing one silently costs a second round trip, and a wrong one
# is read aloud to the driver as fact.

@pytest.mark.parametrize("name,args,must_contain", [
    ("set_ac", {"on": True, "temperature": 22}, "22"),
    ("set_ac", {"on": False}, "tắt"),
    ("set_fan", {"level": 3}, "3"),
    ("set_fan", {"level": 0}, "tắt"),
    ("set_window", {"position": "driver", "opening": 50}, "ghế lái"),
    ("set_window", {"position": "passenger", "opening": 0}, "đóng"),
    ("adjust_ac_temperature", {"delta": -2}, "22"),
    ("adjust_fan", {"delta": 2}, "2"),
])
def test_successful_control_returns_speech(name, args, must_contain):
    result = tools.dispatch(name, args)
    assert result["status"] == "success"
    assert must_contain in result["speech"], result["speech"]


@pytest.mark.parametrize("name,args", [
    ("set_ac", {"on": True, "temperature": 99}),
    ("set_fan", {"level": 9}),
    ("set_window", {"position": "rear", "opening": 50}),
])
def test_errors_carry_no_speech(name, args):
    """Errors must reach the LLM — it is the part that can ask a sensible follow-up."""
    assert "speech" not in tools.dispatch(name, args)


@pytest.mark.parametrize("name", ["search_manual", "search_internet"])
def test_lookup_tools_carry_no_speech(name):
    """Their results need summarising, so they must not bypass the model."""
    assert "speech" not in tools.dispatch(name, {"query": "áp suất lốp"})


def test_speech_reports_a_no_op_rather_than_going_silent():
    """At the clamp, nothing changes — saying so beats confirming a change that didn't happen."""
    set_ac(True, 16)
    assert "16" in vehicle.adjust_ac_temperature(-2)["speech"]
    set_fan(5)
    assert "5" in vehicle.adjust_fan(2)["speech"]
