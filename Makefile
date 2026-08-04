.PHONY: install lint test check run kb clean
PY ?= .venv/bin/python

install:            ## create venv and install dependencies
	python3 -m venv .venv && $(PY) -m pip install -qU pip && $(PY) -m pip install -q -r requirements-dev.txt

lint:               ## lint with ruff
	$(PY) -m ruff check .

test:               ## run the whole suite, no API key needed
	$(PY) -m pytest

check: lint test    ## gate before committing

run:                ## run the voice agent (needs OPENROUTER_API_KEY in .env)
	$(PY) -m voice_agent

kb:                 ## rebuild the knowledge base from the VinFast manual
	$(PY) scripts/fetch_kb.py VF8 2026

clean:
	rm -rf __pycache__ */__pycache__ */*/__pycache__ .pytest_cache
