"""Split large HTML post bodies for per-chunk translation."""

from __future__ import annotations

import os
import re

# Below this length, translate title + content in one API call.
DEFAULT_CHUNK_CHARS = 12_000

_BREAK_TAGS = ("</p>", "</div>", "</section>", "</li>", "</h1>", "</h2>", "</h3>", "</h4>")


def content_chunk_threshold() -> int:
    raw = os.environ.get("CONTENT_CHUNK_CHARS", str(DEFAULT_CHUNK_CHARS))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_CHUNK_CHARS
    return max(4000, value)


def split_html_content(html: str, max_chars: int | None = None) -> list[str]:
    """Split HTML into chunks at tag boundaries; single element if already small enough."""
    if not html:
        return [""]
    limit = max_chars if max_chars is not None else content_chunk_threshold()
    if len(html) <= limit:
        return [html]

    chunks: list[str] = []
    pos = 0
    length = len(html)

    while pos < length:
        end = min(pos + limit, length)
        if end < length:
            window = html[pos:end]
            best = -1
            best_end = 0
            for tag in _BREAK_TAGS:
                idx = window.rfind(tag)
                if idx != -1:
                    close = idx + len(tag)
                    if close > best:
                        best = idx
                        best_end = close
            if best >= int(limit * 0.4):
                end = pos + best_end
            else:
                nl = window.rfind("\n\n")
                if nl >= int(limit * 0.4):
                    end = pos + nl + 2

        piece = html[pos:end]
        if piece:
            chunks.append(piece)
        pos = end

    return chunks or [html]
