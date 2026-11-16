"""Citekey generation.
Format: <Type><first-4 authors' last names><yyyymmdd>, each part folded via
sanitize.cite_word so it is a safe file name; guarded against empty/reserved.
"""
import sanitize

_RESERVED = (
    {"CON", "PRN", "AUX", "NUL"}
    | {"COM%d" % i for i in range(1, 10)}
    | {"LPT%d" % i for i in range(1, 10)}
)


def build(item_type, authors, yyyymmdd):
    """authors: [(last, first), ...]."""
    out = sanitize.cite_word(item_type)
    for last, _first in authors[:4]:
        out += sanitize.cite_word(last)
    out += yyyymmdd
    if not out:
        return "entry"
    if out.upper() in _RESERVED:
        out += "_"
    return out


def clean(raw):
    """Fold a hand-typed citekey (`hib update -ctk`) exactly as build folds its
    parts, so it stays a safe file name -- the metadata is stored as
    '<citekey>.json'. Returns "" when nothing usable is left, which the caller
    reports rather than silently inventing a key."""
    out = sanitize.cite_word(raw)
    if not out:
        return ""
    if out.upper() in _RESERVED:
        out += "_"
    return out
