"""Tiptap → HTML rendering contract.

Covers the node and mark types we expect from the editor's toolbar.
Anything outside this surface is dropped (safer default than emitting
unknown HTML).
"""

from core.cms.rendering import render_tiptap


def _doc(*children):
    return {"type": "doc", "content": list(children)}


def _text(text, *marks):
    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def test_paragraphs_and_text():
    doc = _doc(
        {"type": "paragraph", "content": [_text("Hello ", {"type": "bold"}), _text("world")]}
    )
    html = render_tiptap(doc)
    assert html == "<p><strong>Hello </strong>world</p>"


def test_headings_are_clamped():
    doc = _doc({"type": "heading", "attrs": {"level": 8}, "content": [_text("Hi")]})
    html = render_tiptap(doc)
    assert html == "<h2>Hi</h2>"


def test_links_escape_and_drop_dangerous_schemes():
    safe = _doc(
        {
            "type": "paragraph",
            "content": [
                _text(
                    "Click",
                    {"type": "link", "attrs": {"href": "https://example.com"}},
                )
            ],
        }
    )
    html = render_tiptap(safe)
    assert html == '<p><a href="https://example.com">Click</a></p>'

    dangerous = _doc(
        {
            "type": "paragraph",
            "content": [
                _text(
                    "evil",
                    {"type": "link", "attrs": {"href": "javascript:alert(1)"}},
                )
            ],
        }
    )
    html = render_tiptap(dangerous)
    assert "javascript" not in html


def test_image_required_src():
    doc = _doc(
        {"type": "image", "attrs": {"src": "https://cdn.example.com/x.png", "alt": "x"}}
    )
    html = render_tiptap(doc)
    assert html == '<img src="https://cdn.example.com/x.png" alt="x"/>'


def test_image_with_dangerous_scheme_is_dropped():
    doc = _doc(
        {"type": "image", "attrs": {"src": "javascript:alert(1)"}}
    )
    html = render_tiptap(doc)
    assert html == ""


def test_text_is_escaped():
    doc = _doc({"type": "paragraph", "content": [_text("<script>oops")]})
    html = render_tiptap(doc)
    assert "<script>" not in html
    assert "&lt;script&gt;oops" in html


def test_lists_and_quotes():
    doc = _doc(
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [_text("one")]},
                    ],
                },
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [_text("two")]},
                    ],
                },
            ],
        }
    )
    html = render_tiptap(doc)
    assert html == "<ul><li><p>one</p></li><li><p>two</p></li></ul>"


def test_code_block():
    doc = _doc(
        {
            "type": "codeBlock",
            "attrs": {"language": "python"},
            "content": [_text("print('hi')")],
        }
    )
    html = render_tiptap(doc)
    # Note: html.escape() quotes apostrophes — safer for attribute contexts.
    assert html == '<pre><code class="language-python">print(&#x27;hi&#x27;)</code></pre>'


def test_unknown_node_drops_to_children():
    doc = _doc(
        {
            "type": "futureFeature",
            "content": [{"type": "paragraph", "content": [_text("kept")]}],
        }
    )
    html = render_tiptap(doc)
    assert html == "<p>kept</p>"
