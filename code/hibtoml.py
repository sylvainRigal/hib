"""Minimal TOML-subset parser for hib's config. Only what hib needs, NOT full
TOML:

  - `# comments` (whole-line, and trailing on bare/quoted values)
  - `[section]` headers (one level, no dotted/nested tables)
  - `key = value`, split on the FIRST `=`
  - literal strings  'C:\\path'  (raw -- ideal for Windows paths)
  - basic strings    "..."       (with \\\\ \\" \\n \\r \\t escapes)

Keys before any header live in the root section "". A `Toml` is a dict keyed by
(section, key); `Toml.get(section, key)` returns the value or None (first wins).
"""


class TomlError(Exception):
    pass


class Toml(dict):
    """dict {(section, key): value} with a convenience getter."""

    def get_value(self, section, key):
        return self.get((section, key))


def parse(text):
    table = Toml()
    section = ""
    for raw_line in text.split("\n"):
        line = raw_line.strip(" \t\r")
        if not line or line[0] == "#":
            continue
        if line[0] == "[":
            close = line.find("]")
            if close < 0:
                raise TomlError("malformed section header: " + line)
            section = line[1:close].strip(" \t")
            continue
        eq = line.find("=")
        if eq < 0:
            raise TomlError("malformed line (no '='): " + line)
        key = line[:eq].strip(" \t")
        if not key:
            raise TomlError("malformed line (empty key): " + line)
        value = _parse_value(line[eq + 1:].strip(" \t"))
        table.setdefault((section, key), value)  # first occurrence wins
    return table


def _parse_value(raw):
    if not raw:
        return ""
    if raw[0] == "'":
        close = raw.find("'", 1)
        if close < 0:
            raise TomlError("unterminated literal string")
        return raw[1:close]
    if raw[0] == '"':
        return _parse_basic(raw)
    hash_pos = raw.find("#")
    end = hash_pos if hash_pos >= 0 else len(raw)
    return raw[:end].strip(" \t")


_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


def _parse_basic(raw):
    out = []
    i = 1  # skip the opening quote
    n = len(raw)
    while i < n:
        c = raw[i]
        if c == '"':
            return "".join(out)
        if c == "\\":
            i += 1
            if i >= n:
                raise TomlError("unterminated basic string")
            out.append(_ESCAPES.get(raw[i], raw[i]))  # unknown escape -> verbatim
        else:
            out.append(c)
        i += 1
    raise TomlError("unterminated basic string")


def _toml_string(value):
    """Encode `value` as a TOML string: single-quoted literal when it has no
    `'`/newline (best for Windows paths), else a basic string with escapes."""
    if "'" not in value and "\n" not in value and "\r" not in value:
        return "'" + value + "'"
    out = ['"']
    for c in value:
        out.append({"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(c, c))
    out.append('"')
    return "".join(out)


def render(storage, pdf=None):
    """Render a config.toml from a `storage` dict (file/html/json[/trash]) and an
    optional `pdf` dict (powershell/cmd)."""
    lines = [
        "# hib configuration.",
        "# Single-quoted '...' literal strings keep Windows backslashes as-is.",
        "",
        "[storage]",
    ]
    for k in ("file", "html", "json", "trash"):
        if storage.get(k):
            lines.append("%-5s = %s" % (k, _toml_string(storage[k])))
    lines.append("")
    lines.append("[pdf]")
    pdf = pdf or {}
    for k in ("powershell", "cmd"):
        if pdf.get(k) is not None:
            lines.append("%s = %s" % (k, _toml_string(pdf[k])))
    return "\n".join(lines) + "\n"


TEMPLATE = """\
# hib configuration. Fill in your storage paths below, then re-run hib.
# Single-quoted '...' literal strings keep Windows backslashes as-is.

[storage]
file  = ''   # directory for copied files (the "f" folder)
html  = ''   # directory for the HTML cards
json  = ''   # directory for the per-entry JSON metadata
# trash = ''  # optional; defaults to <file>\\trash

# hib converts Word -> PDF in Python (docx2pdf, which drives Word). An external
# fallback converter (pandoc, soffice, ...) is declared in a separate file, see
# README. The [pdf] keys below are not used: they are read and kept only so an
# existing config that sets them survives a round-trip.
# [pdf]
# powershell = ''
# cmd = ''

# Default destination of `hib backup` (a command-line folder overrides it).
# [backup]
# target = ''
"""
