# Kiến trúc hệ thống

## 1. Tổng thể

```
┌──────────────────────── máy người dùng (trên xe) ─────────────────────────┐
│                                                                           │
│   mic ──► LocalAudioTransport ──► SileroVAD ──┐                           │
│                                               │                           │
│   loa ◄── LocalAudioTransport ◄── LatencyProbe ◄── Piper TTS ◄─┐          │
│                                                                │          │
│                        tools/  (vehicle mock, BM25 KB) ────────┘          │
│                              ▲          │       câu xác nhận đọc thẳng     │
└──────────────────────────────┼──────────┼─────────────────────────────────┘
                               │          │
                    ┌──────────┴──────────▼──────────┐
                    │      OpenRouter (1 API key)    │
                    │        STT  ──►  LLM           │
                    └────────────────────────────────┘
```

Xử lý âm thanh, VAD, **TTS**, tool execution và knowledge base đều chạy **local**.
Chỉ hai lời gọi mạng ra ngoài: STT và LLM, qua cùng một endpoint OpenRouter.

TTS không đi qua OpenRouter vì OpenRouter **không có giọng tiếng Việt nào** — đã
kiểm chứng bằng cách gọi thẳng `/audio/speech`: chỉ nhận `hexgrad/kokoro-82m`
(8 ngôn ngữ, không có `vi`) và `deepgram/aura-2` (5 ngôn ngữ châu Âu). Bảng đo các
phương án thay thế nằm trong `voice_agent/config.py`.

## 2. Luồng xử lý voice

```
 t=0  người dùng bắt đầu nói
      │
      ├─ SileroVAD phát hiện có tiếng      → UserStartedSpeakingFrame
      │                                     → nếu TTS đang phát: ngắt (barge-in)
      │
      ├─ audio 16kHz PCM đệm lại
      │
 t=T  im lặng đủ lâu → VAD chốt hết lượt   → UserStoppedSpeakingFrame
      │                                     └─► LatencyProbe bấm giờ t0
      │
      ├─ STT   upload audio  ─────────────► OpenRouter → transcript
      │
      ├─ aggregator ghép transcript vào lịch sử hội thoại
      │
      ├─ LLM   stream ────────────────────► OpenRouter
      │         ├─ trả text     → đẩy thẳng sang TTS
      │         └─ trả tool_call → dispatch()
      │              ├─ kết quả có "speech"  → đọc thẳng, KHÔNG gọi LLM lượt 2
      │              └─ kết quả không có     → gửi lại cho LLM diễn đạt
      │
      ├─ TTS   Piper sinh PCM 22.05kHz ngay trên máy
      │
 t=A  frame audio đầu tiên tới LatencyProbe → ghi FAL = A − T
      │
      └─ loa phát
```

**First Audio Latency = A − T**, đúng định nghĩa mục 3 đề bài: từ lúc hệ thống
xác định người dùng kết thúc lượt nói đến frame âm thanh đầu tiên của phản hồi.

Đo bởi `voice_agent/metrics.py:LatencyProbe`, đặt ngay trước `transport.output()`
nên nó thấy đúng frame sắp ra loa. Chưa trừ device output buffer (~20-40ms).

## 3. Thiết kế Agent và tool

### Ranh giới

```
voice_agent/tools/*.py       hàm Python thuần, không import Pipecat
        │
        │  to_schema()  ← ranh giới DUY NHẤT
        ▼
voice_agent/schema.py        đọc type hint + docstring → FunctionSchema
        │
        ▼
voice_agent/app.py           đăng ký handler vào LLM service
```

Nhờ tách như vậy: đổi framework agent (Pipecat → LiveKit → tự viết) chỉ phải viết
lại `schema.py` + `app.py`; toàn bộ logic nghiệp vụ và test không đụng tới.

### Hợp đồng của một tool

```python
def set_ac(on: bool, temperature: int | None = None) -> dict:
    """Bật/tắt điều hòa và đặt nhiệt độ.        ← thành description của tool

    Args:
        on: True để bật, False để tắt điều hòa.  ← thành description của tham số
        temperature: Nhiệt độ mong muốn, 16-30 độ C. Bỏ trống nếu chỉ bật/tắt.
    """
```

- Type hint → kiểu JSON schema. `int | None` → `integer` và **không** bắt buộc.
- Tham số không có giá trị mặc định → nằm trong `required`.
- Docstring là hợp đồng với LLM: đổi chữ trong docstring là đổi hành vi model.

**Thêm tool = thêm 1 hàm + đưa vào `TOOLS` của module đó.** Không sửa pipeline.

### Nguyên tắc: tool không bao giờ raise

`dispatch()` bọc mọi lời gọi và trả `{"status": "error", "message": ...}`. Lý do:
LLM sinh sai tên tool / sai kiểu tham số / thiếu tham số là chuyện thường xuyên.
Ném exception thì chết pipeline; trả error dict thì model đọc được và tự sửa ở
lượt sau. `dispatch()` cũng chặn sai kiểu trước khi gọi hàm, vì `set_ac(on="có")`
không raise mà âm thầm coi chuỗi là truthy.

Mọi hàm validate xong mới mutate `STATE` — đường lỗi không được để lại thay đổi
một nửa. Đây là lỗi đã xảy ra thật và có test riêng (`test_vehicle.py`).

### Đường tắt `speech`: bỏ vòng LLM thứ hai

Vòng đời chuẩn của một tool call là hai lời gọi LLM: một để model quyết định gọi
tool, một để nó đọc kết quả và diễn đạt thành câu. Với lệnh điều khiển thiết bị,
lời gọi thứ hai không thêm thông tin gì — kết quả `{"temp": 22}` chỉ có đúng một
cách nói. Nhưng nó tốn nguyên một vòng mạng: **LLM p50 2517ms → 984ms** sau khi bỏ.

Nên mỗi tool điều khiển trả kèm trường `speech` — câu xác nhận viết sẵn:

```python
{"device": "ac", "status": "success", "speech": "Đã giảm còn 22 độ", "temp": 22}
```

`app.py` thấy `speech` thì đẩy `TTSSpeakFrame(speech, append_to_context=True)` và
trả kết quả kèm `FunctionCallResultProperties(run_llm=False)`. `append_to_context`
là phần quan trọng: câu vừa nói vẫn vào lịch sử hội thoại, nên lượt sau nói "tăng
thêm hai độ nữa" model vẫn hiểu.

Hai loại kết quả **cố ý không** có `speech`:

- **Đường lỗi.** "Nhiệt độ phải từ 16 đến 30 độ" cần model hỏi lại cho tự nhiên,
  chứ không phải đọc nguyên câu lỗi cho người đang lái xe.
- **Tool tra cứu.** `search_manual` trả về 3 đoạn văn bản thô; cần model tóm tắt.

Ranh giới này có test (`test_vehicle.py::test_errors_carry_no_speech`,
`test_lookup_tools_carry_no_speech`) vì thêm nhầm `speech` vào chỗ không nên có
sẽ khiến agent đọc dữ liệu thô ra loa mà không ai phát hiện lúc review.

### Hội thoại nhiều lượt và làm rõ yêu cầu

- **Ngữ cảnh**: `LLMContextAggregatorPair` giữ lịch sử hội thoại. Các tool tương
  đối (`adjust_ac_temperature`, `adjust_fan`) cho phép "giảm thêm 2 độ" mà không
  cần model biết nhiệt độ hiện tại.
- **Làm rõ**: `set_window` bắt buộc có `position`, và docstring ghi rõ "nếu người
  dùng không nói thì hỏi lại". System prompt nhắc lại nguyên tắc này. "Mở cửa sổ"
  → agent hỏi "Bạn muốn mở cửa sổ nào?" thay vì đoán.

### Knowledge Base

`data/kb/*.md` (sổ tay VinFast VF 8 thật) được chunk và dựng index BM25 lúc import
module — ~250ms một lần, sống suốt process.

Hai điều chỉnh riêng cho tiếng Việt:

1. **Chunk mang theo heading gần nhất.** Đoạn nói về sấy kính trong sổ tay không
   chứa chữ "sấy kính" nào; heading là thứ duy nhất khớp được query.
2. **Token gồm bigram âm tiết.** Tiếng Việt tách theo âm tiết thì "áp", "suất",
   "lốp" đều quá phổ biến để phân biệt; bigram `áp_suất` mới mang nghĩa từ ghép.

## 4. Dashboard demo

```
pipeline ──► ui.emit(kind, ...) ──► asyncio.Queue mỗi tab ──SSE──► trình duyệt
   ▲                                                                    │
   └── UIProbe đứng cuối pipeline, chỉ đọc frame, luôn push_frame ──────┘
```

Trang chỉ **quan sát**. Đưa trình duyệt vào đường âm thanh sẽ thêm một chặng mạng
vào đúng con số đề bài chấm, nên mic vẫn ở máy chạy pipeline. Hệ quả: luồng dữ liệu
một chiều, và SSE là đủ — không cần WebSocket, không thêm thư viện (`aiohttp` đã
là dependency của Pipecat).

Ba nguyên tắc để dashboard không bao giờ làm hỏng pipeline:

1. **`UIProbe` luôn `push_frame`.** Nuốt một frame là câm cả hệ thống. Có test.
2. **`emit` dùng `put_nowait`.** Một tab treo chỉ mất sự kiện của chính nó, không
   chặn vòng audio. Có test.
3. **Tắt được hoàn toàn** bằng `UI_PORT=0`; pipeline không phụ thuộc vào nó.

`scripts/demo_ui.py` phát lại một hội thoại mẫu vào dashboard — không mic, không
API key. Tool trong đó chạy thật qua `dispatch` nên panel trạng thái xe hoạt động
đúng như phiên thật; chỉ số thời gian là bịa.

## 5. Điểm mở rộng

| Muốn gì | Sửa ở đâu |
|---|---|
| Thêm thiết bị trên xe | 1 hàm trong `tools/vehicle.py` |
| Đổi STT/LLM/TTS | env var, không sửa code |
| Nối CAN bus thật | thay thân hàm trong `tools/vehicle.py`, giữ nguyên chữ ký |
| KB dòng xe khác | `python scripts/fetch_kb.py VF9 2026` |
| Retrieval chính xác hơn | rerank trong `tools/knowledge.py:search_manual` |
| Search thật | set `TAVILY_API_KEY`, code đã sẵn |
| Thêm thứ lên dashboard | `ui.emit(...)` ở chỗ phát sinh + 1 nhánh trong `index.html` |
