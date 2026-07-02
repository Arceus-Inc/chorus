"""Markdown→HTML for email — content drafted in md must render wherever md can't go (gmail).

Mira drafts in markdown; inbox clients render HTML. This is a small deterministic renderer for
the email subset — headings, paragraphs, bold/italic/code, lists, links, hr — with full escaping
first (no raw content ever reaches the HTML), inline styles only (email clients strip
stylesheets), and no external dependency. The blog's client-side renderer is its sibling.
"""

from __future__ import annotations

import html
import re

_STYLE_BODY = "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1a1a1a;line-height:1.6;max-width:640px"
_STYLE_H = "margin:28px 0 12px;line-height:1.25;color:#000"
_STYLE_P = "margin:0 0 16px"
_STYLE_LIST = "margin:0 0 16px;padding-left:24px"
_STYLE_CODE = "font-family:ui-monospace,Menlo,monospace;font-size:0.9em;background:#f5f5f5;border-radius:4px;padding:1px 5px"
_STYLE_HR = "border:none;border-top:1px solid #e5e5e5;margin:28px 0"

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"\*([^*]+)\*")
_CODE = re.compile(r"`([^`]+)`")
_UL_ITEM = re.compile(r"^[-*] ")
_OL_ITEM = re.compile(r"^\d+\. ")


def render_email_html(markdown: str) -> str:
    """Render the markdown body as a self-contained, inline-styled HTML email fragment."""
    blocks = [block.strip() for block in markdown.split("\n\n") if block.strip()]
    parts = [f'<div style="{_STYLE_BODY}">']
    for block in blocks:
        parts.append(_render_block(block))
    parts.append("</div>")
    return "\n".join(parts)


def _render_block(block: str) -> str:
    if re.fullmatch(r"-{3,}", block):
        return f'<hr style="{_STYLE_HR}"/>'
    for level, prefix in ((1, "# "), (2, "## "), (3, "### ")):
        if block.startswith(prefix):
            return f'<h{level} style="{_STYLE_H}">{_inline(block[len(prefix):])}</h{level}>'
    lines = [line.strip() for line in block.split("\n") if line.strip()]
    if all(_UL_ITEM.match(line) for line in lines):
        items = "".join(f"<li>{_inline(_UL_ITEM.sub('', line))}</li>" for line in lines)
        return f'<ul style="{_STYLE_LIST}">{items}</ul>'
    if all(_OL_ITEM.match(line) for line in lines):
        items = "".join(f"<li>{_inline(_OL_ITEM.sub('', line))}</li>" for line in lines)
        return f'<ol style="{_STYLE_LIST}">{items}</ol>'
    return f'<p style="{_STYLE_P}">{_inline(" ".join(lines))}</p>'


def _inline(text: str) -> str:
    """Escape FIRST, then apply span markup — raw content can never inject HTML."""
    escaped = html.escape(text)
    escaped = _CODE.sub(rf'<code style="{_STYLE_CODE}">\1</code>', escaped)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC.sub(r"<em>\1</em>", escaped)
    return _LINK.sub(r'<a href="\2" style="color:#2F5AA8">\1</a>', escaped)


__all__ = ["render_email_html"]
