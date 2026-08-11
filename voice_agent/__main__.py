"""Entrypoint: `python -m voice_agent`."""
import asyncio
import contextlib
import os
import sys
from pathlib import Path

from loguru import logger

# Must run BEFORE importing app: the Windows console defaults to cp1252 and printing
# Vietnamese crashes it.
sys.stdout.reconfigure(encoding="utf-8")

# nltk (pulled in by Pipecat) installs a meta-path hook that blocks any module located
# under the current working directory, to mitigate module hijacking (CWE-427). The hook
# misfires when the venv lives inside the repo: `.venv/Lib/site-packages/regex` is under
# cwd, so nltk blocks its own dependency and `python -m voice_agent` dies at import time.
# The `-P` flag does not help, because the hook inspects file location rather than sys.path.
#
# Rather than just switching it off, do the thing the hook was approximating: drop cwd
# from sys.path (that is the real CWE-427 mitigation), then disable the misfiring hook.
# The voice_agent package is already loaded here, so submodules still resolve via __path__.
_cwd = str(Path.cwd())
sys.path[:] = [p for p in sys.path if p not in ("", ".", _cwd)]
os.environ["NLTK_DISABLE_IMPORT_SECURITY"] = "1"

# Pipecat logs through loguru, whose default sink is stderr at DEBUG — that prints every
# frame link and every per-service metric. INFO keeps the dashboard URL and the turns.
logger.remove()
logger.add(sys.stderr, level=os.environ.get("LOG_LEVEL", "INFO"))

from .app import run  # noqa: E402

if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())
