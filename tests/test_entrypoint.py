"""The entrypoint must actually import.

No other test imports `voice_agent.app`, so the heavy import chain (Pipecat → nltk)
was never exercised. `python -m voice_agent` once died at import time while all
47 other tests stayed green.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_runs_via_python_m():
    """`python -m voice_agent` must reach the missing-key message, not die importing.

    Run as a subprocess with cwd at the repo root, because that is the only situation
    that reproduces the failure: the venv lives inside the repo, so nltk's hook treats
    site-packages as "inside cwd" and blocks it. An in-process import cannot show this.
    """
    env = {**os.environ, "OPENROUTER_API_KEY": "", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-m", "voice_agent"],
                       cwd=ROOT, capture_output=True, text=True, timeout=180,
                       encoding="utf-8", errors="replace", env=env)
    out = (r.stdout or "") + (r.stderr or "")
    assert "ImportError" not in out and "Traceback" not in out, out[-1500:]
    assert "OPENROUTER_API_KEY" in out, f"expected the missing-key exit, got: {out[-500:]}"
