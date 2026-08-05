"""Replay a scripted conversation into the dashboard. No microphone, no API key.

    python scripts/demo_ui.py          # then open http://127.0.0.1:8080

Two uses: checking the page renders without setting up audio, and having something to
project if the microphone fails during a presentation. The tool calls are real — they
run through `dispatch` and mutate the same `STATE` the live agent uses — so the vehicle
panel behaves exactly as it does in a real session. Only the timings are invented.
"""
import asyncio
import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from voice_agent import config, ui  # noqa: E402
from voice_agent.tools import dispatch  # noqa: E402

# (what the driver said, tool to run, args, what the agent replied, FAL in ms)
SCRIPT = [
    ("Bật điều hòa 24 độ", "set_ac", {"on": True, "temperature": 24}, None, 1180),
    ("Giảm thêm hai độ nữa", "adjust_ac_temperature", {"delta": -2}, None, 1240),
    ("Quạt mạnh lên", "adjust_fan", {"delta": 2}, None, 1090),
    ("Mở cửa sổ", None, None, "Bạn muốn mở cửa sổ ghế lái hay ghế phụ ạ?", 1870),
    ("Ghế lái", "set_window", {"position": "driver", "opening": 50}, None, 1320),
    ("Áp suất lốp bao nhiêu là đúng", "search_manual", {"query": "áp suất lốp tiêu chuẩn"},
     "Bạn xem nhãn dán ở khung cửa phía người lái để biết mức đúng cho xe mình.", 2410),
    ("Đóng cửa sổ lại", "set_window", {"position": "driver", "opening": 0}, None, 1150),
]


async def main() -> int:
    await ui.start(config.UI_PORT, config.UI_HOST)
    print(f"Dashboard: http://127.0.0.1:{config.UI_PORT}\nCtrl+C to quit.", flush=True)
    while True:  # loop so the page stays alive through a long presentation
        for said, tool, args, reply, fal in SCRIPT:
            ui.emit("listening")
            await asyncio.sleep(1.1)
            ui.emit("user", text=said)
            await asyncio.sleep(0.5)
            if tool:
                result = dispatch(tool, args)
                ui.emit("tool", name=tool, args=str(args), result=ui.summarise(result))
                ui.emit_state()
                reply = reply or result.get("speech")
                await asyncio.sleep(0.4)
            ui.emit("bot", text=reply)
            ui.emit("fal", ms=fal)
            await asyncio.sleep(2.6)
        await asyncio.sleep(4)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(asyncio.run(main()))
