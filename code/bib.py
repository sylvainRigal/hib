"""Minimal BibTeX / biblatex parser for the optional `.bib` import.
Tokenizes `@type{key, field = value, ...}` entries with case-insensitive
field lookup; a value's surrounding `{...}`/`"..."` is stripped, inner braces are
removed, and whitespace runs collapse to a single space. Best-effort: malformed
input is skipped, never raised.

Scope: import only PRE-FILLS the interactive `add` defaults. The .bib citation key
is IGNORED (hib generates its own citekey), and the .bib does not supply the stored
file. LaTeX command decoding (`\\'e` -> e-acute) is NOT handled; UTF-8 .bib files
import cleanly and LaTeX-escaped accents survive verbatim.
"""
import dates


_WS = " \t\r\n"


def _is_ascii_alpha(c):
    return ("a" <= c <= "z") or ("A" <= c <= "Z")


class BibEntry(object):
    def __init__(self, entry_type, key, fields):
        self.entry_type = entry_type          # lower-cased
        self.key = key                         # verbatim, ignored by hib
        self.fields = fields                   # [(name_lower, value), ...]

    def get(self, name):
        """Case-insensitive field lookup -> cleaned value or None."""
        low = name.lower()
        for n, v in self.fields:
            if n == low:
                return v
        return None


def _skip_ws(text, i):
    n = len(text)
    while i < n and text[i] in _WS:
        i += 1
    return i


def _skip_balanced_braces(text, i):
    """`i` is just after the opening '{'; return the index just past the match."""
    n = len(text)
    depth = 1
    while i < n and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return i


def _is_skippable_type(etype):
    return etype in ("comment", "preamble", "string")


def _read_value(text, i, close):
    """Read a field value at `i` (after '=' + ws) -> (inner_text, new_i)."""
    n = len(text)
    if i >= n:
        return "", i
    if text[i] == "{":
        depth = 1
        i += 1
        start = i
        while i < n and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        val = text[start:i]
        if i < n:
            i += 1                      # past '}'
        return val, i
    if text[i] == '"':
        depth = 0
        i += 1
        start = i
        while i < n:
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                if depth > 0:
                    depth -= 1
            elif c == '"' and depth == 0:
                break
            i += 1
        val = text[start:i]
        if i < n:
            i += 1                      # past '"'
        return val, i
    # Bare token (number / unquoted) until ',' or the entry close.
    start = i
    while i < n and text[i] != "," and text[i] != close:
        i += 1
    return text[start:i].strip(_WS), i


def _clean_value(raw):
    """Remove inner braces and collapse whitespace runs to single spaces."""
    out = []
    prev_space = False
    for c in raw:
        if c == "{" or c == "}":
            continue
        if c in _WS:
            if not prev_space:
                out.append(" ")
                prev_space = True
            continue
        out.append(c)
        prev_space = False
    return "".join(out).strip(" ")


def parse(text):
    """Parse `text` into a list of BibEntry. Best-effort; never raises on syntax."""
    entries = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "@":
            i += 1
            continue
        i += 1                          # past '@'

        type_start = i
        while i < n and _is_ascii_alpha(text[i]):
            i += 1
        etype = text[type_start:i].lower()

        i = _skip_ws(text, i)
        if i >= n or (text[i] != "{" and text[i] != "("):
            continue
        open_ch = text[i]
        close = ")" if open_ch == "(" else "}"
        i += 1

        if _is_skippable_type(etype):
            if open_ch == "{":
                i = _skip_balanced_braces(text, i)
            else:
                while i < n and text[i] != close:
                    i += 1
                if i < n:
                    i += 1
            continue

        # Citation key: up to the first ',' or the entry close.
        key_start = i
        while i < n and text[i] != "," and text[i] != close:
            i += 1
        key = text[key_start:i].strip(_WS)

        fields = []
        if i < n and text[i] == ",":
            i += 1
            while True:
                i = _skip_ws(text, i)
                if i >= n or text[i] == close:
                    break
                name_start = i
                while i < n and text[i] != "=" and text[i] != "," and text[i] != close:
                    i += 1
                raw_name = text[name_start:i].strip(_WS)
                if i >= n or text[i] != "=":
                    if i < n and text[i] == ",":      # tolerate a stray comma
                        i += 1
                        continue
                    break
                i += 1                  # past '='
                i = _skip_ws(text, i)
                raw_value, i = _read_value(text, i, close)
                if raw_name:
                    fields.append((raw_name.lower(), _clean_value(raw_value)))
                i = _skip_ws(text, i)
                if i < n and text[i] == ",":
                    i += 1
                    continue
                break
        if i < n and text[i] == close:
            i += 1

        entries.append(BibEntry(etype, key, fields))
    return entries


def _split_authors(value):
    """Split a BibTeX author value on ' and ' (case-insensitive on 'and')."""
    out = []
    start = 0
    i = 0
    n = len(value)
    while i + 5 <= n:
        if (value[i] == " " and value[i + 1].lower() == "a" and value[i + 2].lower() == "n"
                and value[i + 3].lower() == "d" and value[i + 4] == " "):
            out.append(value[start:i])
            i += 5
            start = i
        else:
            i += 1
    out.append(value[start:])
    return out


def authors_to_hib(value):
    """Convert a BibTeX author value into hib's 'Last:First, Last2:First2' input
    (the colon omitted when there is no first name). Handles 'Last, First' and
    'First Last' forms."""
    result = []
    for raw in _split_authors(value):
        a = raw.strip(" ")
        if not a:
            continue
        last, first = a, ""
        comma = a.find(",")
        if comma >= 0:
            last = a[:comma].strip(" ")
            first = a[comma + 1:].strip(" ")
        else:
            sp = a.rfind(" ")
            if sp >= 0:
                first = a[:sp].strip(" ")
                last = a[sp + 1:].strip(" ")
        result.append(last + (":" + first if first else ""))
    return ", ".join(result)


def _try_uint(t, limit):
    """Strict unsigned-integer parse: an optional single leading '+', then
    ASCII digits with INTERIOR '_' group separators (leading/trailing/right-after-
    the-sign '_' are rejected; doubled interior '_' like '1__2' is accepted). No
    '-', no surrounding whitespace. None on reject or when > limit (u8/u16 overflow)."""
    if not t:
        return None
    s = t[1:] if t[0] == "+" else t
    if not s or s[0] == "_" or s[-1] == "_":
        return None
    s = s.replace("_", "")
    if not s or not all("0" <= c <= "9" for c in s):
        return None
    v = int(s)
    return v if v <= limit else None


def _parse_month(s):
    t = s.strip(" ")
    num = _try_uint(t, 255)             # parseInt(u8)
    if num is not None:
        return num if 1 <= num <= 12 else None
    names = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    if len(t) < 3:
        return None
    pre = t[:3].lower()
    for idx, nm in enumerate(names):
        if pre == nm:
            return idx + 1
    return None


def to_hib_date(entry):
    """Derive a 'DD/MM/YYYY' default from an entry's date fields: biblatex `date`
    (YYYY[-MM[-DD]]) if present, else `year` (+ optional `month`/`day`). Missing
    month/day default to 01. None when no year is found."""
    year = None
    month = 1
    day = 1

    d = entry.get("date")
    if d is not None:
        segs = d.strip(" ").split("-")
        year = _try_uint(segs[0].strip(" "), 65535)
        if len(segs) >= 2:
            m = _parse_month(segs[1])
            if m is not None:
                month = m
        if len(segs) >= 3:
            dd = _try_uint(segs[2].strip(" "), 255)
            if dd is not None:
                day = dd
    if year is None:
        ys = entry.get("year")
        if ys is not None:
            year = _try_uint(ys.strip(" "), 65535)
        ms = entry.get("month")
        if ms is not None:
            m = _parse_month(ms)
            if m is not None:
                month = m
        ds = entry.get("day")
        if ds is not None:
            dd = _try_uint(ds.strip(" "), 255)
            if dd is not None:
                day = dd
    if year is None:
        return None
    if month < 1 or month > 12:
        month = 1
    if day < 1 or day > 31:
        day = 1
    return dates.format_dmy(year, month, day)


def semicolons_to_commas(s):
    """';' -> ',' (some tools separate keywords with semicolons), so the value
    parses as hib's comma-separated tag list."""
    return s.replace(";", ",")
