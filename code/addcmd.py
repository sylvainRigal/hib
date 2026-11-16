"""The interactive `add` flow.

Prompts for an entry's fields, copies the source into a fresh random folder under
the file-storage path, best-effort-generates a PDF, then writes the HTML card and
the JSON metadata.

Card and JSON are written with '\\n' line endings and UTF-8 (no BOM), so new
cards are byte-compatible with the cards already in an existing archive.
"""
import os
import shutil
import sys

import sanitize
import dates
import entry as entry_mod
import citekey as citekey_mod
import reference as reference_mod
import naming
import locate
import bib as bib_mod
import item_types
import html as html_mod
import metadata as metadata_mod
import pdfgen


def _nonempty(v):
    return v if v else None      # None or "" -> None


def _coalesce(*vals):
    """First non-None value, else "". Like a null-coalescing chain, it
    falls through ONLY on None -- so a present-but-empty field wins over the next
    one (unlike Python's `or`, which would fall through on the empty string)."""
    for v in vals:
        if v is not None:
            return v
    return ""


_NO_BIB = {"item_type": None, "title": None, "short_title": None, "version": None,
           "authors": None, "date": None, "tags": None, "description": None}


def _load_bib_defaults(ask, out):
    """Prompt for an optional .bib path; if given, parse it and return field
    defaults from its FIRST entry (each None when absent). Best-effort: a
    missing/unreadable file or a .bib with no entries prints a note and yields no
    defaults, so the normal add flow always continues."""
    raw = ask("Import metadata from a .bib (path, empty to skip)", "")
    bib_path, _ = sanitize.parse_source_path(raw)
    if not bib_path:
        return dict(_NO_BIB)
    try:
        with open(bib_path, "rb") as f:
            # Decode as raw bytes: UTF-8, surrogateescape so a non-UTF-8
            # byte round-trips to its original on write (matching the byte pass-through).
            text = f.read().decode("utf-8", "surrogateescape")
    except OSError as e:
        out("hib: cannot read .bib '%s' (%s); continuing without import." % (bib_path, e))
        return dict(_NO_BIB)
    entries = bib_mod.parse(text)
    if not entries:
        out("hib: no entries found in the .bib; continuing without import.")
        return dict(_NO_BIB)
    if len(entries) > 1:
        out("hib: %d entries in the .bib; using the first." % len(entries))
    e = entries[0]
    author = e.get("author")
    keywords = e.get("keywords")
    return {
        "item_type": _nonempty(e.entry_type),
        "title": _nonempty(e.get("title") or ""),
        "short_title": _nonempty(e.get("shorttitle") or ""),
        "version": _nonempty(e.get("version") or ""),
        "authors": _nonempty(bib_mod.authors_to_hib(author)) if author is not None else None,
        "date": bib_mod.to_hib_date(e),
        "tags": _nonempty(bib_mod.semicolons_to_commas(keywords)) if keywords is not None else None,
        # abstract THEN note, falling through only on absence (a present-but-empty
        # abstract wins -> empty description), a null-coalescing chain.
        "description": _nonempty(_coalesce(e.get("abstract"), e.get("note"))),
    }


def _write_text_file(path, text):
    # newline="" : do NOT translate '\n' to '\r\n' (byte-identical files on every OS);
    # utf-8 (no BOM). surrogateescape lets a byte that
    # came in via stdin's surrogateescape decode round-trip back to its original
    # byte (raw bytes pass through) instead of crashing the write.
    with open(path, "w", encoding="utf-8", newline="", errors="surrogateescape") as f:
        f.write(text)


def make_random_folder(root):
    """Create a fresh, uniquely named 'a<yyyymmdd><8 hex>' subfolder under `root`
    and return its full path. `root` is created."""
    os.makedirs(root, exist_ok=True)
    y, m, d = dates.today()
    ymd = dates.compact_ymd(y, m, d)
    for _ in range(1000):
        name = "a%s%s" % (ymd, os.urandom(4).hex())   # 8 lowercase hex chars
        folder = os.path.join(root, name)
        if os.path.exists(folder):
            continue
        os.makedirs(folder)
        return folder
    raise OSError("no free folder name")


def resolve_card_path(html_dir, initial_base, ask, out, exclude=None, allow_overwrite=True):
    """Where to write the card. A free name (or one equal to `exclude`, an entry's
    own old card during update) -> its path; a collision with a DIFFERENT card
    offers [a]uto-rename / [m]anual / [e]overwrite (add only) / [c]ancel. None on
    cancel."""
    base = initial_base
    while True:
        name = naming.card_name(base)
        path = os.path.join(html_dir, name)
        if exclude is not None and locate.same_path(path, exclude):
            return exclude          # keep the existing file's on-disk casing
        if not os.path.exists(path):
            return path

        def taken(nm):
            p = os.path.join(html_dir, nm)
            if exclude is not None and locate.same_path(p, exclude):
                return False        # the entry's own old card counts as free
            return os.path.exists(p)
        auto_name = naming.first_free_numbered_name(base, taken)

        out("")
        out('A card named "%s" already exists in the html folder.' % name)
        out("  [a] auto-rename to  %s" % auto_name)
        out("  [m] enter a new name manually")
        if allow_overwrite:
            out("  [e] overwrite the existing card")
        out("  [c] cancel (write nothing)")
        choice = ask("Choice (a/m/e/c)" if allow_overwrite else "Choice (a/m/c)", "a")
        c0 = choice[0].lower() if choice else "a"
        if c0 == "a":
            return os.path.join(html_dir, auto_name)
        elif c0 == "e":
            if allow_overwrite:
                return path
            out("Cannot overwrite another entry's card here.")
        elif c0 == "c":
            return None
        elif c0 == "m":
            typed = ask("New name (without .html)", base)
            base = sanitize.sanitize_base(typed)
        else:
            out("Please answer with a valid choice.")


def resolve_json_path(json_dir, base, exclude=None):
    """First free '<base>.json', '<base>_1.json', ...; a path equal to `exclude`
    (the entry's own JSON during update) is treated as free so it lands back on
    its existing file. `base` comes from
    the entry's reference (naming.json_base), not from its citekey."""
    n = 0
    while n < 1000000:
        name = "%s.json" % base if n == 0 else "%s_%d.json" % (base, n)
        path = os.path.join(json_dir, name)
        if exclude is not None and locate.same_path(path, exclude):
            return exclude
        if not os.path.exists(path):
            return path
        n += 1
    raise OSError("no free json name")


def _write_entry_metadata(config, e, citekey, folder, local_file, pdf_path, html_path):
    m = metadata_mod.Metadata(
        citekey=citekey, entry=e, local_file_path=local_file,
        local_folder_path=folder, html_path=html_path,
        pdf_local_path=pdf_path, remote_path=e.remote_path)
    text = metadata_mod.render(m)
    json_dir = config.json_storage_path.rstrip("\\/")
    os.makedirs(json_dir, exist_ok=True)
    path = resolve_json_path(json_dir, naming.json_base(e.reference, citekey))
    _write_text_file(path, text)
    return path


def run_add(config, source_arg, config_dir):
    """Run the interactive add. Prompts on stdout; reads stdin. Returns an exit
    code (0 success or graceful cancel/skip, 1 on a hard I/O failure)."""

    def out(s):
        sys.stdout.write(s + "\n")

    def ask(label, default):
        if default:
            sys.stdout.write("%s [%s]: " % (label, default))
        else:
            sys.stdout.write("%s: " % label)
        sys.stdout.flush()
        line = sys.stdin.readline()
        if line == "":                       # EOF -> default
            return default
        t = line.strip(" \t\r\n")
        return t if t else default

    out("hib - add an entry")
    out("")

    # 1) Source file path (from the command line, else prompted). Accepts quotes
    #    and a trailing '*' (keep a remote link + a local PDF link on the card).
    if source_arg:
        out("Source file path: %s" % source_arg)
        path_input = source_arg
    else:
        path_input = ask("Source file path", "")
    source_path, keep_remote = sanitize.parse_source_path(path_input)
    if not source_path:
        out("hib: no source file path given.")
        return 0
    if not os.path.exists(source_path):
        out("hib: source file not found: %s" % source_path)
        return 0
    default_title = sanitize.strip_extension(sanitize.base_name(source_path))

    # 2) Optional: import field DEFAULTS from a .bib file. The source file above
    #    is still what gets stored; only the prompts below are pre-filled, and the
    #    .bib citation key is ignored (hib generates its own citekey).
    bib = _load_bib_defaults(ask, out)

    # 3) Item type, matched against the extensible table. The default is the .bib
    #    type canonicalized to the table's spelling when it matches (so the offered
    #    default is the citekey-stable form), else the .bib type verbatim, else
    #    "document". "?" lists; a number selects; an unknown value is confirmed.
    table = item_types.load_item_types(config_dir, out)
    if bib["item_type"]:
        canon = table.find_fold(bib["item_type"])
        type_default = canon if canon is not None else bib["item_type"]
    else:
        type_default = "document"
    item_type = item_types.choose_item_type(table, ask, out, type_default)

    # 4) Title (defaults to the .bib title, else the source file name).
    title = ask("Title", bib["title"] or default_title)

    # 5) Short title (defaults to the .bib shorttitle, else the title slug). A
    #    trailing '*' names the card from the short title instead of the title.
    default_short = bib["short_title"] or sanitize.sanitize_base(title)
    short_input = ask("Short title", default_short)
    short_title, name_from_card = sanitize.parse_short_title(short_input)

    # 6) Version (defaults to the .bib version, else 1).
    version = ask("Version", bib["version"] or "1")

    # 7) Authors: "Last:First", comma-separated (defaults from the .bib author).
    authors = entry_mod.parse_author_list(
        ask("Authors (Last:First, comma-separated)", bib["authors"] or ""))

    # 8) Date (defaults to the .bib date, else today, DD/MM/YYYY).
    y, m, d = dates.today()
    date = ask("Date (DD/MM/YYYY)", bib["date"] or dates.format_dmy(y, m, d))

    # 9) Tags, comma-separated (defaults from the .bib keywords).
    tags = entry_mod.parse_tag_list(ask("Tags (comma-separated)", bib["tags"] or ""))

    # 10) Description (defaults from the .bib abstract, else note).
    description = ask("Description", bib["description"] or "")

    # 11) Reference (default depends on the item type; citekey computed here too).
    yyyymmdd = dates.compact_dmy(date)
    citekey = citekey_mod.build(item_type, authors, yyyymmdd)
    default_ref = reference_mod.default_reference(item_type, short_title, authors, yyyymmdd)
    reference = ask("Reference", default_ref)

    # Resolve the card path first (where the user may cancel) so nothing is copied
    # for an abandoned entry. The card is named from the short title when flagged,
    # else from the title; either way slugified.
    name_source = short_title if (name_from_card and short_title) else title
    card_base = sanitize.sanitize_base(name_source)
    html_dir = config.html_storage_path.rstrip("\\/")
    try:
        os.makedirs(html_dir, exist_ok=True)
    except OSError as err:
        out("hib: cannot create the html folder (%s)." % err)
        return 1
    out_path = resolve_card_path(html_dir, card_base, ask, out)
    if out_path is None:
        out("")
        out("Cancelled - no file written.")
        return 0

    # Copy the source into a fresh uniquely named folder under the storage path,
    # using a simplified ASCII copy name (the original is left untouched).
    storage_root = config.file_storage_path.rstrip("\\/")
    try:
        folder = make_random_folder(storage_root)
    except OSError as err:
        out("hib: cannot create the storage folder (%s)." % err)
        return 1
    copy_name = sanitize.sanitize_filename(source_path)
    local_path = os.path.join(folder, copy_name)
    try:
        shutil.copyfile(source_path, local_path)
    except (OSError, shutil.SameFileError) as err:
        out("hib: failed to copy the source file (%s)." % err)
        return 1

    # Local PDF path (same folder, ".pdf" stem). Always recorded in the JSON.
    pdf_path = os.path.join(folder, sanitize.strip_extension(copy_name) + ".pdf")
    pdfgen.generate_pdf(config, copy_name, local_path, folder, pdf_path, out)
    pdf_exists = os.path.exists(pdf_path)

    e = entry_mod.Entry(
        title=title, item_type=item_type, authors=authors, date=date,
        tags=tags, description=description, version=version,
        short_title=short_title, reference=reference, citekey=citekey,
        local_path=local_path,
        remote_path=source_path if keep_remote else None,
        pdf_path=pdf_path if pdf_exists else None,
    )

    try:
        _write_text_file(out_path, html_mod.render_entry(e))
    except OSError as err:
        out("hib: failed to write the card '%s' (%s)." % (out_path, err))
        return 1

    try:
        json_path = _write_entry_metadata(config, e, citekey, folder, local_path, pdf_path, out_path)
    except OSError as err:
        out("hib: card written (%s) but metadata failed (%s)." % (out_path, err))
        return 1

    out("")
    out("Stored copy:    %s" % local_path)
    out("Wrote card:     %s" % out_path)
    out("Wrote metadata: %s" % json_path)
    # The JSON is named after the reference. A numbered name means that reference
    # is already taken: harmless (nothing is overwritten, and hib finds entries by
    # reading the files, not by their names) but worth saying, since the reference
    # is meant to identify this entry and now no longer does so on its own.
    if sanitize.strip_extension(sanitize.base_name(json_path)) != naming.json_base(e.reference, citekey):
        out("  Note: the reference '%s' is already used by another entry, "
            "so the file was numbered. `hib update <citekey>` cannot change a "
            "reference; re-add the entry if you need a distinct one." % e.reference)
    return 0
