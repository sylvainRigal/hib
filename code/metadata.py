"""JSON metadata file for a stored entry.

`render` returns the JSON text (entry fields + citekey + file paths), byte-stable
so it matches the files in existing archives. Python strings are always valid
Unicode, so no invalid-UTF-8 -> U+FFFD handling is needed here.
"""


class Metadata(object):
    def __init__(self, citekey, entry, local_file_path, local_folder_path,
                 html_path, pdf_local_path, remote_path=None):
        self.citekey = citekey
        self.entry = entry
        self.local_file_path = local_file_path
        self.local_folder_path = local_folder_path
        self.html_path = html_path
        self.pdf_local_path = pdf_local_path
        self.remote_path = remote_path


def _json_string(s):
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif ord(ch) < 0x20:
            out.append('\\u%04x' % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _is_canonical_json_int(s):
    if not s:
        return False
    if s == "0":
        return True
    if s[0] == "0":
        return False
    return all("0" <= c <= "9" for c in s)


def _field(key, value):
    return '  "%s": %s' % (key, _json_string(value))


def _version_field(key, value):
    v = value if _is_canonical_json_int(value) else _json_string(value)
    return '  "%s": %s' % (key, v)


def render(m):
    e = m.entry
    out = []
    a = out.append
    a("{\n")
    a(_field("citekey", m.citekey)); a(",\n")
    a(_field("reference", e.reference)); a(",\n")
    a(_field("title", e.title)); a(",\n")
    a(_field("shortTitle", e.short_title)); a(",\n")
    a(_field("itemType", e.item_type)); a(",\n")
    a(_version_field("version", e.version)); a(",\n")

    a('  "authors": [')
    for i, (last, first) in enumerate(e.authors):
        if i != 0:
            a(", ")
        a('{"lastName": ')
        a(_json_string(last))
        a(', "firstName": ')
        a(_json_string(first))
        a("}")
    a("],\n")

    a(_field("date", e.date)); a(",\n")

    a('  "tags": [')
    for i, t in enumerate(e.tags):
        if i != 0:
            a(", ")
        a(_json_string(t))
    a("],\n")

    a(_field("description", e.description)); a(",\n")
    a(_field("localFilePath", m.local_file_path)); a(",\n")
    a(_field("localFolderPath", m.local_folder_path)); a(",\n")
    a(_field("htmlPath", m.html_path)); a(",\n")
    a(_field("pdfLocalPath", m.pdf_local_path))
    if m.remote_path is not None:
        a(",\n")
        a(_field("remotePath", m.remote_path))
    a("\n}\n")
    return "".join(out)
