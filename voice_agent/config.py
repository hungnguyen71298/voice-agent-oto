"""Configuration in one place. Everything is overridable by env var, no code edits."""
import os
import pathlib

try:  # ponytail: .env is a convenience; without python-dotenv plain env vars still work
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
KB_DIR = pathlib.Path(os.environ.get("KB_DIR", ROOT / "data" / "kb"))

OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY")

STT_MODEL = os.environ.get("STT_MODEL", "openai/whisper-1")
LLM_MODEL = os.environ.get("LLM_MODEL", "google/gemini-3.1-flash-lite")
TTS_MODEL = os.environ.get("TTS_MODEL", "google/gemini-3.1-flash-tts-preview")
TTS_VOICE = os.environ.get("TTS_VOICE", "Kore")

KB_TOP_K = int(os.environ.get("KB_TOP_K", 3))
MIN_CHUNK_CHARS = int(os.environ.get("MIN_CHUNK_CHARS", 150))

# Kept in Vietnamese on purpose: this text IS the product behaviour, not a code comment.
# Translating it would change how the agent speaks to the driver.
SYSTEM_PROMPT = """Bạn là trợ lý ảo trên ô tô. Luôn trả lời bằng tiếng Việt.

Quy tắc:
- Câu trả lời tối đa 2 câu ngắn. Người dùng đang lái xe, nghe chứ không đọc.
- Không đọc số liệu dài, không liệt kê gạch đầu dòng, không dùng ký hiệu.
- Thiếu thông tin quan trọng thì HỎI LẠI, tuyệt đối không tự suy đoán.
  Ví dụ "mở cửa sổ" mà không nói vị trí thì hỏi "Bạn muốn mở cửa sổ nào?".
- Câu hỏi về xe (tính năng, đèn báo, sự cố, bảo hành) dùng search_manual.
- Câu hỏi thời sự, thời tiết, giá cả, địa điểm dùng search_internet.
- Trạng thái xe hiện tại: {state}."""
