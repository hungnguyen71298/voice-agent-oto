# Kiến trúc hệ thống

## 1. Tổng thể

```
┌──────────────────────── máy người dùng (trên xe) ────────────────────────┐
│                                                                          │
│   mic ──► LocalAudioTransport ──► SileroVAD ──┐                          │
│                                                │                          │
│   loa ◄── LocalAudioTransport ◄── LatencyProbe ◄──┐                      │
│                                                    │                      │
│                        tools/  (vehicle mock, BM25 KB)                    │
│                              ▲          │                                 │
└──────────────────────────────┼──────────┼─────────────────────────────────┘
                               │          │
                    ┌──────────┴──────────▼──────────┐
                    │      OpenRouter (1 API key)     │
                    │  STT  ──►  LLM  ──►  TTS        │
                    └─────────────────────────────────┘
```

Toàn bộ xử lý âm thanh, VAD, tool execution và knowledge base chạy **local**.
Chỉ 3 lời gọi mạng ra ngoài: STT, LLM, TTS — đều qua một endpoint OpenRouter.

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
      │         ├─ nếu trả tool_call → dispatch() → kết quả → gọi LLM lượt 2
      │         └─ nếu trả text      → đẩy thẳng sang TTS
      │
      ├─ TTS   stream PCM 24kHz ──────────► OpenRouter
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

## 4. Điểm mở rộng

| Muốn gì | Sửa ở đâu |
|---|---|
| Thêm thiết bị trên xe | 1 hàm trong `tools/vehicle.py` |
| Đổi STT/LLM/TTS | env var, không sửa code |
| Nối CAN bus thật | thay thân hàm trong `tools/vehicle.py`, giữ nguyên chữ ký |
| KB dòng xe khác | `python scripts/fetch_kb.py VF9 2026` |
| Retrieval chính xác hơn | rerank trong `tools/knowledge.py:search_manual` |
| Search thật | set `TAVILY_API_KEY`, code đã sẵn |
