# Các quyết định kỹ thuật

Mỗi mục: chọn gì, vì sao, đánh đổi gì, và điều kiện nào thì nên đổi ý.

## 1. Cascaded pipeline thay vì realtime speech-to-speech API

**Chọn**: `STT → LLM → TTS` rời nhau, thay vì Gemini Live / OpenAI Realtime.

**Vì sao**

- Đề bài mục 2.1 vẽ đúng luồng cascaded. Yêu cầu bắt buộc là FAL < 2s, không phải
  realtime API.
- **Chi phí vận hành**: realtime API tính tiền theo *thời gian mic mở*, cascaded
  tính theo *lượt nói thật*. Xe chạy 1 tiếng mic mở, realtime tính đủ 60 phút audio
  input dù người dùng chỉ nói 1 phút.

  | | Cascaded (TTS local) | Realtime |
  |---|---|---|
  | 1 xe, 20 lượt/ngày, 30 ngày | ~$0.5/tháng | ~$15-40/tháng |
  | 10.000 xe | ~$60k/năm | ~$1.8-4.8tr/năm |

- **Tự do đổi model**: đổi STT/LLM/TTS bằng env var → benchmark nhiều model gần như
  miễn phí (đề bài mục 8, điểm cộng). Đã dùng đúng khả năng này để chọn cả ba.
- **Mở đường edge**: thay STT/TTS bằng model local mà không đụng kiến trúc
  (đề bài mục 8, điểm cộng). Realtime API thì không. TTS đã đi đường này thật —
  xem mục 3.

**Đánh đổi**

- Time-to-answer chậm hơn realtime API khoảng 2×.
- Turn detection do Silero VAD lo thay vì server → phải tự calib ngưỡng.
- Barge-in tự quản (nhưng dễ hơn: mình sở hữu output buffer).

**Đo được sau khi làm xong**: tổng chuỗi p50 2297ms (STT 703 + LLM 984 + TTS 93),
min 1547ms. Lượt không gọi tool đạt dưới 2s; lượt phải tra sổ tay thì chưa, vì còn
đi qua hai vòng LLM. Xem README mục Latency.

**Đo qua mic thật, 14 lượt**: nhánh local p50 **1000ms** (n=9, dải 906–1094) — đạt.
Nhánh `search_internet` p50 **4938ms** (n=6), chưa lần nào dưới 4 giây. Điều kiện đổi ý
bên dưới vì thế mới thoả một nửa: cascaded đủ nhanh cho phần chạy trên máy, chỗ vượt
mốc nằm ở lượt gọi ra ngoài — và realtime API cũng không sửa được chỗ đó.

**Đổi ý khi**: FAL đo qua mic vẫn > 2s **trên nhánh local** sau khi đã áp hết tối ưu ở
mục 3 và 4, hoặc yêu cầu chuyển sang hội thoại chồng lấn thật sự (cả hai cùng nói).

## 2. OpenRouter cho STT và LLM

**Chọn**: STT và LLM qua `https://openrouter.ai/api/v1`. TTS **không** — xem mục 3.

**Vì sao**: 1 key, 1 tài khoản, 1 hoá đơn. Đổi model là đổi chuỗi. Cả hai endpoint
đều tương thích OpenAI nên client của Pipecat dùng được nguyên.

**Đánh đổi**: thêm một chặng proxy. Đo thực tế trên máy dev tại Việt Nam: RTT
ICMP tới edge 44ms, HTTPS cold 375ms / warm ~176ms — chấp nhận được.

**Model chọn theo số đo, không theo bảng giá.** Cùng một câu, 3 lần chạy:

| STT (audio 3s) | p50 | ổn định |
|---|---|---|
| `openai/whisper-large-v3` | **0.70s** | ✅ |
| `openai/gpt-4o-mini-transcribe` | 0.95s | ✅, rẻ hơn 6× |
| `openai/whisper-1` | 1.6–5.7s | ❌ vọt |
| `deepgram/nova-3` | 1.0–5.1s | ❌ vọt |

| LLM (TTFT streaming) | p50 |
|---|---|
| `google/gemini-3.5-flash-lite` | **0.99s** |
| `google/gemini-3.1-flash-lite` | 1.30s |
| `google/gemini-3.6-flash` | 1.73s |
| `openai/gpt-5-mini` | 2.98s |

Đo lại bất cứ lúc nào bằng `STT_MODEL=... python scripts/bench.py`.

**Lưu ý**: OpenRouter **không** route Gemini Live / realtime WebSocket. Muốn dùng
realtime của Google phải lấy key trực tiếp từ AI Studio.

## 3. TTS chạy local (Piper) thay vì gọi API

**Chọn**: `piper` với giọng `vi_VN-vais1000-medium`, chạy trên CPU của máy.

**Vì sao**: OpenRouter không có giọng tiếng Việt nào — `/audio/speech` chỉ nhận
`hexgrad/kokoro-82m` (en, ja, zh, es, fr, hi, it, pt) và `deepgram/aura-2` (5 ngôn
ngữ châu Âu). Khảo sát các phương án còn lại, đo TTFB:

| | TTFB | ghi chú |
|---|---|---|
| **piper `vi_VN-vais1000-medium`** | **93ms** | local, không key, không giới hạn |
| edge-tts `vi-VN-HoaiMyNeural` | 438ms | nhưng **3063ms** khi gọi liên tục |
| `gemini-2.5-flash-preview-tts` | 3469ms | trả cả khối, không stream |
| `gemini-3.1-flash-tts-preview` | 10985ms | trả cả khối, không stream |

Hai model Gemini TTS có `generate_content_stream` nhưng TTFB đúng bằng thời gian
tổng — nghĩa là không có chunk trung gian nào. Loại thẳng.

edge-tts nhanh khi chạy lẻ nhưng Microsoft bóp băng thông khi gọi dồn, và sau đó
trả `NoAudioReceived` cả với lời gọi đơn, phải nghỉ vài phút mới hồi. Không dùng
làm mặc định được, nhưng giữ lại làm `TTS_ENGINE=edge`.

**Chất lượng giọng đo bằng số**: cho mỗi giọng đọc một câu đã biết rồi đưa qua
chính STT của hệ thống, phần chữ còn sót lại là điểm (`bench.py --voices`).

| giọng | STT đọc lại đúng |
|---|---|
| `piper/vi_VN-vais1000-medium` | **79%** |
| `edge/vi-VN-HoaiMyNeural` | 75% |
| `piper/vi_VN-25hours_single-low` | 53% |

Không đo được độ tự nhiên, nhưng đo được độ rõ — thứ quyết định trong xe có ồn.

**Đánh đổi**: giọng Piper nghe máy hơn Edge. Gói `piper-tts` in-process là GPL-3.0;
nếu sản phẩm đóng gói thương mại thì chuyển sang `PiperHttpTTSService`.

**Được thêm**: đây chính là điểm cộng "thiết kế edge / hybrid" mục 8 đề bài, và
cắt ~80% chi phí mỗi lượt.

**Đổi ý khi**: cần giọng tự nhiên hơn hẳn cho demo → ElevenLabs Flash v2.5
(~75ms, WebSocket giữ kết nối, Pipecat có sẵn service), đổi 1 class trong `tts.py`.

## 4. Bỏ vòng LLM thứ hai cho lệnh điều khiển

**Chọn**: tool điều khiển trả kèm câu xác nhận `speech`; pipeline đọc thẳng và
gọi `FunctionCallResultProperties(run_llm=False)`.

**Vì sao**: kết quả `{"temp": 22}` chỉ có đúng một cách nói. Bắt model diễn đạt lại
tốn nguyên một vòng mạng mà không thêm thông tin. **LLM p50 2517ms → 984ms.**

**Đánh đổi**: câu xác nhận cố định, kém linh hoạt hơn model tự viết. Chấp nhận
được vì đây là loại câu ngắn nhất và lặp nhiều nhất.

**Ranh giới**: đường lỗi và tool tra cứu cố ý **không** có `speech` — chúng cần
model diễn đạt. Có test giữ ranh giới này.

## 5. Pipecat thay vì tự viết vòng audio

**Chọn**: Pipecat 1.7, transport `local`.

**Vì sao**: có sẵn Silero VAD, ngắt lời, streaming ba tầng, và **metrics TTFB từng
service** — đúng thứ đề bài mục 3 yêu cầu ("đo latency thực tế, chỉ ra bottleneck").
Tự viết mất ~4 ngày và VAD energy-based tự calib sẽ tệ hơn Silero.

Đề bài mục 5 cho phép framework agent ("AutoGen, LangGraph, ADK... hoặc tương đương").

**Đánh đổi**: một dependency lớn. Bù lại logic nghiệp vụ nằm hoàn toàn trong
`tools/` không import Pipecat, nên đổi framework không phải viết lại nghiệp vụ.

## 6. BM25 thay vì vector embedding

**Chọn**: `rank_bm25` in-memory, không vector DB, không embedding.

**Vì sao**: đề bài mục 2.4 ghi rõ "có thể dùng bm25 để retrieve, không nhất thiết
phải dùng model embedding". Index 850 chunk dựng trong 250ms, query 3ms, 0 đồng,
0 lời gọi mạng trên nhánh KB.

**Trần đã đo được**: vocabulary mismatch. Hỏi "chìa khóa thông minh hết pin" không
khớp đoạn viết "pin chìa khóa điều khiển từ xa hết điện", dù đó đúng là nội dung
cần tìm.

**Đường nâng cấp đã khảo sát**: BM25 lấy top-20 rồi rerank bằng `baai/bge-m3` trên
OpenRouter — $0.01/1M token, embed toàn bộ KB tốn ~$0.002 một lần và cache xuống
đĩa, mỗi query thêm ~100-200ms **chỉ trên nhánh KB**. Chưa làm vì chưa đo được là
BM25 có thực sự làm hỏng kịch bản demo hay không.

## 7. Knowledge base dùng dữ liệu thật, không mock

**Chọn**: sổ tay hướng dẫn sử dụng VinFast VF 8 (2026), tiếng Việt, 12 chương,
530k ký tự — lấy từ API công khai của om.vinfastauto.com.

**Vì sao**: đề bài cho phép mock nhưng dữ liệu thật lộ ra vấn đề mà dữ liệu bịa
không bao giờ lộ. Chuyển sang dữ liệu thật đã bắt được hai lỗi retrieval ngay:
file mock ngắn thắng BM25 trước tài liệu thật, và chunk mất heading làm query trượt.

**Đánh đổi**: phụ thuộc một API không có tài liệu công bố. `scripts/fetch_kb.py`
tách riêng, dữ liệu commit vào repo nên hệ thống vẫn chạy khi API đổi.

## 8. Vehicle API mock

**Chọn**: `STATE` — dict trong RAM, một xe, một process.

**Vì sao**: đề bài mục 9 cho phép. Điều đáng chấm là thiết kế tool và chất lượng
hội thoại, không phải tích hợp CAN bus.

**Đường nâng cấp**: giữ nguyên chữ ký hàm, thay thân hàm bằng lời gọi CAN bus hoặc
`CarPropertyManager` của Android Automotive. Test hiện có vẫn dùng lại được.
