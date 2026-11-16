"""Read a stored entry's JSON metadata (the inverse of metadata.render).
Permissive: a missing/non-string scalar becomes ""
(except remote_path, which is None when absent). `version` is normalized to a
string (the writer emits a bare number for canonical ints).
"""
import json


def _s(obj, key):
    v = obj.get(key)
    return v if isinstance(v, str) else ""


class Entry(object):
    def __init__(self, obj):
        self.citekey = _s(obj, "citekey")
        self.reference = _s(obj, "reference")
        self.title = _s(obj, "title")
        self.short_title = _s(obj, "shortTitle")
        self.item_type = _s(obj, "itemType")
        # A string stays; an int/float is stringified; a
        # missing/null/bool/array/object value defaults to "1". (bool is checked
        # before int since Python's bool is an int subclass.)
        v = obj.get("version")
        if isinstance(v, str):
            self.version = v
        elif isinstance(v, bool):
            self.version = "1"
        elif isinstance(v, int):
            self.version = str(v)
        elif isinstance(v, float):
            # On a float: an integral, finite float
            # renders as an int ("2.0" -> "2", "1e3" -> "1000") so it re-emits as a
            # canonical bare number; a non-integral float keeps its decimal form.
            if v == v and v not in (float("inf"), float("-inf")) and v == int(v):
                self.version = str(int(v))
            else:
                self.version = repr(v)
        else:
            self.version = "1"
        self.date = _s(obj, "date")
        self.description = _s(obj, "description")
        self.local_file_path = _s(obj, "localFilePath")
        self.local_folder_path = _s(obj, "localFolderPath")
        self.html_path = _s(obj, "htmlPath")
        self.pdf_local_path = _s(obj, "pdfLocalPath")
        rp = obj.get("remotePath")
        self.remote_path = rp if isinstance(rp, str) else None
        self.authors = [
            (_s(a, "lastName"), _s(a, "firstName"))
            for a in obj.get("authors", []) if isinstance(a, dict)
        ]
        self.tags = [t for t in obj.get("tags", []) if isinstance(t, str)]


def parse(text):
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("metadata JSON is not an object")
    return Entry(obj)
