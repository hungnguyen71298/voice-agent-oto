"""Internet search. Falls back to mock results without TAVILY_API_KEY (allowed by the brief)."""
import json
import urllib.error
import urllib.request

from ..config import TAVILY_KEY

TAVILY = "https://api.tavily.com/search"


def search_internet(query: str) -> dict:
    """Tìm thông tin thời sự trên Internet: thời tiết, giá cả, tin tức, địa điểm, kiến thức chung.

    Args:
        query: Nội dung cần tìm kiếm.
    """
    if not TAVILY_KEY:
        # ponytail: mock, permitted by the brief. Supplying a key switches this to the
        # real call with no code change.
        return {"mock": True, "results": [
            {"title": f"Kết quả cho '{query}'", "url": "https://example.com",
             "snippet": "(mock) chưa gắn search API — set TAVILY_API_KEY để dùng thật"}]}

    body = json.dumps({"api_key": TAVILY_KEY, "query": query, "max_results": 3,
                       "include_answer": True}).encode()
    req = urllib.request.Request(TAVILY, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        # Never raise: the agent must be able to say "I couldn't look that up"
        # rather than kill the pipeline.
        return {"results": [], "message": f"Tìm kiếm lỗi: {e}"}

    return {"answer": d.get("answer"),
            "results": [{"title": x.get("title"), "url": x.get("url"),
                         "snippet": (x.get("content") or "")[:400]} for x in d.get("results", [])]}


TOOLS = [search_internet]
