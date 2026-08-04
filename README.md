# Voice Agent trên ô tô

Trợ lý ảo tương tác hoàn toàn bằng giọng nói: **điều khiển thiết bị trên xe**,
**tra sổ tay hướng dẫn sử dụng**, **tìm thông tin Internet**.

```
mic ─► SileroVAD ─► STT ─► LLM (+tool calling) ─► TTS ─► loa
                    └──────── OpenRouter, 1 API key ────────┘
                                   │
                                   ▼
                    tools/  vehicle mock · BM25 knowledge base · search
```

Chi tiết: [`docs/kien-truc.md`](docs/kien-truc.md) · lý do từng lựa chọn:
[`docs/quyet-dinh.md`](docs/quyet-dinh.md)

## Cài đặt

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt      # Windows: .venv\Scripts\pip
cp .env.example .env                               # điền OPENROUTER_API_KEY
```

Lấy key: <https://openrouter.ai/keys>. Một key dùng cho cả STT, LLM và TTS.
Nạp ~$25 là đủ cho toàn bộ quá trình phát triển và demo (xem [Chi phí](#chi-phí)).

## Chạy

```bash
.venv/bin/python -m voice_agent
```

Nói vào mic, agent trả lời bằng giọng nói. Mỗi lượt in ra transcript, tool được
gọi, kết quả tool và **First Audio Latency**.

Windows: `$env:PYTHONIOENCODING="utf-8"` nếu console vỡ font tiếng Việt.

## Kiểm thử

Không cần API key, không cần mic:

```bash
.venv/bin/python -m pytest        # 47 test
.venv/bin/python -m ruff check .  # lint
```

| File | Kiểm tra |
|---|---|
| `tests/test_vehicle.py` | giá trị trả về **và** mutation trên `STATE`; đường lỗi không được để lại thay đổi một nửa |
| `tests/test_knowledge.py` | chunk mang heading, bigram tiếng Việt, retrieve đúng nội dung, không đụng state |
| `tests/test_schema.py` | sinh JSON schema từ type hint + docstring |
| `tests/test_metrics.py` | đo FAL đúng frame đầu tiên, bỏ lượt khi barge-in, probe không chặn frame |

## Cấu hình

Mọi thứ đổi bằng biến môi trường, không sửa code:

| Biến | Mặc định | |
|---|---|---|
| `OPENROUTER_API_KEY` | — | **bắt buộc** |
| `TAVILY_API_KEY` | — | không có thì `search_internet` trả kết quả mock |
| `STT_MODEL` | `openai/whisper-1` | |
| `LLM_MODEL` | `google/gemini-3.1-flash-lite` | |
| `TTS_MODEL` | `google/gemini-3.1-flash-tts-preview` | |
| `TTS_VOICE` | `Kore` | |
| `KB_TOP_K` | `3` | số chunk trả về mỗi lần tra sổ tay |

```bash
LLM_MODEL=openai/gpt-5-mini .venv/bin/python -m voice_agent
```

## Knowledge Base

Dữ liệu **thật**: sổ tay hướng dẫn sử dụng VinFast VF 8 (2026), tiếng Việt —
12 chương, 530k ký tự, 850 chunk. Nguồn: API công khai của
[om.vinfastauto.com](https://om.vinfastauto.com).

```bash
.venv/bin/python scripts/fetch_kb.py VF9 2026
```

Hỗ trợ VF3, VF5, VF6, VF7, VF8, VF9, VF e34, Minio/Herio/Nerio/Limo Green,
Fadil, Lux A2.0, Lux SA2.0, President, EC VAN, EB 6/8/10.

Retrieve bằng BM25: index build 250ms, query ~3ms, không gọi mạng. Hai điều chỉnh
cho tiếng Việt — chunk mang theo heading gần nhất, và token gồm bigram âm tiết
(`áp_suất`), vì âm tiết đơn tiếng Việt quá phổ biến để phân biệt.

## Latency

FAL đo bởi `voice_agent/metrics.py` từ `UserStoppedSpeakingFrame` đến
`TTSAudioRawFrame` đầu tiên — đúng định nghĩa mục 3 đề bài. Chưa trừ device
output buffer (~20-40ms) nên số báo lạc quan hơn thực tế một chút.

Đã đo (máy dev tại Việt Nam):

| | cold | warm |
|---|---|---|
| HTTPS tới openrouter.ai | 375ms | ~176ms |
| ICMP edge | | 44ms |

**Chưa đo end-to-end** — cần API key. Chạy `python -m voice_agent`, số in ra sau
mỗi lượt, tổng kết p50/p95/max khi thoát.

## Chi phí

Ước tính 1 lượt: user nói 3s, agent trả lời 6s, 1 tool call.

| | Đơn giá | Tiền/lượt |
|---|---|---|
| STT | $0.016/phút | $0.0008 |
| LLM in + out | $0.25 / $1.50 per 1M | $0.0009 |
| TTS | $20/1M token audio | $0.0030 |
| **Tổng** | | **~$0.005** |

Toàn bộ quá trình phát triển + demo ≈ **$15-20**. Vận hành thật ≈ $3/tháng/xe.

## Docker

```bash
docker compose up --build
```

Mic/loa cần thiết bị âm thanh của host — chỉ chạy được trên **host Linux**
(`/dev/snd`). Trên Windows/macOS, Docker không chuyển tiếp được audio; chạy trực
tiếp bằng venv.

## Phần mock

Theo yêu cầu mục 9 đề bài:

- **Vehicle API** — `STATE` là dict trong RAM (`voice_agent/tools/vehicle.py`),
  không có CAN bus thật.
- **`search_internet`** — trả kết quả giả nếu không có `TAVILY_API_KEY`.
  Có key là tự chuyển sang gọi thật, không sửa code.
- **Knowledge Base** — **không mock**, là sổ tay VF 8 thật.

## Cấu trúc

```
voice_agent/
├── __main__.py          entrypoint
├── config.py            env var + system prompt
├── app.py               lắp pipeline Pipecat
├── metrics.py           LatencyProbe — đo FAL
├── schema.py            hàm Python → JSON schema cho LLM
└── tools/
    ├── __init__.py      registry + dispatch (không bao giờ raise)
    ├── vehicle.py       mock thiết bị trên xe
    ├── knowledge.py     BM25 trên sổ tay
    └── web.py           Tavily, mock nếu thiếu key
data/kb/                 sổ tay VF 8 2026
scripts/fetch_kb.py      nạp KB từ om.vinfastauto.com
tests/                   47 test, không cần API key
docs/                    kiến trúc + lý do các quyết định
```

**Thêm tool = thêm 1 hàm** vào module trong `tools/` rồi đưa vào `TOOLS` của
module đó. Type hint và docstring Google-style là hợp đồng với LLM;
`schema.py` tự sinh JSON schema. Pipeline không phải sửa.
