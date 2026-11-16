"""Filename / slug helpers.

Rules (confirmed with the user): fold accents to ASCII, keep original case,
spaces -> "_", keep only [A-Za-z0-9._-], DROP any other character, collapse
repeated "_", trim leading/trailing "_-.", empty -> "file", cap length.
Python iterates over codepoints natively, so no manual UTF-8 decoding is needed.
"""

MAX_BASE_LEN = 80


def base_name(path):
    """Last path segment (after the final '\\' or '/')."""
    start = 0
    for i, c in enumerate(path):
        if c == "\\" or c == "/":
            start = i + 1
    return path[start:]


def strip_extension(name):
    """`name` without its final extension (the last '.' not at index 0)."""
    dot = None
    for i, c in enumerate(name):
        if c == "." and i != 0:
            dot = i
    return name[:dot] if dot is not None else name


def extension(name):
    """Final extension INCLUDING the dot (e.g. '.docx'), or '' when none."""
    dot = None
    for i, c in enumerate(name):
        if c == "." and i != 0:
            dot = i
    return name[dot:] if dot is not None else ""


def _is_kept(ch):
    return (
        "A" <= ch <= "Z" or "a" <= ch <= "z" or "0" <= ch <= "9" or ch in "-_."
    )


def _fold_non_ascii(cp):
    """ASCII replacement for a non-ASCII codepoint; '' means drop it."""
    if 0xC0 <= cp <= 0xC5:
        return "A"
    if cp == 0xC6:
        return "AE"
    if cp == 0xC7:
        return "C"
    if 0xC8 <= cp <= 0xCB:
        return "E"
    if 0xCC <= cp <= 0xCF:
        return "I"
    if cp == 0xD0:
        return "D"
    if cp == 0xD1:
        return "N"
    if (0xD2 <= cp <= 0xD6) or cp == 0xD8:
        return "O"
    if 0xD9 <= cp <= 0xDC:
        return "U"
    if cp == 0xDD:
        return "Y"
    if cp == 0xDF:
        return "ss"
    if 0xE0 <= cp <= 0xE5:
        return "a"
    if cp == 0xE6:
        return "ae"
    if cp == 0xE7:
        return "c"
    if 0xE8 <= cp <= 0xEB:
        return "e"
    if 0xEC <= cp <= 0xEF:
        return "i"
    if cp == 0xF0:
        return "d"
    if cp == 0xF1:
        return "n"
    if (0xF2 <= cp <= 0xF6) or cp == 0xF8:
        return "o"
    if 0xF9 <= cp <= 0xFC:
        return "u"
    if cp in (0xFD, 0xFF):
        return "y"
    if cp == 0x152:
        return "OE"
    if cp == 0x153:
        return "oe"
    if cp == 0x178:
        return "Y"
    return ""


def parse_source_path(s):
    """Parse the source-path prompt input -> (cleaned_path, keep_remote).
    Strips surrounding straight quotes and a trailing '*' (inside or outside the
    quotes)."""
    s = s.strip(" \t\r\n")
    keep_remote = False
    if s.endswith("*"):
        keep_remote = True
        s = s[:-1].rstrip(" \t")
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    if s.endswith("*"):
        keep_remote = True
        s = s[:-1]
    return s.strip(" \t"), keep_remote


def parse_short_title(s):
    """Parse the short-title prompt input -> (value, name_from_card). A single
    trailing '*' (and the space before it) is stripped; the rest is verbatim."""
    s = s.strip(" \t\r\n")
    name_from_card = False
    if s.endswith("*"):
        name_from_card = True
        s = s[:-1].rstrip(" \t")
    return s, name_from_card


def sanitize_base(s, collapse=True):
    """Slugify into a simple, robust base name. `collapse=False` keeps runs of
    underscores as they are -- used for the metadata file name, which must read
    back as the entry's reference character for character (a default reference
    with no author is '<type>_<short>__<date>', and that '__' is part of it)."""
    folded = []
    for ch in s:
        cp = ord(ch)
        if cp < 0x80:
            if ch == " ":
                folded.append("_")
            elif _is_kept(ch):
                folded.append(ch)
            # else: drop
        else:
            folded.append(_fold_non_ascii(cp))
    folded = "".join(folded)

    if collapse:
        collapsed = []
        prev_underscore = False
        for c in folded:
            if c == "_":
                if prev_underscore:
                    continue
                prev_underscore = True
            else:
                prev_underscore = False
            collapsed.append(c)
        folded = "".join(collapsed)

    trimmed = folded.strip("_-.")
    if not trimmed:
        return "file"
    return trimmed[:MAX_BASE_LEN]


def sanitize_filename(path):
    """Stored-copy file name: slugify the stem, re-append the original extension."""
    base = base_name(path)
    ext = extension(base)
    slug = sanitize_base(strip_extension(base))
    return slug + ext if ext else slug


def cite_word(s):
    """Fold into a citekey word: accents -> ASCII, keep [A-Za-z0-9._-], DROP
    spaces and other chars, capitalize the first letter."""
    out = []
    for ch in s:
        cp = ord(ch)
        if cp < 0x80:
            if ch == " ":
                continue
            if _is_kept(ch):
                out.append(ch)
        else:
            out.append(_fold_non_ascii(cp))
    r = "".join(out)
    if r and "a" <= r[0] <= "z":
        r = r[0].upper() + r[1:]
    return r
