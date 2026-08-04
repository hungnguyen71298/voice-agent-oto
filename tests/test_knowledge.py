"""BM25 knowledge base over the real VinFast VF 8 owner's manual."""
import copy

import pytest

from voice_agent.tools import knowledge
from voice_agent.tools.knowledge import DOCS, _chunks, _tok, search_manual


def test_kb_is_loaded():
    assert len(DOCS) > 300, f"only {len(DOCS)} chunks — run scripts/fetch_kb.py"


def test_chunk_carries_its_heading():
    """The defroster passage contains no "sấy kính" — the heading is what saves the query."""
    src = "# Điều hòa\n\n" + "x" * 200
    assert next(_chunks(src)).startswith("Điều hòa\n")


def test_short_fragments_are_dropped():
    """Bare headings and captions win BM25 by being short while holding no answer."""
    assert list(_chunks("## Bật/Tắt sấy kính\n\nngắn quá")) == []


def test_tokens_include_bigrams():
    """Single Vietnamese syllables are too common; only the bigram carries the compound."""
    assert "áp_suất" in _tok("áp suất lốp")


@pytest.mark.parametrize("query,expect", [
    ("bật sấy kính", "sấy kính"),
    ("áp suất lốp bao nhiêu", "lốp"),
    ("sạc pin", "sạc"),
])
def test_retrieves_relevant_content(query, expect):
    r = search_manual(query)["results"]
    assert r, f"nothing found for '{query}'"
    assert expect in r[0]["text"].lower()


def test_respects_top_k():
    assert len(search_manual("pin")["results"]) <= knowledge.KB_TOP_K


def test_results_carry_a_source():
    """The brief asks for reference sources to be shown in the transcript."""
    assert search_manual("sạc pin")["results"][0]["source"].endswith(".md")


def test_nonsense_query_returns_empty():
    assert search_manual("xyzzy qwerty")["results"] == []


def test_search_does_not_touch_vehicle_state():
    from voice_agent.tools.vehicle import STATE
    before = copy.deepcopy(STATE)
    search_manual("sạc pin")
    assert STATE == before
