"""Find a microphone that actually hears you, and the rate to open it at.

    python scripts/mic.py

Speak while it runs. It records from every input device in turn and prints the peak
level, because on Windows the *default* device frequently opens without error and then
delivers pure silence — the agent hears nothing, logs nothing, and looks broken for no
visible reason. That happened on the machine this was developed on: the MME default was
silent while the same microphone through DirectSound peaked at full scale.

Put the winning *name* in `.env` as `INPUT_DEVICE` — indices are handed out per boot and
the array that worked at 5 came back as 6 after a restart. If the winning rate is not
16000, set `INPUT_RATE` to it as well — letting the driver downsample a 44.1 kHz array
to 16 kHz degraded speech enough to change what Whisper transcribed.
"""
import array
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pyaudio  # noqa: E402

from voice_agent import audio  # noqa: E402

SECONDS = 3.0
SPEECH = 3000  # peak amplitude that means "someone spoke", not "the room hums"


def measure(pa: pyaudio.PyAudio, index: int, rate: int) -> int | None:
    """Peak amplitude over `SECONDS`, or None if the device will not open at `rate`."""
    try:
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=rate, input=True,
                         frames_per_buffer=1024, input_device_index=index)
    except Exception:
        return None
    peak = 0
    try:
        deadline = time.monotonic() + SECONDS
        while time.monotonic() < deadline:
            samples = array.array("h")
            samples.frombytes(stream.read(1024, exception_on_overflow=False))
            peak = max(peak, max(abs(s) for s in samples) if samples else 0)
    finally:
        stream.close()
    return peak


def main() -> int:
    pa = pyaudio.PyAudio()
    inputs = [(i, pa.get_device_info_by_index(i)) for i in range(pa.get_device_count())]
    inputs = [(i, d) for i, d in inputs if d["maxInputChannels"] > 0]
    if not inputs:
        sys.exit("Không tìm thấy thiết bị thu nào.")

    print(f"Nói liên tục trong lúc chạy — mỗi thiết bị thu {SECONDS:.0f} giây.\n")
    results = []
    for index, info in inputs:
        native = int(info["defaultSampleRate"])
        api = pa.get_host_api_info_by_index(info["hostApi"])["name"]
        for rate in dict.fromkeys([16000, native]):  # dedupe, keep order
            peak = measure(pa, index, rate)
            label = f"[{index:2}] {info['name'][:38]:38} {api:18} {rate:6} Hz"
            if peak is None:
                print(f"  {label}  không mở được")
                continue
            bar = "#" * min(30, peak // 500)
            print(f"  {label}  đỉnh {peak:6}  {bar}"
                  + ("  ← nghe rõ" if peak >= SPEECH else ""))
            results.append((peak, index, rate, info["name"]))

    heard = [r for r in results if r[0] >= SPEECH]
    print()
    if not heard:
        print("Không thiết bị nào nghe thấy giọng nói. Kiểm tra mic có bị tắt tiếng,")
        print("và Windows đã cho phép ứng dụng desktop dùng micro chưa.")
        return 1

    peak, index, rate, name = max(heard)
    # Name over index: indices are per-boot. But the same microphone shows up once per
    # host API with near-identical names, so only recommend the name when it resolves
    # back to the device actually measured.
    devices = audio.list_devices(pa)
    by_name = name if audio.match_device(name, devices) == index else None
    print(f"Dùng thiết bị [{index}] {name} (đỉnh {peak} ở {rate} Hz). Thêm vào .env:\n")
    print(f"    INPUT_DEVICE={by_name or index}")
    if rate != 16000:
        print(f"    INPUT_RATE={rate}")
        print("\nINPUT_RATE để hệ thống tự hạ tần số bằng SoX thay vì để driver làm —")
        print("driver hạ tần số kém có thể làm STT nghe sai hẳn từ.")
    if by_name is None:
        print("\nTên này trùng với thiết bị khác (cùng mic, khác host API) nên phải dùng"
              "\nsố. Số đổi sau mỗi lần khởi động — chạy lại script nếu agent hoá điếc.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
