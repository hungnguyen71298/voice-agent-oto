# Voice Agent trên ô tô

Trợ lý ảo tương tác hoàn toàn bằng giọng nói: **điều khiển thiết bị trên xe**,
**tra sổ tay hướng dẫn sử dụng**, **tìm thông tin Internet**.

```
mic ─► SileroVAD ─► STT ─► LLM (+tool calling) ─┬─► TTS (Piper, local) ─► loa
                    └── OpenRouter, 1 key ──┘   │
                                   │            └── lệnh điều khiển: đọc thẳng
                                   ▼                câu xác nhận, bỏ vòng LLM thứ 2
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

Lấy key: <https://openrouter.ai/keys>. Một key cho cả STT và LLM. **TTS chạy local**,
không cần key thứ hai — lần chạy đầu tự tải model Piper (~60 MB) về `data/piper/`.
Nạp ~$20 là đủ cho toàn bộ quá trình phát triển và demo (xem [Chi phí](#chi-phí)).

## Chạy

```bash
.venv/bin/python -m voice_agent
```

Nói vào mic, agent trả lời bằng giọng nói. Mỗi lượt in ra transcript, tool được
gọi, kết quả tool và **First Audio Latency**.

Mở <http://127.0.0.1:8080> để xem **dashboard**: hội thoại trực tiếp, tool đang
chạy, trạng thái xe và biểu đồ FAL từng lượt. Trang chỉ quan sát — mic vẫn ở máy
chạy pipeline, không có chặng mạng nào thêm vào đường âm thanh nên số FAL không bị
ảnh hưởng. Tắt bằng `UI_PORT=0`.

Xem dashboard mà không cần mic (cũng là phương án dự phòng khi thuyết trình):

```bash
.venv/bin/python scripts/demo_ui.py
```

Windows: `$env:PYTHONIOENCODING="utf-8"` nếu console vỡ font tiếng Việt.

## Kiểm thử

Không cần API key, không cần mic:

```bash
.venv/bin/python -m pytest        # 82 test
.venv/bin/python -m ruff check .  # lint
```

| File | Kiểm tra |
|---|---|
| `tests/test_vehicle.py` | giá trị trả về **và** mutation trên `STATE`; đường lỗi không được để lại thay đổi một nửa |
| `tests/test_knowledge.py` | chunk mang heading, bigram tiếng Việt, retrieve đúng nội dung, không đụng state |
| `tests/test_schema.py` | sinh JSON schema từ type hint + docstring |
| `tests/test_metrics.py` | đo FAL đúng frame đầu tiên, bỏ lượt khi barge-in, probe không chặn frame |
| `tests/test_vehicle.py` | câu xác nhận `speech` có mặt trên đường thành công, vắng mặt trên đường lỗi và trên tool tra cứu |
| `tests/test_ui.py` | dashboard không nuốt frame, tab treo không chặn pipeline, mọi hình dạng kết quả tool đều đọc được |

## Cấu hình

Mọi thứ đổi bằng biến môi trường, không sửa code:

| Biến | Mặc định | |
|---|---|---|
| `OPENROUTER_API_KEY` | — | **bắt buộc** |
| `TAVILY_API_KEY` | — | không có thì `search_internet` trả kết quả mock |
| `STT_MODEL` | `openai/whisper-large-v3` | |
| `LLM_MODEL` | `google/gemini-3.5-flash-lite` | |
| `TTS_ENGINE` | `piper` | `piper` (local) hoặc `edge` |
| `PIPER_VOICE` | `vi_VN-vais1000-medium` | |
| `EDGE_VOICE` | `vi-VN-HoaiMyNeural` | chỉ dùng khi `TTS_ENGINE=edge` |
| `KB_TOP_K` | `3` | số chunk trả về mỗi lần tra sổ tay |
| `UI_PORT` | `8080` | `0` để tắt dashboard |
| `UI_HOST` | `127.0.0.1` | Docker đặt `0.0.0.0` |

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

`scripts/bench.py` đo phần mạng của chuỗi mà không cần mic: nó tự tổng hợp giọng
"người dùng" bằng Edge TTS rồi nạp vào STT, nên chạy được ở mọi máy và đồng thời
chấm luôn độ chính xác STT.

```bash
.venv/bin/python scripts/bench.py --repeat 3
TTS_ENGINE=edge .venv/bin/python scripts/bench.py     # so sánh engine
.venv/bin/python scripts/bench.py --voices            # xếp hạng giọng đọc
```

Đo trên máy dev tại Việt Nam, `--repeat 3`, n=9:

| | p50 | min | max |
|---|---|---|---|
| STT `openai/whisper-large-v3` | 703ms | 656 | 1235 |
| LLM `gemini-3.5-flash-lite` → token đầu | 984ms | 782 | 3282 |
| TTS `piper/vi_VN-vais1000-medium` | 93ms | 63 | 203 |
| **Tổng** | **2297ms** | 1547 | 4078 |

Độ chính xác STT: 85% (so từng từ với câu gốc).

### Đã cắt được gì

**Bỏ vòng LLM thứ hai cho lệnh điều khiển thiết bị.** Mỗi tool điều khiển trả kèm
trường `speech` — câu xác nhận đã viết sẵn. Pipeline đọc thẳng câu đó và gọi
`FunctionCallResultProperties(run_llm=False)`, thay vì gửi kết quả tool ngược lại
cho model để nó diễn đạt. Câu nói vẫn được ghi vào ngữ cảnh
(`TTSSpeakFrame(append_to_context=True)`) nên "tăng thêm hai độ nữa" ở lượt sau vẫn
hiểu đúng. LLM p50 2517ms → 984ms.

Đường lỗi và các tool tra cứu **không** có `speech`, vẫn đi qua model — vì đó mới là
phần biết cách hỏi lại cho tự nhiên.

**TTS chạy local.** Xem bảng đo trong `voice_agent/config.py`. Piper là lựa chọn duy
nhất có đuôi latency bị chặn: không có mạng trên đường trả lời thì không bị bóp băng
thông, không chết giữa đường vì nhà cung cấp.

### Chọn giọng bằng số, không bằng cảm tính

`--voices` cho mỗi giọng đọc một câu đã biết trước rồi đưa qua STT — cái gì còn
sót lại là điểm. Không đo được độ tự nhiên, nhưng đo được **độ rõ**, và trong xe
có tiếng ồn thì đó mới là thứ quyết định.

| giọng | STT đọc lại đúng |
|---|---|
| `piper/vi_VN-vais1000-medium` | **79%** |
| `edge/vi-VN-HoaiMyNeural` | 75% |
| `piper/vi_VN-25hours_single-low` | 53% |

Giọng Piper mặc định rõ hơn giọng Edge, dù nghe máy hơn. File nghe thử cả ba:
[`data/samples/`](data/samples/).

### Còn lại

STT 703ms giờ là mảng lớn nhất, nhưng chạy local **không** giải quyết được:
`faster-whisper small` trên CPU mất 2063ms — chậm gấp 3 lần gọi API. Đường CUDA
báo thiếu `cublas64_12.dll` (cần cài CUDA 12 runtime + cuDNN, không có sẵn).
Hướng còn lại là streaming ASR để STT chạy chồng lên lúc người dùng đang nói, thay
vì đợi nói xong mới upload — OpenRouter `/audio/transcriptions` chỉ nhận file nên
sẽ phải đổi nhà cung cấp cho nhánh này.

## Chi phí

Ước tính 1 lượt: user nói 3s, agent trả lời 6s, 1 tool call.

| | Đơn giá | Tiền/lượt |
|---|---|---|
| STT `whisper-large-v3` | $0.006/phút | $0.0003 |
| LLM in (~900 token: system prompt + 7 schema tool) | $0.30/1M | $0.0003 |
| LLM out (~60 token) | $2.50/1M | $0.0002 |
| TTS | chạy local | $0 |
| **Tổng** | | **~$0.0008** |

TTS local là phần cắt lớn nhất — qua API nó chiếm ~80% chi phí mỗi lượt.

**Chi thật:** toàn bộ khảo sát model, benchmark và phát triển tính tới lúc này
tốn **$0.042**. Cả quá trình làm bài + demo ước tính dưới **$3**. Vận hành thật
≈ $0.5/tháng/xe với 20 lượt/ngày.

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
- **TTS** — **không mock**, Piper chạy thật trên máy.

## Cấu trúc

```
voice_agent/
├── __main__.py          entrypoint
├── config.py            env var + system prompt
├── app.py               lắp pipeline Pipecat
├── metrics.py           LatencyProbe — đo FAL
├── schema.py            hàm Python → JSON schema cho LLM
├── tts.py               chọn engine TTS + EdgeTTSService
├── ui.py                dashboard: event bus + UIProbe
├── static/index.html    trang dashboard (1 file, không framework)
└── tools/
    ├── __init__.py      registry + dispatch (không bao giờ raise)
    ├── vehicle.py       mock thiết bị trên xe
    ├── knowledge.py     BM25 trên sổ tay
    └── web.py           Tavily, mock nếu thiếu key
data/kb/                 sổ tay VF 8 2026
data/piper/              model giọng đọc, tự tải lần chạy đầu (gitignore)
data/samples/            3 file nghe thử giọng
scripts/fetch_kb.py      nạp KB từ om.vinfastauto.com
scripts/bench.py         đo latency + xếp hạng giọng, không cần mic
scripts/demo_ui.py       phát lại hội thoại mẫu vào dashboard, không cần mic
tests/                   82 test, không cần API key
docs/                    kiến trúc + lý do các quyết định
```

**Thêm tool = thêm 1 hàm** vào module trong `tools/` rồi đưa vào `TOOLS` của
module đó. Type hint và docstring Google-style là hợp đồng với LLM;
`schema.py` tự sinh JSON schema. Pipeline không phải sửa.
