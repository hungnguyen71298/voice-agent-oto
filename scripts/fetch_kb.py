"""Fetch a VinFast owner's manual (Vietnamese) into data/kb/.

    python scripts/fetch_kb.py            # defaults to VF8 2026
    python scripts/fetch_kb.py VF9 2026

Source: https://om.vinfastauto.com (VinFast's public documentation).
The API returns a chapter tree where each node holds HTML; it is converted to text
and written out as one .md file per top-level chapter.
"""
import json
import pathlib
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from html.parser import HTMLParser

API = "https://omapi.vinfastauto.com/fe/v1/menu"
KB = pathlib.Path(__file__).resolve().parent.parent / "data" / "kb"
BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "table"}


class ToText(HTMLParser):
    """HTML to text using the stdlib parser, rather than pulling in bs4/lxml."""

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def to_text(raw: str) -> str:
    p = ToText()
    p.feed(raw)
    t = unicodedata.normalize("NFC", "".join(p.out)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n[ \t]*(\n[ \t]*)+", "\n\n", t).strip()


def slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")


def sections(nodes, trail=()):
    """Walk the tree, yielding (chapter path, text) for every node that has content."""
    for n in nodes:
        path = (*trail, n["name"])
        body = to_text(n.get("html_web") or n.get("html") or "")
        if len(body) > 200:  # skip nodes that are only a title
            yield path, body
        yield from sections(n.get("childs") or [], path)


def main(model="VF8", version="2026"):
    q = urllib.parse.urlencode({"carModel": model, "version": version,
                                "lang": "vi", "country": "vn"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    if not data.get("success"):
        sys.exit(f"API error: {data.get('message')}")

    KB.mkdir(exist_ok=True)
    chapters, total = {}, 0
    for path, body in sections(data["data"]):
        # ponytail: group by top-level chapter — ~12 files, small enough to eyeball and diff.
        heading = "#" * min(len(path) + 1, 4) + " " + " › ".join(path[1:] or path)
        chapters.setdefault(path[0], []).append((heading, body))

    for chapter, parts in chapters.items():
        out = KB / f"{model.lower()}-{version}-{slug(chapter)}.md"
        text = (f"# {chapter}\n\nNguồn: sổ tay {model} {version}, om.vinfastauto.com\n\n"
                + "\n\n".join(f"{h}\n\n{b}" for h, b in parts))
        out.write_text(text, encoding="utf-8")
        total += len(text)
        print(f"  {out.name:52} {len(parts):3} sections  {len(text):>7} chars")
    print(f"\n{len(chapters)} chapters, {total} chars -> {KB}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
