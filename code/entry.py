"""Entry data model + the interactive-input parsers.
Authors are (last_name, first_name) tuples throughout.
"""


def parse_author_list(s):
    """Comma-separated 'Last:First' items -> [(last, first), ...]; a missing ':'
    means the whole item is the last name; empty items are skipped."""
    out = []
    for raw in s.split(","):
        item = raw.strip(" \t\r")
        if not item:
            continue
        if ":" in item:
            colon = item.index(":")
            last = item[:colon].strip(" \t\r")
            first = item[colon + 1:].strip(" \t\r")
        else:
            last, first = item, ""
        out.append((last, first))
    return out


def parse_tag_list(s):
    """Comma-separated tags, trimmed, empties dropped."""
    return [t for t in (raw.strip(" \t\r") for raw in s.split(",")) if t]


def authors_to_input(authors):
    """Inverse of parse_author_list: 'Last:First, ...' (':First' omitted when empty)."""
    return ", ".join(last + (":" + first if first else "") for last, first in authors)


def tags_to_input(tags):
    return ", ".join(tags)


class Entry(object):
    """Render-side model (what html/metadata consume)."""

    def __init__(self, title, item_type, authors, date, tags, description,
                 version="1", short_title="", reference="", citekey="",
                 local_path=None, remote_path=None, pdf_path=None):
        self.title = title
        self.item_type = item_type
        self.authors = authors          # [(last, first), ...]
        self.date = date
        self.tags = tags                # [str, ...]
        self.description = description
        self.version = version
        self.short_title = short_title
        self.reference = reference
        self.citekey = citekey          # shown on the card (read-only identifier)
        self.local_path = local_path
        self.remote_path = remote_path
        self.pdf_path = pdf_path
