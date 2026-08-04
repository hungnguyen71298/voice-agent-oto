"""Knowledge base: the vehicle owner's manual, retrieved with BM25.

The index is built at module import (~250ms for 850 chunks) and lives for the
lifetime of the process. Source data is `data/kb/*.md`, fetched by `scripts/fetch_kb.py`.
"""
import re
from itertools import pairwise

from rank_bm25 import BM25Okapi

from ..config import KB_DIR, KB_TOP_K, MIN_CHUNK_CHARS


def _chunks(text: str):
    """Split on blank lines, prefixing each chunk with its nearest heading.

    Without the heading a chunk loses its context: the passage about the rear
    defroster contains no occurrence of "sấy kính", so no query can match it.
    Short fragments are dropped — bare headings and image captions win BM25 by
    being short while containing no answer.
    """
    head = ""
    for c in (x.strip() for x in text.split("\n\n")):
        if c.startswith("#"):
            head = c.lstrip("# ").strip()
        elif len(c) > MIN_CHUNK_CHARS:
            yield f"{head}\n{c}" if head else c


def _tok(s: str) -> list[str]:
    """Syllables plus bigrams.

    Vietnamese splits into syllables, and single syllables like "áp", "suất", "lốp"
    are far too common to discriminate; the bigram "áp_suất" is what carries the
    meaning of the compound word.
    ponytail: a one-line approximation of word segmentation, instead of underthesea/pyvi.
    """
    w = re.findall(r"\w+", s.lower())
    return w + [f"{a}_{b}" for a, b in pairwise(w)]


DOCS = [(p.name, c) for p in sorted(KB_DIR.glob("*.md"))
        for c in _chunks(p.read_text(encoding="utf-8"))]
_bm25 = BM25Okapi([_tok(t) for _, t in DOCS]) if DOCS else None


def search_manual(query: str) -> dict:
    """Tra cứu sổ tay hướng dẫn sử dụng xe: tính năng, đèn cảnh báo, xử lý sự cố, bảo hành.

    Args:
        query: Câu hỏi hoặc từ khóa cần tra cứu trong sổ tay xe.
    """
    if _bm25 is None:
        return {"results": [], "message": "Knowledge base rỗng, chạy scripts/fetch_kb.py"}
    # ponytail: plain BM25. Its ceiling is vocabulary mismatch — asking about "chìa
    # khóa thông minh hết pin" does not match the passage worded "pin chìa khóa điều
    # khiển từ xa hết điện", even though that is the right content. Upgrade path:
    # take BM25 top-20 and rerank with baai/bge-m3 ($0.01/1M, +~150ms, KB branch only).
    #
    # strict=True: scores and DOCS must be the same length. A mismatch means the index
    # was built from a different document set — better to blow up than to silently
    # truncate and return text from the wrong chunk.
    scores = _bm25.get_scores(_tok(query))
    ranked = sorted(zip(scores, DOCS, strict=True), key=lambda x: -x[0])[:KB_TOP_K]
    return {"results": [{"source": src, "text": txt} for score, (src, txt) in ranked if score > 0]}


TOOLS = [search_manual]
