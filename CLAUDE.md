# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Always use the venv interpreter — this machine has a second Python (Miniconda) first on PATH,
and running bare `python` silently picks it up and fails on missing dependencies.

```bash
.venv/Scripts/python -m pytest              # 88 tests, no API key, no mic needed
.venv/Scripts/python scripts/e2e.py         # whole pipeline, recorded speech, needs the key
.venv/Scripts/python -m ruff check .         # lint — config in pyproject.toml
.venv/Scripts/python -m voice_agent         # run the agent (needs OPENROUTER_API_KEY)
.venv/Scripts/python scripts/fetch_kb.py VF9 2026   # rebuild data/kb/
```

On Linux/macOS the paths are `.venv/bin/python` and `make check` (lint + test), `make run`, `make kb` work.

Windows: `$env:PYTHONIOENCODING="utf-8"` if the console garbles Vietnamese.
`voice_agent/__main__.py` already calls `sys.stdout.reconfigure(encoding="utf-8")`.

Models are swapped by env var, never by editing code: `STT_MODEL`, `LLM_MODEL`, `TTS_ENGINE`,
`PIPER_VOICE`, `EDGE_VOICE`, `KB_TOP_K`. STT and LLM route through one OpenRouter key; TTS
does not go through OpenRouter at all, because it serves no Vietnamese voice.

`scripts/bench.py` measures the STT → LLM → TTS chain without a microphone, synthesising the
test speech so any model combination can be compared by env var alone.

## Architecture

Cascaded voice pipeline on Pipecat with the `local` transport (no WebRTC, no server):

```
mic → SileroVAD → STT → LLM (+tool calling) → TTS → LatencyProbe → speaker
```

The boundary that matters:

- **`voice_agent/tools/`** is framework-agnostic — plain Python functions, no Pipecat import.
  Every tool is `(type hints + Google-style docstring) → dict`, and never raises:
  `dispatch()` returns an error dict instead so the LLM can self-correct next turn.
  It also rejects wrong-typed args *before* calling, because `set_ac(on="có")` does not
  raise — a truthy string would silently pass.
- **`voice_agent/schema.py:to_schema()`** is the *only* place tools meet Pipecat. It reflects
  over type hints and parses the docstring `Args:` block into a `FunctionSchema`.
- **Adding a tool = adding one function to a module in `tools/` and appending it to that
  module's `TOOLS` list.** Nothing else changes. The docstring is the LLM-facing contract:
  first line becomes the tool description, each `Args:` entry becomes a parameter description,
  so wording there changes model behaviour.

Every vehicle function validates fully *before* mutating `STATE` — an error path must not leave
a half-applied change. This was a real bug (`set_ac` turned the AC on before rejecting an
out-of-range temperature) and `tests/test_vehicle.py` guards it via `assert_no_mutation`.

Knowledge base: `data/kb/*.md` is chunked and BM25-indexed at `tools/knowledge.py` import time
(module-level `DOCS` / `_bm25`), so importing costs ~250ms and the index lives for the process.
Two Vietnamese-specific choices — chunks carry their nearest heading (`_chunks`), and tokens
include syllable bigrams (`_tok`) — because single Vietnamese syllables are all too common to
discriminate. Both are covered by tests; don't "simplify" them away.

`voice_agent/config.py:SYSTEM_PROMPT` interpolates live vehicle state via
`tools/vehicle.py:describe_state()`, so changing `STATE`'s shape means checking that function.

## Conventions

- **All code is English**: comments, docstrings, test names, identifiers, console output.
  Two deliberate exceptions, both because the text is product behaviour rather than code:
  `config.py:SYSTEM_PROMPT` (it instructs the agent to speak Vietnamese) and the `Args:`
  bodies of tool docstrings plus user-facing error strings inside tools (the LLM relays
  them to a Vietnamese-speaking driver). `README.md` and `docs/` stay Vietnamese —
  they are for the reviewer, not the compiler.
- `# ponytail:` comments mark deliberate simplifications and name their ceiling + upgrade path
  (e.g. BM25 vocabulary mismatch → rerank with `baai/bge-m3`). Respect them; don't silently
  "fix" them, and add one when you take a shortcut.
- Known mocks: `search_internet` returns fake results without `TAVILY_API_KEY`; the vehicle API
  is `STATE`. The knowledge base is **not** mocked — it is the real VinFast VF 8 owner's manual.
- Latency is the graded metric. Anything added to the path between `UserStoppedSpeakingFrame`
  and the first `TTSAudioRawFrame` needs a reason.
