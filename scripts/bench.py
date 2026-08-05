"""Measure the STT → LLM → TTS chain without a microphone.

    python scripts/bench.py                 # default models, 3 utterances
    STT_MODEL=openai/gpt-4o-mini-transcribe python scripts/bench.py
    python scripts/bench.py --repeat 5

Test speech is synthesised with Edge TTS, so the same command runs anywhere and
scores STT accuracy against known-good text at the same time.

What this does NOT measure: Silero deciding the user stopped talking, and the audio
device buffer. Both sit outside the network path, and both are in the real number
that `python -m voice_agent` prints. Treat the total here as a floor, not as FAL.
"""
import argparse
import asyncio
import io
import json
import statistics
import sys
import time
import unicodedata
import urllib.request
import wave

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame  # noqa: E402

from voice_agent import config, schema  # noqa: E402
from voice_agent import tts as tts_engine  # noqa: E402
from voice_agent.tools import ALL, dispatch  # noqa: E402
from voice_agent.tts import EDGE_SAMPLE_RATE, EdgeTTSService  # noqa: E402

# One per branch the agent can take: pure device control, a clarification, a KB lookup.
UTTERANCES = [
    "Giảm điều hòa xuống hai độ",
    "Mở cửa sổ",
    "Áp suất lốp xe bao nhiêu là đúng",
]

TOOL_SPECS = [
    {"type": "function", "function": {"name": s.name, "description": s.description,
                                      "parameters": {"type": "object", "properties": s.properties,
                                                     "required": s.required}}}
    for s in (schema.to_schema(f) for f in ALL)
]


def _norm(s: str) -> str:
    """Case-fold and strip punctuation so transcripts compare on words, not typography."""
    s = unicodedata.normalize("NFC", s.lower())
    return " ".join("".join(c for c in s if c.isalnum() or c.isspace()).split())


def word_accuracy(expected: str, got: str) -> float:
    """Fraction of expected words present in the transcript.

    # ponytail: not WER — no alignment, no substitution/deletion split, and no numeral
    # normalisation, so "hai mươi hai" transcribed as "22" scores as three misses. That
    # understates every score here by a few points, evenly. Enough to catch "STT is
    # mangling Vietnamese" and to rank engines; swap in jiwer if a number needs defending.
    """
    want = _norm(expected).split()
    have = set(_norm(got).split())
    return sum(w in have for w in want) / len(want) if want else 0.0


async def synth(text: str) -> bytes:
    """Render `text` to a 16-bit mono WAV, standing in for the driver's microphone.

    Always Edge, never the engine under test: the input has to stay identical when
    TTS_ENGINE changes, or the STT column would move for the wrong reason.
    """
    tts = EdgeTTSService(voice=config.EDGE_VOICE)
    tts._sample_rate = EDGE_SAMPLE_RATE  # no pipeline here, so no StartFrame to set it
    return _wav(b"".join([chunk async for chunk in tts._pcm_chunks(text)]), EDGE_SAMPLE_RATE)


def _wav(pcm: bytes, rate: int) -> bytes:
    """Wrap raw 16-bit mono samples in a WAV container — what the STT endpoint accepts."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def transcribe(wav: bytes) -> tuple[str, float]:
    """POST the WAV to OpenRouter's Whisper endpoint. Returns (transcript, seconds)."""
    boundary = "----bench"
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
        f"{config.STT_MODEL}\r\n".encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nvi\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n".encode(), wav, f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        f"{config.OPENROUTER_BASE}/audio/transcriptions", body,
        {"Authorization": f"Bearer {config.OPENROUTER_KEY}",
         "Content-Type": f"multipart/form-data; boundary={boundary}"})
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=120) as r:
        text = json.load(r).get("text", "")
    return text.strip(), time.monotonic() - t


def llm_stream(messages: list[dict]) -> tuple[dict, float, float]:
    """Stream one completion. Returns (assistant message, seconds to first token, total)."""
    payload = {"model": config.LLM_MODEL, "messages": messages, "tools": TOOL_SPECS,
               "stream": True}
    req = urllib.request.Request(
        f"{config.OPENROUTER_BASE}/chat/completions", json.dumps(payload).encode(),
        {"Authorization": f"Bearer {config.OPENROUTER_KEY}", "Content-Type": "application/json"})
    t = time.monotonic()
    ttft = None
    content, calls = "", {}
    with urllib.request.urlopen(req, timeout=120) as r:
        for line in r:
            if not line.startswith(b"data: ") or line[6:].strip() == b"[DONE]":
                continue
            delta = json.loads(line[6:]).get("choices", [{}])[0].get("delta", {})
            if delta.get("content"):
                ttft = ttft or time.monotonic() - t
                content += delta["content"]
            for tc in delta.get("tool_calls") or []:
                ttft = ttft or time.monotonic() - t
                slot = calls.setdefault(tc["index"], {"id": "", "name": "", "args": ""})
                slot["id"] += tc.get("id") or ""
                slot["name"] += (tc.get("function") or {}).get("name") or ""
                slot["args"] += (tc.get("function") or {}).get("arguments") or ""
    msg = {"role": "assistant", "content": content or None}
    if calls:
        msg["tool_calls"] = [
            {"id": c["id"], "type": "function",
             "function": {"name": c["name"], "arguments": c["args"]}}
            for c in calls.values()]
    return msg, (ttft or time.monotonic() - t), time.monotonic() - t


async def tts_ttfb(text: str) -> float:
    """Seconds until the first decoded audio sample of `text` is available."""
    if not text.strip():  # Edge answers empty input with NoAudioReceived, which reads as a bug
        return float("nan")
    tts = tts_engine.build()
    tts._sample_rate = tts.sample_rate or EDGE_SAMPLE_RATE
    t = time.monotonic()
    try:
        async for frame in tts.run_tts(text, "bench"):
            if isinstance(frame, ErrorFrame):
                break
            if isinstance(frame, TTSAudioRawFrame):
                return time.monotonic() - t
    except Exception as e:
        print(f"  ! TTS failed on {text!r}: {type(e).__name__}", flush=True)
    return float("nan")


async def one_turn(utterance: str, wav: bytes) -> dict:
    """Run a full turn and time each leg the way the live pipeline would."""
    transcript, t_stt = transcribe(wav)
    messages = [{"role": "system", "content": config.SYSTEM_PROMPT.format(
        state=__import__("voice_agent.tools.vehicle", fromlist=["x"]).describe_state())},
        {"role": "user", "content": transcript}]

    msg, ttft, t_llm = llm_stream(messages)
    tools_used, t_llm2, spoken = [], 0.0, None
    if msg.get("tool_calls"):
        messages.append(msg)
        for call in msg["tool_calls"]:
            args = json.loads(call["function"]["arguments"] or "{}")
            result = dispatch(call["function"]["name"], args)
            tools_used.append(call["function"]["name"])
            spoken = spoken or result.get("speech")
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result, ensure_ascii=False)})
        if not spoken:  # mirrors app.py: only tools without a ready sentence re-run the LLM
            msg, ttft2, t_llm2 = llm_stream(messages)
            ttft += t_llm + ttft2  # the first call must finish before the tool can even run

    reply = spoken or (msg.get("content") or "").strip()
    # The live pipeline hands TTS the first sentence as soon as it is complete, not the
    # whole reply — so that is what gets timed here.
    first_sentence = reply.split(".")[0].strip() or reply
    t_tts = await tts_ttfb(first_sentence)
    return {"said": utterance, "heard": transcript, "reply": reply, "tools": tools_used,
            "accuracy": word_accuracy(utterance, transcript),
            "stt": t_stt, "llm": ttft, "tts": t_tts, "total": t_stt + ttft + t_tts,
            "llm_full": t_llm + t_llm2}


REPLIES = [  # what the agent actually says, not what the driver says
    "Đã giảm còn hai mươi hai độ",
    "Bạn muốn mở cửa sổ ghế lái hay ghế phụ ạ",
    "Áp suất lốp tiêu chuẩn ghi trên nhãn dán ở khung cửa phía người lái",
]


async def compare_voices() -> int:
    """Rank TTS voices by how well STT reads them back.

    Naturalness needs ears, but intelligibility does not, and intelligibility is what
    actually matters in a car with road noise. Each voice speaks a known sentence, the
    sentence goes through the same STT, and the score is how much survived.
    """
    engines = [("piper", v) for v in ("vi_VN-vais1000-medium", "vi_VN-25hours_single-low")]
    engines.append(("edge", config.EDGE_VOICE))
    for engine, voice in engines:
        config.TTS_ENGINE, config.PIPER_VOICE, config.EDGE_VOICE = engine, voice, voice
        scores = []
        for text in REPLIES:
            tts = tts_engine.build()
            tts._sample_rate = tts.sample_rate or EDGE_SAMPLE_RATE
            pcm = b"".join([f.audio async for f in tts.run_tts(text, "voices")
                            if isinstance(f, TTSAudioRawFrame)])
            heard, _ = transcribe(_wav(pcm, tts._sample_rate))
            scores.append(word_accuracy(text, heard))
            print(f"  {engine}/{voice:26} {scores[-1]:5.0%}  {heard}", flush=True)
        print(f"  {engine}/{voice:26} {statistics.mean(scores):5.0%}  ← mean\n")
    return 0


async def main(repeat: int) -> int:
    if not config.OPENROUTER_KEY:
        sys.exit("Missing OPENROUTER_API_KEY — see .env.example")
    voice = config.PIPER_VOICE if config.TTS_ENGINE == "piper" else config.EDGE_VOICE
    print(f"STT={config.STT_MODEL}\nLLM={config.LLM_MODEL}\n"
          f"TTS={config.TTS_ENGINE}/{voice}\n")

    wavs = {u: await synth(u) for u in UTTERANCES}
    rows = [await one_turn(u, wavs[u]) for _ in range(repeat) for u in UTTERANCES]

    for r in rows[: len(UTTERANCES)]:
        print(f"  said  {r['said']}\n  heard {r['heard']}  ({r['accuracy']:.0%} words)")
        print(f"  tools {r['tools'] or '—'}\n  reply {r['reply']}\n")

    print(f"{'':22}{'p50':>8}{'min':>8}{'max':>8}   (n={len(rows)})")
    for leg in ("stt", "llm", "tts", "total"):
        # A failed leg is NaN. Dropping it silently would flatter the numbers, so say so.
        v = sorted(r[leg] for r in rows if r[leg] == r[leg])
        label = {"llm": "llm (to 1st token)", "total": "TOTAL"}.get(leg, leg)
        missed = f"  [{len(rows) - len(v)} failed]" if len(v) < len(rows) else ""
        print(f"  {label:20}{statistics.median(v) * 1000:7.0f}ms{v[0] * 1000:7.0f}ms"
              f"{v[-1] * 1000:7.0f}ms{missed}" if v else f"  {label:20}   all failed")
    acc = statistics.mean(r["accuracy"] for r in rows)
    print(f"\n  STT word accuracy {acc:.0%}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repeat", type=int, default=1, help="passes over the utterance set")
    p.add_argument("--voices", action="store_true",
                   help="rank TTS voices by STT-measured intelligibility instead")
    args = p.parse_args()
    sys.exit(asyncio.run(compare_voices() if args.voices else main(args.repeat)))
