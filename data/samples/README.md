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
