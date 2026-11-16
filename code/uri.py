"""File-URI helpers for the card's open buttons.

Backslashes become slashes; every byte outside the URI-safe set is
percent-encoded at the BYTE level (so 'é' UTF-8 C3 A9 -> %C3%A9). Office docs
get an ms-word:/ms-excel:/ms-powerpoint: "open for edit" scheme prefix.
"""

_OFFICE = (".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")


def _last_extension(path):
    seg = 0
    for i, c in enumerate(path):
        if c == "\\" or c == "/":
            seg = i + 1
    base = path[seg:]
    dot = None
    for i, c in enumerate(base):
        if c == "." and i != 0:
            dot = i
    return base[dot:] if dot is not None else ""


def is_office_ext(ext):
    return ext.lower() in _OFFICE


def _office_prefix(ext):
    e = ext.lower()
    if e in (".doc", ".docx"):
        return "ms-word:ofe|u|"
    if e in (".xls", ".xlsx"):
        return "ms-excel:ofe|u|"
    if e in (".ppt", ".pptx"):
        return "ms-powerpoint:ofe|u|"
    return ""


def _byte_unreserved(b):
    return (0x41 <= b <= 0x5A) or (0x61 <= b <= 0x7A) or (0x30 <= b <= 0x39) \
        or b in (0x2D, 0x2E, 0x5F, 0x7E)   # - . _ ~


def file_uri(win_path):
    out = ["file:///"]
    for b in win_path.encode("utf-8"):
        if b == 0x5C:          # backslash -> slash
            b = 0x2F
        if b == 0x2F or b == 0x3A or _byte_unreserved(b):   # '/' ':' kept
            out.append(chr(b))
        else:
            out.append("%%%02X" % b)   # uppercase hex
    return "".join(out)


def open_href(win_path):
    return _office_prefix(_last_extension(win_path)) + file_uri(win_path)
