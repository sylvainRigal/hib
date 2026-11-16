"""Path/entry matching helpers that the selector needs: case-insensitive normalization, partial-citekey substring, and
html-path matching (full path vs basename).
"""
import os


def _ascii_lower(s):
    # ASCII-only lowercasing (byte-wise), so path matching stays stable.
    # Python's str.lower() would also fold non-ASCII (e.g. U+212A KELVIN SIGN -> 'k',
    # 'É' -> 'é'), which we must NOT do -- it would loosen same_path/is_within and
    # weakening stored_path_is_safe's [a-z0-9/._-] tail check.
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


def normalize_path(p):
    """Lowercase (ASCII only), unify '\\'->'/', collapse repeated '/', drop one
    trailing '/'. Does NOT resolve '.'/'..'."""
    s = _ascii_lower(p.replace("\\", "/"))
    while "//" in s:
        s = s.replace("//", "/")
    if len(s) > 1 and s.endswith("/"):
        s = s[:-1]
    return s


def same_path(a, b):
    """True when `a` and `b` refer to the same file by normalized full-path
    equality."""
    return normalize_path(a) == normalize_path(b)


def contains_fold(haystack, needle):
    """Case-insensitive substring test (used for partial-citekey matches).
    An empty needle never matches."""
    if not needle:
        return False
    return needle.lower() in haystack.lower()


def _basename(p):
    return p.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def clean_source_path(s):
    """Strip a wrapping pair of straight double-quotes and a trailing '*' (the
    remote marker): an Explorer "Copy as
    path" value keeps its quotes, and a card path may carry a trailing '*'."""
    s = s.strip(" \t\r\n")
    if s.endswith("*"):
        s = s[:-1].rstrip(" \t")
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    if s.endswith("*"):
        s = s[:-1]
    return s.strip(" \t")


def html_match(stored_html, arg):
    """Match an html-path selector: 'full' when the normalized full paths are
    equal, 'base' when only the (case-insensitive) basenames match, else 'none'.
    `arg` may be a bare card name, a quoted path, or end with a '*' marker."""
    arg = clean_source_path(arg)
    if not stored_html or not arg:
        return "none"
    if normalize_path(stored_html) == normalize_path(arg):
        return "full"
    if _basename(stored_html).lower() == _basename(arg).lower():
        return "base"
    return "none"


def stored_path_is_safe(root, p):
    """True only when `p` is confined under `root` AND the portion below `root`
    uses only the sanitized alphabet ([a-z0-9/._-] after normalize lowercases).
    hib writes entries as <root>/<hex>/<sanitized name> (sanitizeFilename keeps
    only [A-Za-z0-9._-]), so every real entry passes; a hand-edited/foreign JSON
    that escapes the store or embeds shell metacharacters is rejected. This is
    the `pdf` converter guard against a tampered path."""
    nr = normalize_path(root)
    np = normalize_path(p)
    if not nr or len(np) <= len(nr):
        return False
    if not np.startswith(nr):
        return False
    if np[len(nr)] != "/":           # p must be a strict descendant of root
        return False
    for c in np[len(nr) + 1:]:
        if not (("a" <= c <= "z") or ("0" <= c <= "9") or c in "/._-"):
            return False
    return True


def is_within(root, p):
    """True when `p` is a strict descendant of `root` (normalized), rejecting any
    '.'/'..' segment. For the move/delete guards (kept for later commands)."""
    nr = normalize_path(root)
    np = normalize_path(p)
    if not nr or len(np) <= len(nr):
        return False
    for seg in np.split("/"):
        if seg in (".", ".."):
            return False
    if not np.startswith(nr):
        return False
    return np[len(nr)] == "/"
