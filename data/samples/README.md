# Mẫu giọng đọc

Cùng một câu, ba giọng — nghe để so, vì con số "độ rõ" trong README không nói được
độ tự nhiên.

> Tôi đã giảm nhiệt độ điều hòa xuống hai mươi hai độ cho bạn.

| file | engine / giọng | STT đọc lại đúng |
|---|---|---|
| `piper-vais1000-medium.wav` | piper `vi_VN-vais1000-medium` — **mặc định** | 79% |
| `edge-hoaimy.mp3` | edge `vi-VN-HoaiMyNeural` (`TTS_ENGINE=edge`) | 75% |
| `piper-25hours-single-low.wav` | piper `vi_VN-25hours_single-low` | 53% |

Tự dựng lại: `python scripts/bench.py --voices`.

## e2e/

Đầu vào và đầu ra của `scripts/e2e.py`.

| file | là gì |
|---|---|
| `driver-00..04.wav` | năm câu người dùng, tổng hợp sẵn và **commit vào repo** để lần chạy nào cũng giống hệt nhau và không cần mạng |
| `driver.wav` | năm câu trên nối lại, nghe cho tiện |
| `agent.wav` | agent trả lời gì trong lần chạy gần nhất |

Xoá `driver-*.wav` là chúng được dựng lại từ Edge TTS (Piper nếu Edge bị chặn).
`agent.wav` chỉ sinh khi chạy với `--keep-audio`.
