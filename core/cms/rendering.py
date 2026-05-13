"""Render Tiptap doc JSON to safe HTML.

Tiptap's "doc" format is a tree of typed nodes (paragraph, heading,
bulletList, listItem, blockquote, codeBlock, image, hardBreak) with
inline marks (bold, italic, code, link). This walker emits HTML that
mirrors Tiptap's own output, escaping every text node and attribute so
admin-authored content can't inject scripts.

Kept dependency-free on purpose — if we ever need plugin parity with
Tiptap's React renderer we can swap to `tiptap-html` (Node) via a
subprocess or rewrite this in TS, but for our content (text + images +
links + lists) the surface stays small.
"""

from __future__ import annotations

from html import escape
from typing import Any, Iterable
from urllib.parse import urlparse


_ALLOWED_HEADING_LEVELS = {1, 2, 3, 4, 5, 6}
_ALLOWED_LINK_SCHEMES = {"http", "https", "mailto"}


def render_tiptap(doc: Any) -> str:
    if not isinstance(doc, dict):
        return ""
    content = doc.get("content") or []
    if not isinstance(content, list):
        return ""
    return "".join(_render_nodes(content))


def _render_nodes(nodes: Iterable[Any]) -> list[str]:
    parts: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        parts.append(_render_node(node))
    return parts


def _render_node(node: dict) -> str:
    type_ = node.get("type")

    if type_ == "doc":
        return "".join(_render_nodes(node.get("content") or []))

    if type_ == "paragraph":
        inner = "".join(_render_inline(node.get("content") or []))
        return f"<p>{inner}</p>"

    if type_ == "heading":
        level = node.get("attrs", {}).get("level", 2)
        if level not in _ALLOWED_HEADING_LEVELS:
            level = 2
        inner = "".join(_render_inline(node.get("content") or []))
        return f"<h{level}>{inner}</h{level}>"

    if type_ == "bulletList":
        items = "".join(_render_nodes(node.get("content") or []))
        return f"<ul>{items}</ul>"

    if type_ == "orderedList":
        items = "".join(_render_nodes(node.get("content") or []))
        return f"<ol>{items}</ol>"

    if type_ == "listItem":
        inner = "".join(_render_nodes(node.get("content") or []))
        return f"<li>{inner}</li>"

    if type_ == "blockquote":
        inner = "".join(_render_nodes(node.get("content") or []))
        return f"<blockquote>{inner}</blockquote>"

    if type_ == "codeBlock":
        text = "".join(
            child.get("text", "")
            for child in node.get("content") or []
            if isinstance(child, dict) and child.get("type") == "text"
        )
        language = node.get("attrs", {}).get("language") or ""
        cls = f' class="language-{escape(language)}"' if language else ""
        return f"<pre><code{cls}>{escape(text)}</code></pre>"

    if type_ == "horizontalRule":
        return "<hr/>"

    if type_ == "image":
        attrs = node.get("attrs", {}) or {}
        src = _safe_url(attrs.get("src", ""))
        if not src:
            return ""
        alt = escape(attrs.get("alt", "") or "")
        title = attrs.get("title")
        title_attr = f' title="{escape(title)}"' if title else ""
        return f'<img src="{src}" alt="{alt}"{title_attr}/>'

    if type_ == "hardBreak":
        return "<br/>"

    if type_ == "text":
        return _render_inline([node])[0] if node else ""

    # Unknown node type: render children if any, else drop.
    inner = "".join(_render_nodes(node.get("content") or []))
    return inner


def _render_inline(nodes: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "hardBreak":
            out.append("<br/>")
            continue
        if node.get("type") != "text":
            out.append(_render_node(node))
            continue
        text = escape(node.get("text", "") or "")
        for mark in node.get("marks") or []:
            text = _apply_mark(mark, text)
        out.append(text)
    return out


def _apply_mark(mark: dict, text: str) -> str:
    mtype = mark.get("type")
    if mtype == "bold":
        return f"<strong>{text}</strong>"
    if mtype == "italic":
        return f"<em>{text}</em>"
    if mtype == "code":
        return f"<code>{text}</code>"
    if mtype == "strike":
        return f"<s>{text}</s>"
    if mtype == "link":
        href = _safe_url((mark.get("attrs") or {}).get("href", ""))
        if not href:
            return text
        target = (mark.get("attrs") or {}).get("target")
        rel = ' rel="noopener noreferrer"' if target == "_blank" else ""
        target_attr = f' target="{escape(target)}"' if target else ""
        return f'<a href="{href}"{target_attr}{rel}>{text}</a>'
    return text


def _safe_url(value: str) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme and parsed.scheme.lower() not in _ALLOWED_LINK_SCHEMES:
        return ""
    return escape(candidate, quote=True)
