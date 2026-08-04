"""Mock vehicle API — stands in for a real CAN bus.

Every function validates fully before mutating `STATE`, and returns a dict with a
`status` field so the agent can read the execution result. Nothing here raises.
"""

# ponytail: state is an in-RAM dict, one vehicle, one process. Enough for the demo.
# Upgrade path: adapter onto CAN bus / Android Automotive CarPropertyManager.
STATE = {
    "ac": {"on": False, "temp": 24},
    "fan": {"level": 0},
    "window": {"driver": 0, "passenger": 0},  # percent open
}


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
    return {"device": "ac", "status": "success", **STATE["ac"]}


def adjust_ac_temperature(delta: int) -> dict:
    """Tăng hoặc giảm nhiệt độ điều hòa so với mức hiện tại.

    Args:
        delta: Số độ thay đổi, dương là tăng, âm là giảm. Ví dụ -2 là giảm 2 độ.
    """
    return set_ac(True, max(16, min(30, STATE["ac"]["temp"] + delta)))


def set_fan(level: int) -> dict:
    """Đặt mức quạt gió.

    Args:
        level: Mức quạt từ 0 (tắt) đến 5 (mạnh nhất).
    """
    if not 0 <= level <= 5:
        return {"device": "fan", "status": "error", "message": "Mức quạt phải từ 0 đến 5"}
    STATE["fan"]["level"] = level
    return {"device": "fan", "status": "success", **STATE["fan"]}


def adjust_fan(delta: int) -> dict:
    """Tăng hoặc giảm mức quạt gió so với mức hiện tại.

    Args:
        delta: Số mức thay đổi, dương là tăng, âm là giảm. Ví dụ 2 là tăng hai mức.
    """
    return set_fan(max(0, min(5, STATE["fan"]["level"] + delta)))


def set_window(position: str, opening: int) -> dict:
    """Mở hoặc đóng cửa sổ. Phải biết rõ cửa sổ nào, nếu người dùng không nói thì hỏi lại.

    Args:
        position: Vị trí cửa sổ, chỉ nhận "driver" (ghế lái) hoặc "passenger" (ghế phụ).
        opening: Độ mở từ 0 (đóng hẳn) đến 100 (mở hết).
    """
    if position not in STATE["window"]:
        return {"device": "window", "status": "error", "message": f"Không có cửa sổ '{position}'"}
    STATE["window"][position] = max(0, min(100, opening))
    return {"device": "window", "position": position, "status": "success", **STATE["window"]}


def describe_state() -> str:
    """Render current vehicle state as one line, for interpolation into the system prompt."""
    ac, fan, win = STATE["ac"], STATE["fan"], STATE["window"]
    return (f"điều hòa {'bật' if ac['on'] else 'tắt'} {ac['temp']} độ, "
            f"quạt mức {fan['level']}, "
            f"cửa sổ ghế lái {win['driver']}%, ghế phụ {win['passenger']}%")


TOOLS = [set_ac, adjust_ac_temperature, set_fan, adjust_fan, set_window]
