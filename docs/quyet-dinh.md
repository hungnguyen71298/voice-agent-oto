# Các quyết định kỹ thuật

Mỗi mục: chọn gì, vì sao, đánh đổi gì, và điều kiện nào thì nên đổi ý.

## 1. Cascaded pipeline thay vì realtime speech-to-speech API

**Chọn**: `STT → LLM → TTS` rời nhau, thay vì Gemini Live / OpenAI Realtime.

**Vì sao**

- Đề bài mục 2.1 vẽ đúng luồng cascaded. Yêu cầu bắt buộc là FAL < 2s, không phải
  realtime API. Cascaded ước tính 0.65-1.6s — còn biên.
- **Chi phí vận hành**: realtime API tính tiền theo *thời gian mic mở*, cascaded
  tính theo *lượt nói thật*. Xe chạy 1 tiếng mic mở, realtime tính đủ 60 phút audio
  input dù người dùng chỉ nói 1 phút.

  | | Cascaded | Realtime |
  |---|---|---|
  | 1 xe, 20 lượt/ngày, 30 ngày | ~$3/tháng | ~$15-40/tháng |
  | 10.000 xe | ~$30k/năm | ~$150-400k/năm |

- **Tự do đổi model**: 1 key OpenRouter, đổi STT/LLM/TTS bằng env var → benchmark
  nhiều model gần như miễn phí (đề bài mục 8, điểm cộng).
- **Mở đường edge**: thay STT/TTS bằng model local mà không đụng kiến trúc
  (đề bài mục 8, điểm cộng). Realtime API thì không.

**Đánh đổi**

- Time-to-answer chậm hơn realtime API khoảng 2×.
- Turn detection do Silero VAD lo thay vì server → phải tự calib ngưỡng.
- Barge-in tự quản (nhưng dễ hơn: mình sở hữu output buffer).

**Đổi ý khi**: đo thực tế FAL > 2s sau khi đã áp hết tối ưu ở mục 5, hoặc yêu cầu
chuyển sang hội thoại chồng lấn thật sự (cả hai cùng nói).

## 2. OpenRouter thay vì gọi thẳng từng nhà cung cấp

**Chọn**: mọi lời gọi STT/LLM/TTS qua `https://openrouter.ai/api/v1`.

**Vì sao**: 1 key, 1 tài khoản, 1 hoá đơn. Đổi model là đổi chuỗi. Ba endpoint
đều tương thích OpenAI nên client của Pipecat dùng được nguyên.

**Đánh đổi**: thêm một chặng proxy. Đo thực tế trên máy dev tại Việt Nam: RTT
ICMP tới edge 44ms, HTTPS cold 375ms / warm ~176ms — chấp nhận được.

**Lưu ý**: OpenRouter **không** route Gemini Live / realtime WebSocket. Muốn dùng
realtime của Google phải lấy key trực tiếp từ AI Studio.

## 3. Pipecat thay vì tự viết vòng audio

**Chọn**: Pipecat 1.7, transport `local`.

**Vì sao**: có sẵn Silero VAD, ngắt lời, streaming ba tầng, và **metrics TTFB từng
service** — đúng thứ đề bài mục 3 yêu cầu ("đo latency thực tế, chỉ ra bottleneck").
Tự viết mất ~4 ngày và VAD energy-based tự calib sẽ tệ hơn Silero.

Đề bài mục 5 cho phép framework agent ("AutoGen, LangGraph, ADK... hoặc tương đương").

**Đánh đổi**: một dependency lớn. Bù lại logic nghiệp vụ nằm hoàn toàn trong
`tools/` không import Pipecat, nên đổi framework không phải viết lại nghiệp vụ.

## 4. BM25 thay vì vector embedding

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

## 5. Knowledge base dùng dữ liệu thật, không mock

**Chọn**: sổ tay hướng dẫn sử dụng VinFast VF 8 (2026), tiếng Việt, 12 chương,
530k ký tự — lấy từ API công khai của om.vinfastauto.com.

**Vì sao**: đề bài cho phép mock nhưng dữ liệu thật lộ ra vấn đề mà dữ liệu bịa
không bao giờ lộ. Chuyển sang dữ liệu thật đã bắt được hai lỗi retrieval ngay:
file mock ngắn thắng BM25 trước tài liệu thật, và chunk mất heading làm query trượt.

**Đánh đổi**: phụ thuộc một API không có tài liệu công bố. `scripts/fetch_kb.py`
tách riêng, dữ liệu commit vào repo nên hệ thống vẫn chạy khi API đổi.

## 6. Vehicle API mock

**Chọn**: `STATE` — dict trong RAM, một xe, một process.

**Vì sao**: đề bài mục 9 cho phép. Điều đáng chấm là thiết kế tool và chất lượng
hội thoại, không phải tích hợp CAN bus.

**Đường nâng cấp**: giữ nguyên chữ ký hàm, thay thân hàm bằng lời gọi CAN bus hoặc
`CarPropertyManager` của Android Automotive. Test hiện có vẫn dùng lại được.
