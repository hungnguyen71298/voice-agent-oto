"""Mock vehicle API — stands in for a real CAN bus.

Every function validates fully before mutating `STATE`, and returns a dict with a
`status` field so the agent can read the execution result. Nothing here raises.

A successful result also carries `speech`: the sentence to say back. The pipeline
speaks it directly and skips the second LLM round trip, which measured 1.5-2.4s of
the 4.1s a tool-using turn used to cost. Errors deliberately carry no `speech` —
those go back through the LLM, which is the part that knows how to ask a good
follow-up question.
"""

import copy

# ponytail: state is an in-RAM dict, one vehicle, one process. Enough for the demo.
# Upgrade path: adapter onto CAN bus / Android Automotive CarPropertyManager.
DEFAULTS = {
    "ac": {"on": False, "temp": 24},
    "fan": {"level": 0},
    "window": {"driver": 0, "passenger": 0},  # percent open
}

STATE = copy.deepcopy(DEFAULTS)


def reset_state() -> None:
    """Put the vehicle back to how it starts. Used by the dashboard's reset button."""
    STATE.clear()
    STATE.update(copy.deepcopy(DEFAULTS))


def set_ac(on: bool, temperature: int | None = None) -> dict:
    """Bật hoặc tắt điều hòa, có thể kèm đặt nhiệt độ.

    Args:
        on: True để bật, False để tắt điều hòa.
        temperature: Nhiệt độ mong muốn, 16-30 độ C. Bỏ trống nếu chỉ bật/tắt.
    """
    if temperature is not None and not 16 <= temperature <= 30:  # validate before mutating
        return {"device": "ac", "status": "error", "message": "Nhiệt độ phải từ 16 đến 30 độ"}
    STATE["ac"]["on"] = on
    if temperature is not None:
        STATE["ac"]["temp"] = temperature
    said = f"Đã bật điều hòa {STATE['ac']['temp']} độ" if on else "Đã tắt điều hòa"
    return {"device": "ac", "status": "success", "speech": said, **STATE["ac"]}


def adjust_ac_temperature(delta: int) -> dict:
    """Tăng hoặc giảm nhiệt độ điều hòa so với mức hiện tại.

    Args:
        delta: Số độ thay đổi, dương là tăng, âm là giảm. Ví dụ -2 là giảm 2 độ.
    """
    before = STATE["ac"]["temp"]
    result = set_ac(True, max(16, min(30, before + delta)))
    if result["temp"] == before:  # already at the 16-30 limit; silence would read as a failure
        result["speech"] = f"Điều hòa đã ở mức {before} độ rồi"
    else:
        result["speech"] = f"Đã {'giảm' if delta < 0 else 'tăng'} còn {result['temp']} độ"
    return result


def set_fan(level: int) -> dict:
    """Đặt mức quạt gió.

    Args:
        level: Mức quạt từ 0 (tắt) đến 5 (mạnh nhất).
    """
    if not 0 <= level <= 5:
        return {"device": "fan", "status": "error", "message": "Mức quạt phải từ 0 đến 5"}
    STATE["fan"]["level"] = level
    said = f"Đã đặt quạt mức {level}" if level else "Đã tắt quạt gió"
    return {"device": "fan", "status": "success", "speech": said, **STATE["fan"]}


def adjust_fan(delta: int) -> dict:
    """Tăng hoặc giảm mức quạt gió so với mức hiện tại.

    Args:
        delta: Số mức thay đổi, dương là tăng, âm là giảm. Ví dụ 2 là tăng hai mức.
    """
    before = STATE["fan"]["level"]
    result = set_fan(max(0, min(5, before + delta)))
    if result["level"] == before:
        result["speech"] = f"Quạt đã ở mức {before} rồi"
    return result


def set_window(position: str, opening: int) -> dict:
    """Mở hoặc đóng cửa sổ. Phải biết rõ cửa sổ nào, nếu người dùng không nói thì hỏi lại.

    Args:
        position: Vị trí cửa sổ, chỉ nhận "driver" (ghế lái) hoặc "passenger" (ghế phụ).
        opening: Độ mở từ 0 (đóng hẳn) đến 100 (mở hết).
    """
    if position not in STATE["window"]:
        return {"device": "window", "status": "error", "message": f"Không có cửa sổ '{position}'"}
    before = STATE["window"][position]
    STATE["window"][position] = max(0, min(100, opening))
    where = "ghế lái" if position == "driver" else "ghế phụ"
    pct = STATE["window"][position]
    # Which verb depends on the direction, not the final value: going 100 → 50 is closing,
    # and answering "đã mở 50 phần trăm" to "đóng cửa sổ 50%" sounds like a misheard command.
    if pct == 0:
        said = f"Đã đóng cửa sổ {where}"
    elif pct < before:
        said = f"Đã đóng cửa sổ {where} còn {pct} phần trăm"
    else:
        said = f"Đã mở cửa sổ {where} {pct} phần trăm"
    return {"device": "window", "position": position, "status": "success", "speech": said,
            **STATE["window"]}


def describe_state() -> str:
    """Render current vehicle state as one line, for interpolation into the system prompt."""
    ac, fan, win = STATE["ac"], STATE["fan"], STATE["window"]
    return (f"điều hòa {'bật' if ac['on'] else 'tắt'} {ac['temp']} độ, "
            f"quạt mức {fan['level']}, "
            f"cửa sổ ghế lái {win['driver']}%, ghế phụ {win['passenger']}%")


TOOLS = [set_ac, adjust_ac_temperature, set_fan, adjust_fan, set_window]
