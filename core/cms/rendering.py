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
_ALLOWED_TEXT_ALIGN = {"left", "center", "right", "justify"}
_ALLOWED_EMBED_HOSTS = {
    "youtube": {"www.youtube.com", "youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"},
    "vimeo": {"player.vimeo.com"},
}


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
        style = _style_from_attrs(node.get("attrs") or {})
        return f"<p{style}>{inner}</p>"

    if type_ == "heading":
        level = node.get("attrs", {}).get("level", 2)
        if level not in _ALLOWED_HEADING_LEVELS:
            level = 2
        inner = "".join(_render_inline(node.get("content") or []))
        style = _style_from_attrs(node.get("attrs") or {})
        return f"<h{level}{style}>{inner}</h{level}>"

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
        width = _safe_dimension(attrs.get("width"))
        height = _safe_dimension(attrs.get("height"))
        width_attr = f' width="{width}"' if width else ""
        height_attr = f' height="{height}"' if height else ""
        caption = attrs.get("caption")
        img_tag = (
            f'<img src="{src}" alt="{alt}"{title_attr}{width_attr}{height_attr}/>'
        )
        if caption:
            return (
                f'<figure class="cms-figure">{img_tag}'
                f"<figcaption>{escape(caption)}</figcaption></figure>"
            )
        return img_tag

    if type_ == "video":
        return _render_video(node.get("attrs") or {})

    if type_ == "youtube":
        # Tiptap's @tiptap/extension-youtube emits node type "youtube" with `src`
        attrs = node.get("attrs") or {}
        return _render_video({**attrs, "provider": "youtube"})

    if type_ == "table":
        rows = "".join(_render_nodes(node.get("content") or []))
        return f'<div class="cms-table-wrap"><table>{rows}</table></div>'

    if type_ == "tableRow":
        cells = "".join(_render_nodes(node.get("content") or []))
        return f"<tr>{cells}</tr>"

    if type_ in ("tableCell", "tableHeader"):
        attrs = node.get("attrs") or {}
        tag = "th" if type_ == "tableHeader" else "td"
        colspan = _safe_dimension(attrs.get("colspan"))
        rowspan = _safe_dimension(attrs.get("rowspan"))
        colspan_attr = f' colspan="{colspan}"' if colspan and colspan > 1 else ""
        rowspan_attr = f' rowspan="{rowspan}"' if rowspan and rowspan > 1 else ""
        inner = "".join(_render_nodes(node.get("content") or []))
        return f"<{tag}{colspan_attr}{rowspan_attr}>{inner}</{tag}>"

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
    if mtype == "underline":
        return f"<u>{text}</u>"
    if mtype == "code":
        return f"<code>{text}</code>"
    if mtype == "strike":
        return f"<s>{text}</s>"
    if mtype == "highlight":
        color = _safe_color((mark.get("attrs") or {}).get("color", ""))
        style = f' style="background-color:{color}"' if color else ""
        return f"<mark{style}>{text}</mark>"
    if mtype == "textStyle":
        color = _safe_color((mark.get("attrs") or {}).get("color", ""))
        if not color:
            return text
        return f'<span style="color:{color}">{text}</span>'
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


def _safe_dimension(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n <= 0 or n > 4000:
        return None
    return n


def _safe_color(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate:
        return ""
    if candidate.startswith("#") and len(candidate) in (4, 7, 9):
        body = candidate[1:]
        if all(c in "0123456789abcdefABCDEF" for c in body):
            return escape(candidate, quote=True)
    if candidate.startswith("rgb(") or candidate.startswith("rgba("):
        if all(c.isdigit() or c in " ,.()%rgba" for c in candidate):
            return escape(candidate, quote=True)
    return ""


def _style_from_attrs(attrs: dict) -> str:
    parts: list[str] = []
    align = attrs.get("textAlign")
    if isinstance(align, str) and align in _ALLOWED_TEXT_ALIGN and align != "left":
        parts.append(f"text-align:{align}")
    if not parts:
        return ""
    return f' style="{";".join(parts)}"'


def _render_video(attrs: dict) -> str:
    src_raw = attrs.get("src", "")
    src = _safe_url(src_raw)
    if not src:
        return ""
    provider = (attrs.get("provider") or "").lower()
    caption = attrs.get("caption") or ""
    width = _safe_dimension(attrs.get("width"))
    height = _safe_dimension(attrs.get("height"))

    if provider in ("youtube", "vimeo"):
        try:
            host = urlparse(src_raw).hostname or ""
        except Exception:
            host = ""
        if host.lower() not in _ALLOWED_EMBED_HOSTS.get(provider, set()):
            return ""
        w = width or 640
        h = height or 360
        iframe = (
            f'<iframe src="{src}" width="{w}" height="{h}" '
            'frameborder="0" allow="accelerometer; autoplay; clipboard-write; '
            'encrypted-media; gyroscope; picture-in-picture" '
            'allowfullscreen loading="lazy"></iframe>'
        )
        body = iframe
    else:
        width_attr = f' width="{width}"' if width else ""
        height_attr = f' height="{height}"' if height else ""
        body = (
            f'<video src="{src}" controls preload="metadata"'
            f"{width_attr}{height_attr}></video>"
        )

    if caption:
        return (
            f'<figure class="cms-figure cms-video">{body}'
            f"<figcaption>{escape(caption)}</figcaption></figure>"
        )
    return f'<figure class="cms-figure cms-video">{body}</figure>'
