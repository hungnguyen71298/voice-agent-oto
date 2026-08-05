"""In-car voice agent — device control, owner's-manual lookup and web search by voice."""
import os

# nltk 3.10.1 blocks any import it initiates that resolves inside the current working
# directory (CWE-427 hardening). `.venv/` lives inside the project, so every one of its
# own dependencies — regex, defusedxml, ... — reads as "inside cwd" and pipecat's
# `import nltk` dies. This must be set before pipecat imports nltk, hence here.
# The protection we give up is narrow: it only ever covered nltk-initiated imports, and
# running `python -m voice_agent` already executes this repo's code either way.
# Drop this line if the venv is moved outside the project directory.
os.environ.setdefault("NLTK_DISABLE_IMPORT_SECURITY", "1")

__version__ = "0.1.0"
