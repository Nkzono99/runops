"""Build report.html from README.md, with every image embedded as a data URI.

README.md stays the single source of the text, so the two files show the same
figures and results. Needs markdown-it-py (`pip install markdown-it-py`).

Usage (from the investigation directory):
    python scripts/build_html.py           # write report.html
    python scripts/build_html.py --check   # verify report.html is current and self-contained
"""

from __future__ import annotations

import base64
import mimetypes
import re
import sys
from pathlib import Path

from markdown_it import MarkdownIt

TOPIC = Path(__file__).resolve().parents[1]
SOURCE = TOPIC / "README.md"
TARGET = TOPIC / "report.html"
IMG = re.compile(r'<img src="([^"]+)"')
STYLE = """
body { max-width: 52rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.7;
       font-family: system-ui, sans-serif; color: #222; background: #fff; }
img { max-width: 100%; height: auto; display: block; margin: 1rem auto; }
table { border-collapse: collapse; margin: 1rem 0; }
th, td { border: 1px solid #bbb; padding: 0.3rem 0.7rem; text-align: left; }
blockquote { margin: 1rem 0; padding: 0.1rem 1rem; border-left: 4px solid #bbb; color: #555; }
code { background: #f2f2f2; padding: 0 0.2rem; }
"""


def embed(match: re.Match[str]) -> str:
    src = match.group(1)
    if src.startswith("data:"):
        return match.group(0)
    path = TOPIC / src
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = base64.b64encode(path.read_bytes()).decode("ascii")  # a missing image stops here
    return f'<img src="data:{kind};base64,{data}"'


def build() -> tuple[str, int]:
    text = SOURCE.read_text(encoding="utf-8")
    body, images = IMG.subn(embed, MarkdownIt("commonmark").enable("table").render(text))
    title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), TOPIC.name)
    html = (
        '<!doctype html>\n<html>\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n{body}</body>\n</html>\n"
    )
    return html, images


def main() -> int:
    html, images = build()
    if "--check" in sys.argv[1:]:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != html:
            print(f"{TARGET.name} is missing or older than {SOURCE.name}; rebuild it")
            return 1
        print(f"{TARGET.name}: current, {images} image(s) embedded, {len(html)} bytes")
        return 0
    TARGET.write_text(html, encoding="utf-8")
    print(f"wrote {TARGET.name}: {images} image(s) embedded, {len(html)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
