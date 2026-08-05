# Hướng dẫn cài đặt và chạy

Từ máy trắng đến agent nói được, khoảng 10 phút — phần lớn là chờ tải thư viện.

## 0. Cần gì trước

| | Yêu cầu | Ghi chú |
|---|---|---|
| Python | 3.12 trở lên | `python --version` |
| RAM | ~2 GB trống | Piper + Silero nạp vào RAM |
| Mạng | có | STT và LLM gọi API; TTS chạy local |
| Mic + loa | có, để nói chuyện thật | không có vẫn chạy được `scripts/e2e.py` |
| API key | OpenRouter | <https://openrouter.ai/keys>, nạp $5 là quá đủ |

Không cần: GPU, tài khoản Google Cloud, Docker, key TTS.

**Cẩn thận trên Windows**: nếu máy có nhiều bản Python (Miniconda, Python.org, Store),
gọi `python` trần rất dễ trúng bản khác và báo thiếu thư viện. Luôn gọi qua đường dẫn
venv như bên dưới.

## 1. Cài

```bash
git clone <repo> voice-agent && cd voice-agent
python -m venv .venv
```

```bash
# Linux / macOS
.venv/bin/pip install -r requirements-dev.txt
# Windows PowerShell
.venv\Scripts\pip install -r requirements-dev.txt
```

`requirements-dev.txt` gồm cả `requirements.txt` cộng `pytest` và `ruff`.

## 2. Điền API key

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Mở `.env`, điền một dòng:

```
OPENROUTER_API_KEY=sk-or-v1-...
```

Mọi thứ còn lại trong file đó đều có mặc định hợp lý, để trống được.
**`.env` đã nằm trong `.gitignore`** — đừng bao giờ điền key vào `.env.example`,
file đó được commit.

## 3. Kiểm tra trước khi chạy

Không cần key, không cần mic, không gọi mạng:

```bash
.venv/bin/python -m pytest        # 84 test
.venv/bin/python -m ruff check .
```

Cả hai phải xanh. Nếu `pytest` báo thiếu module, gần như chắc bạn đang gọi nhầm
Python — xem lại phần cảnh báo ở mục 0.

## 4. Chạy

```bash
.venv/bin/python -m voice_agent
```

Lần chạy đầu tải giọng Piper (~60 MB) về `data/piper/` và model Silero VAD. Từ lần
sau khởi động dưới 5 giây.

Màn hình sẽ in:

```
STT=openai/whisper-large-v3
LLM=google/gemini-3.5-flash-lite
TTS=piper/vi_VN-vais1000-medium
KB=850 chunks
Dashboard: http://127.0.0.1:8080

Start speaking (Ctrl+C to quit)...
```

Mở <http://127.0.0.1:8080> rồi nói vào mic. Mỗi lượt in ra transcript, tool được gọi
và First Audio Latency. Thoát bằng Ctrl+C, lúc đó nó in tổng kết p50/p95/max.

Thử vài câu:

- "Bật điều hòa hai mươi hai độ"
- "Giảm thêm hai độ nữa" — kiểm tra nó nhớ lượt trước
- "Mở cửa sổ" — nó phải **hỏi lại** là cửa sổ nào, không được tự đoán
- "Áp suất lốp bao nhiêu là đúng" — tra sổ tay VF 8 thật

## 5. Nếu không có mic

```bash
.venv/bin/python scripts/e2e.py --keep-audio out
```

Chạy nguyên pipeline thật với giọng người dùng dựng sẵn, kiểm 5 hành vi và ghi lại
âm thanh ra `out/`. Đây cũng là smoke test nên chạy trước mỗi lần demo.

Chỉ muốn xem giao diện thì:

```bash
.venv/bin/python scripts/demo_ui.py    # không cần mic, không cần key
```

## 6. Docker (tuỳ chọn)

```bash
docker compose up --build
```

Build mất 10–20 phút lần đầu. Image ~2 GB, đã bake sẵn giọng Piper và Silero để lượt
nói đầu tiên không phải chờ tải model.

**Chỉ chạy được trên host Linux.** Container cần `/dev/snd` của host; Docker trên
Windows và macOS không chuyển tiếp được audio. Trên hai hệ đó hãy chạy thẳng bằng venv.
Riêng dashboard thì ở đâu cũng xem được tại <http://localhost:8080>.

Trên WSL2 cũng **không** có audio device, nên container ở đó chỉ dùng để kiểm tra build
và dashboard, không nói chuyện được.

## Sự cố thường gặp

**`ModuleNotFoundError` dù vừa cài xong**
Gọi nhầm Python. Dùng `.venv/bin/python` (hoặc `.venv\Scripts\python`), đừng gọi `python`.

**Console Windows hiện `?????` thay cho tiếng Việt**
```powershell
$env:PYTHONIOENCODING="utf-8"
```
`voice_agent/__main__.py` đã tự xử lý phần lớn trường hợp; biến này lo nốt các script lẻ.

**`OSError` khi mở mic, hoặc không nghe thấy gì**
Kiểm tra Windows/macOS đã cấp quyền micro cho terminal chưa. Liệt kê thiết bị:
```bash
.venv/bin/python -c "import pyaudio; p=pyaudio.PyAudio(); [print(i, p.get_device_info_by_index(i)['name']) for i in range(p.get_device_count())]"
```

**Agent nghe sai từ**
STT đạt ~85% từ đúng trên giọng tổng hợp. Nói chậm hơn và tắt bớt tiếng ồn. Đổi model
mà không sửa code:
```bash
STT_MODEL=openai/gpt-4o-mini-transcribe .venv/bin/python -m voice_agent
```

**FAL cao hơn nhiều so với con số trong README**
Số trong README đo từ Việt Nam. Chặng mạng tới OpenRouter chiếm phần lớn FAL, nên vị trí
địa lý ảnh hưởng mạnh. Đo chính máy bạn:
```bash
.venv/bin/python scripts/bench.py --repeat 3
```

**Giọng đọc nghe máy quá**
```bash
TTS_ENGINE=edge .venv/bin/python -m voice_agent
```
Giọng tự nhiên hơn nhưng chậm hơn ~350 ms, và Microsoft sẽ bóp nếu gọi dồn.

**Cổng 8080 đã bị chiếm**
```bash
UI_PORT=9000 .venv/bin/python -m voice_agent   # UI_PORT=0 để tắt hẳn dashboard
```

## Đổi dòng xe

Knowledge base mặc định là sổ tay VF 8 (2026). Đổi sang xe khác:

```bash
rm data/kb/*.md
.venv/bin/python scripts/fetch_kb.py VF9 2026
```

Hỗ trợ VF3, VF5, VF6, VF7, VF8, VF9, VF e34, Minio/Herio/Nerio/Limo Green, Fadil,
Lux A2.0, Lux SA2.0, President, EC VAN, EB 6/8/10.
