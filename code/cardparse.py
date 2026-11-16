"""Recover an entry's metadata from its rendered HTML card -- the inverse of
html.render_entry, used by `hib update -json` to sync a hand-edited card back into
its JSON.

Best-effort by design: each field is matched by its labelled markup, so editing a
VALUE in the card is picked up while the surrounding structure is intact. A field
whose markup is missing is simply absent from the result, so the caller keeps the
stored value rather than wiping it. Authors are the one lossy field: the card shows
"First Last", so the reverse (last word = last name, the rest = first name) cannot
recover a multi-word last name -- use `hib update <ctk>` for precise author edits.
"""
import re

# Single-line "<strong>Label:</strong> value</p>" fields. The value is whatever the
# user left between the label and the closing </p>.
_LABELLED = {
    "item_type": r"<strong>Type:</strong> (.*?)</p>",
    "reference": r"<strong>Reference:</strong> (.*?)</p>",
    "version": r"<strong>Version:</strong> (.*?)</p>",
    "short_title": r"<strong>Short Title:</strong> (.*?)</p>",
    "date": r"<strong>Date:</strong> (.*?)</p>",
}

# Since the Copy Reference button was added, the reference sits in its own span
# and the plain _LABELLED pattern would swallow the button markup with it. Read
# the span when it is there; the pattern above still covers cards written before
# the button, and those written by older versions of hib.
_REFERENCE_SPAN = r'id="referenceValue">(.*?)</span>'


def _unescape(s):
    """Reverse html._esc. &amp; is decoded LAST so an escaped entity in the source
    (e.g. text '&lt;' -> '&amp;lt;') round-trips correctly."""
    return (s.replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&amp;", "&"))


def parse_authors_display(s):
    """'First Last, ...' (the card's author rendering) -> [(last, first), ...].
    Each comma-separated item splits on its LAST space: last word = last name, the
    rest = first name; a single word is taken as the last name (matching a stored
    author that had no first name)."""
    out = []
    for raw in s.split(","):
        item = _unescape(raw.strip(" \t\r\n"))
        if not item:
            continue
        head, sep, tail = item.rpartition(" ")
        if sep and head:
            out.append((tail, head))      # (last, first)
        else:
            out.append((item, ""))        # single token -> last name only
    return out


def parse_card(html):
    """Extract the editable fields present in `html`. Returns a dict; a key is
    absent when its markup was not found (so the caller keeps the stored value),
    EXCEPT `tags` and `remote_path` which are always set (an empty tag list / a
    missing Remote section are meaningful 'now none' states)."""
    fields = {}

    m = re.search(r"<h2>(.*?)</h2>", html, re.DOTALL)
    if m:
        fields["title"] = _unescape(m.group(1))

    for key, pat in _LABELLED.items():
        m = re.search(pat, html)
        if m:
            fields[key] = _unescape(m.group(1))

    m = re.search(_REFERENCE_SPAN, html, re.DOTALL)
    if m:
        fields["reference"] = _unescape(m.group(1))

    m = re.search(r'<div class="desc">(.*?)</div>', html, re.DOTALL)
    if m:
        fields["description"] = _unescape(m.group(1))

    m = re.search(r"<strong>Authors:</strong> (.*?)</p>", html, re.DOTALL)
    if m:
        fields["authors"] = parse_authors_display(m.group(1))

    fields["tags"] = [_unescape(t) for t in
                      re.findall(r'<span class="tag">(.*?)</span>', html, re.DOTALL)]

    m = re.search(r'id="remotePath">(.*?)</div>', html, re.DOTALL)
    fields["remote_path"] = _unescape(m.group(1)) if m else None

    return fields
