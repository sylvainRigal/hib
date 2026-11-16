"""Extensible item-type table, plus the load_item_types / choose_item_type
helpers.

The recognized item types are read from a user-editable `itemTypes.txt` in the
config directory. parse/resolve are pure; load_item_types does the file I/O
(bootstrapping the embedded default when missing); choose_item_type drives the
interactive "Item type" prompt: an exact canonical match is accepted silently, a
case-only match is confirmed (and canonicalized), an unknown value is accepted
after confirmation, "?" lists the table, and a number selects by index.
"""
import os


def _ascii_lower(s):
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


class ItemTypeTable(object):
    def __init__(self, names):
        self.types = names                  # list of canonical name strings, file order

    def find_exact(self, typed):
        """Byte-for-byte match against a canonical name, else None."""
        for n in self.types:
            if n == typed:
                return n
        return None

    def find_fold(self, typed):
        """First case-insensitive (ASCII fold) match in file order, else None."""
        tl = _ascii_lower(typed)
        for n in self.types:
            if _ascii_lower(n) == tl:
                return n
        return None


def parse(text):
    """Parse newline-separated `text`: each line trimmed (CRLF-safe), blanks and
    full-line '#' comments skipped, de-duplicated case-insensitively (first
    spelling wins)."""
    names = []
    for raw in text.split("\n"):
        line = raw.strip(" \t\r")
        if not line or line[0] == "#":
            continue
        low = _ascii_lower(line)
        if any(_ascii_lower(n) == low for n in names):
            continue
        names.append(line)
    return ItemTypeTable(names)


def resolve(table, typed):
    """Classify `typed` -> ('exact', canonical) / ('case_fold', canonical) /
    ('unknown', typed)."""
    t = table.find_exact(typed)
    if t is not None:
        return ("exact", t)
    t = table.find_fold(typed)
    if t is not None:
        return ("case_fold", t)
    return ("unknown", typed)


# Embedded default: header comment + 40 names (Zotero types in schema order, then
# the hib-specific `script`/`procedure`/`DE`). Single source of truth for the on-disk
# bootstrap and the in-memory fallback. Kept with no trailing newline, the same
# layout as the itemTypes.txt files in existing archives.
_HEADER = (
    "# hib item types - one canonical identifier per line.\n"
    "# Lines starting with '#' are comments; blank lines are ignored.\n"
    '# The "Item type" prompt is free text and matches these case-insensitively;\n'
    '# type "?" at that prompt to list them, or pick by number. Edit this file to\n'
    "# add your own types (one per line); hib rereads it on every run."
)
_DEFAULT_NAMES = [
    "artwork", "audioRecording", "bill", "blogPost", "book", "bookSection", "case",
    "computerProgram", "conferencePaper", "dataset", "dictionaryEntry", "document",
    "email", "encyclopediaArticle", "film", "forumPost", "hearing", "instantMessage",
    "interview", "journalArticle", "letter", "magazineArticle", "manuscript", "map",
    "newspaperArticle", "patent", "podcast", "preprint", "presentation",
    "radioBroadcast", "report", "standard", "statute", "thesis", "tvBroadcast",
    "videoRecording", "webpage", "script", "procedure", "DE",
]
DEFAULT_ITEM_TYPES_TEXT = _HEADER + "\n" + "\n".join(_DEFAULT_NAMES)


def load_item_types(config_dir, out):
    """Load the table from <config_dir>/itemTypes.txt. Best-effort: a missing file
    is bootstrapped with the embedded defaults (and used even if that write fails);
    any other read error falls back with a note; a file parsing to nothing also
    falls back."""
    types_path = os.path.join(config_dir, "itemTypes.txt")
    try:
        with open(types_path, "rb") as f:
            text = f.read().decode("utf-8", "surrogateescape")
    except FileNotFoundError:
        try:
            with open(types_path, "w", encoding="utf-8", newline="") as f:
                f.write(DEFAULT_ITEM_TYPES_TEXT)
        except OSError:
            pass
        text = DEFAULT_ITEM_TYPES_TEXT
    except OSError as e:
        out("hib: could not read itemTypes.txt (%s); using built-in defaults." % e)
        text = DEFAULT_ITEM_TYPES_TEXT
    table = parse(text)
    if not table.types:
        return parse(DEFAULT_ITEM_TYPES_TEXT)
    return table


def _confirm_yes(ask, label):
    """Yes/no (default YES): yes unless the answer's first letter is 'n'/'N'.
    Empty/EOF keeps the default."""
    ans = ask(label, "y")
    return not (ans and ans[0].lower() == "n")


def choose_item_type(table, ask, out, default_type):
    """Resolve the item type interactively against `table`. Accepting the offered
    default (Enter/EOF/retyping it) returns it verbatim with NO matching and NO
    confirmation (keeps piped runs deterministic and a .bib-supplied default
    untouched). Otherwise: "?" lists the table; a number selects by index; an exact
    name is accepted; a case-only match is confirmed then canonicalized; an unknown
    value is accepted after confirmation. A declined confirmation re-prompts."""
    while True:
        typed = ask('Item type ("?" to list)', default_type)

        # Rule 0: the accepted default bypasses matching/confirmation.
        if typed == default_type:
            return typed

        if typed == "?":
            out("Known item types:")
            for i, name in enumerate(table.types):
                out("  %2d) %s" % (i + 1, name))
            out('Type a name or a number, or "?" to list again.')
            continue

        # A number selects by 1-based index. Require all ASCII digits so "+20" etc.
        # fall through to the free-text confirm path.
        if typed and all("0" <= c <= "9" for c in typed):
            n = int(typed)
            if 1 <= n <= len(table.types):
                return table.types[n - 1]

        kind, val = resolve(table, typed)
        if kind == "exact":
            return val
        elif kind == "case_fold":
            if _confirm_yes(ask, 'Use "%s"?' % val):
                return val
        else:  # unknown
            if _confirm_yes(ask, '"%s" is not a known type; use it anyway?' % val):
                return val
        # declined -> re-prompt (loop)
