# Kết quả đo

Mọi con số dưới đây đến từ lệnh chạy được, không phải từ tài liệu nhà cung cấp hay
ước lượng. Máy đo: laptop Windows 11, Việt Nam, mạng gia đình.

Chạy lại:

```bash
.venv/bin/python scripts/e2e.py             # nguyên pipeline, không cần mic
.venv/bin/python scripts/bench.py --repeat 3 # từng chặng mạng
.venv/bin/python scripts/bench.py --voices   # xếp hạng giọng đọc
```

## 1. First Audio Latency

Định nghĩa theo mục 3 đề bài: từ lúc hệ thống xác định người dùng ngừng nói
(`UserStoppedSpeakingFrame`) tới frame âm thanh đầu tiên của câu trả lời
(`TTSAudioRawFrame`). Đo bởi `voice_agent/metrics.py`, đặt ngay trước transport output
nên nó thấy đúng frame sắp ra loa.

Hai lần chạy `scripts/e2e.py`, mỗi lần 5 lượt:

| | lần 1 | lần 2 |
|---|---|---|
| p50 | **1016 ms** | **1172 ms** |
| p95 | 2672 ms | 3203 ms |
| max | 2672 ms | 3203 ms |

**Đạt yêu cầu <2 s ở p50.** Đuôi p95 là lượt tra sổ tay — lượt duy nhất còn phải đi qua
hai vòng LLM, vì kết quả tìm kiếm cần model tóm tắt (xem mục 7).

**Chưa trừ**: device output buffer (~20-40 ms). Số báo lạc quan hơn thực tế chừng đó.

## 2. Từng chặng

`scripts/bench.py --repeat 3`, n=9:

| chặng | p50 | min | max |
|---|---|---|---|
| STT `openai/whisper-large-v3` | 703 ms | 656 | 1235 |
| LLM `gemini-3.5-flash-lite` → token đầu | 984 ms | 782 | 3282 |
| TTS `piper/vi_VN-vais1000-medium` | 93 ms | 63 | 203 |
| **tổng** | **2297 ms** | 1547 | 4078 |

Bottleneck theo thứ tự: **LLM → STT → TTS**. TTS gần như biến mất khỏi ngân sách sau
khi chuyển sang chạy local.

## 3. Chọn model bằng số đo

Cùng một câu, 3 lần chạy mỗi model.

### STT — audio 3 giây

| model | p50 | ổn định | giá |
|---|---|---|---|
| **`openai/whisper-large-v3`** | **0.70 s** | ✅ | $0.0003 |
| `openai/gpt-4o-mini-transcribe` | 0.95 s | ✅ | $0.00005 |
| `openai/gpt-4o-transcribe` | 0.81–6.88 s | ❌ | $0.0001 |
| `openai/whisper-1` | 1.6–5.7 s | ❌ | $0.0003 |
| `deepgram/nova-3` | 1.0–5.1 s | ❌ | $0.0002 |

Chọn `whisper-large-v3` vì **đuôi ổn định**, không phải vì p50 thấp nhất. Với FAL thì
một lượt 5 giây phá trải nghiệm nhiều hơn là 20 lượt nhanh hơn 100 ms bù lại được.

### LLM — thời gian tới token đầu tiên (streaming)

| model | p50 |
|---|---|
| **`google/gemini-3.5-flash-lite`** | **0.99 s** |
| `google/gemini-3.1-flash-lite` | 1.30 s |
| `google/gemini-3.6-flash` | 1.73 s |
| `openai/gpt-5-mini` | 2.98 s |

Đo TTFT chứ không đo tổng thời gian: pipeline đẩy câu đầu tiên sang TTS ngay khi nó
hoàn chỉnh, nên phần còn lại của câu trả lời không nằm trong FAL.

### TTS — thời gian tới byte âm thanh đầu tiên

| | TTFB | ghi chú |
|---|---|---|
| **piper `vi_VN-vais1000-medium`** | **93 ms** | local, không key, không giới hạn |
| edge-tts `vi-VN-HoaiMyNeural` | 438 ms | **3063 ms** khi gọi liên tục |
| `gemini-2.5-flash-preview-tts` | 3469 ms | trả cả khối, không stream |
| `gemini-3.1-flash-tts-preview` | 10985 ms | trả cả khối, không stream |
| OpenRouter `/audio/speech` | — | **không có giọng tiếng Việt** |

OpenRouter `/audio/speech` chỉ nhận `hexgrad/kokoro-82m` (en, ja, zh, es, fr, hi, it,
pt) và `deepgram/aura-2` (5 ngôn ngữ châu Âu). Đã thử gọi thẳng để xác nhận, không
suy đoán từ tài liệu.

Hai model Gemini TTS có API tên là `generate_content_stream` nhưng TTFB đúng bằng tổng
thời gian — nghĩa là không có chunk trung gian nào.

## 4. Chất lượng giọng, đo bằng máy

`bench.py --voices`: mỗi giọng đọc một câu đã biết, đưa qua chính STT của hệ thống,
phần chữ còn sót lại là điểm.

| giọng | STT đọc lại đúng |
|---|---|
| **`piper/vi_VN-vais1000-medium`** | **79 %** |
| `edge/vi-VN-HoaiMyNeural` | 75 % |
| `piper/vi_VN-25hours_single-low` | 53 % |

Không đo được độ tự nhiên — cái đó cần tai người, file mẫu ở `data/samples/`. Nhưng đo
được **độ rõ**, và trong xe có tiếng ồn thì đó mới là thứ quyết định.

Một giới hạn đã biết của thước đo này: nó không chuẩn hoá số, nên "hai mươi hai" được
STT ghi thành "22" bị tính là ba từ sai. Mọi giọng đều chịu như nhau nên thứ hạng vẫn
đúng, chỉ là điểm tuyệt đối thấp hơn thực tế vài phần trăm.

## 5. Chạy end-to-end

`scripts/e2e.py` dựng **chính pipeline của sản phẩm** qua `app.build_task()` — cùng
Silero VAD, cùng turn detection, cùng `dispatch`, cùng `LatencyProbe`, cùng luồng sự
kiện dashboard — chỉ thay mic và loa bằng file. Audio được bơm vào **đúng tốc độ thật**;
tua nhanh sẽ khiến VAD chốt hết lượt sớm và cho ra con số không ai đạt được ngoài đời.

Kết quả assert dựa trên sự kiện thật (tool nào chạy, agent nói gì), không dựa vào trạng
thái xe — vì một lượt có thể "đúng trạng thái" trong khi agent đang làm việc hoàn toàn
khác. Chuyện đó đã xảy ra: lượt "Mở cửa sổ" từng báo đạt trong khi agent thực ra đang
tra Internet cho một câu nghe nhầm, chỉ vì cửa sổ tình cờ vẫn đóng.

**5/5 lượt đạt, exit code 0.**

| người dùng nói | STT nghe | tool | agent trả lời | ✓ |
|---|---|---|---|---|
| Bật điều hòa hai mươi tư độ | Bật điều hòa 24 độ. | `set_ac` | Đã bật điều hòa 24 độ | ✅ |
| Giảm thêm hai độ nữa | Giảm thêm 2 độ nữa. | `adjust_ac_temperature` | Đã giảm còn 22 độ | ✅ |
| Mở cửa sổ | Mở cửa sổ | — | Bạn muốn mở cửa sổ ghế lái hay ghế phụ? | ✅ |
| Ghế lái | Ghê lãi | `set_window` | Đã mở cửa sổ ghế lái 100 phần trăm | ✅ |
| Áp suất lốp bao nhiêu là đúng | Áp suất lốt bao nhiêu là đúng? | `search_manual` | Bạn hãy xem mức áp suất khuyến nghị trên nhãn dán ở cột trụ cửa bên ghế lái… | ✅ |

Lượt 4 đáng chú ý: STT nghe "Ghế lái" thành "Ghê lãi", nhưng vì lượt trước agent vừa
hỏi "ghế lái hay ghế phụ", model vẫn suy ra đúng. Ngữ cảnh đa lượt che được lỗi STT.

Mỗi lượt kiểm đúng một yêu cầu của đề bài:

| lượt | chứng minh điều gì | assert |
|---|---|---|
| 1 | điều khiển thiết bị | `set_ac` đã chạy **và** `STATE` đúng |
| 2 | tham chiếu ngữ cảnh lượt trước | `adjust_ac_temperature` chạy, nhiệt độ = 22 |
| 3 | hỏi lại khi thiếu thông tin | **không** tool nào chạy, câu trả lời có "?", state không đổi |
| 4 | hiểu câu trả lời cho câu hỏi lại | `set_window` chạy, cửa sổ mở |
| 5 | tra sổ tay | `search_manual` chạy, câu trả lời đủ dài |

## 6. Chi phí thật

| | đơn giá | tiền/lượt |
|---|---|---|
| STT `whisper-large-v3` | $0.006/phút | $0.0003 |
| LLM vào (~900 token) | $0.30/1M | $0.0003 |
| LLM ra (~60 token) | $2.50/1M | $0.0002 |
| TTS | chạy local | $0 |
| **tổng** | | **~$0.0008** |

Đơn giá lấy từ `usage.cost` OpenRouter trả về trong response, không lấy từ bảng giá.

**Đã tiêu thật**: toàn bộ khảo sát model, benchmark, phát triển và chạy e2e tốn
**$0.05**. Vận hành ước tính $0.5/tháng/xe với 20 lượt/ngày.

## 7. Những gì đo được mà thiết kế ban đầu không lường

Ghi lại vì đây là phần đáng giá nhất của việc đo thật.

**TTS qua API là ngõ cụt cho tiếng Việt.** Kế hoạch ban đầu là cả ba chặng đi qua một
key OpenRouter. Gọi thử `/audio/speech` mới biết nó không có giọng Việt nào. Thử tiếp
Gemini TTS thì phát hiện nó không stream. Kết cục là TTS chạy local — nhanh hơn 4 lần,
miễn phí, và tự nhiên ăn luôn điểm cộng "thiết kế edge" mục 8.

**Vòng LLM thứ hai là chi phí lớn nhất còn lại.** Với lệnh điều khiển thiết bị, kết quả
`{"temp": 22}` chỉ có đúng một cách nói, nên bắt model diễn đạt lại tốn nguyên một vòng
mạng mà không thêm thông tin. Bỏ nó đi: LLM p50 2517 ms → 984 ms.

**VAD chưa từng được nối.** `LocalAudioTransportParams(vad_analyzer=...)` được Pipecat
1.7 nhận im lặng rồi bỏ qua — trường đó đã bị chuyển sang `VADProcessor` riêng. Code
trông đúng, khởi động không báo gì, và pipeline câm hoàn toàn. Chỉ có lần chạy e2e thật
mới lộ ra. Đây là lý do một bài kiểm thử đơn vị xanh không thay được một lần chạy thật.

**Sáu lỗi đóng gói chỉ lộ khi build Docker.** `pyaudio` không có wheel Linux nên phải
biên dịch; `av` và `loguru` được import trực tiếp nhưng chỉ có mặt nhờ dependency của
Pipecat. `tests/test_packaging.py` giờ quét AST toàn bộ source và chặn loại lỗi này
trong một giây thay vì mười phút build.
