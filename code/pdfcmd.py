"""The `pdf` flow: generate an entry's PDF, plus an attach mode.

`hib pdf <citekey>` (re)generates the PDF for an entry's stored copy, then
refreshes its card so the "Local PDF" button reflects the file on disk. The JSON
is NOT rewritten (the pdf path was already recorded; the button is a render-time
function of the file's existence), so this is idempotent.

`hib pdf <citekey> <file.pdf>` instead ATTACHES a PDF that already exists (a scan,
a publisher's PDF, a conversion done by hand): the file is COPIED into the entry's
storage folder under the name hib reserves for it, so the entry stays
self-contained -- nothing points at the PDF's original location, which stays
untouched. The JSON is rewritten only when it had no pdfLocalPath recorded; the
card is always re-rendered, so the "Local PDF" button appears.

Defense-in-depth: unlike `add`, these paths come from the entry's JSON (read off
disk) and are handed to the converter (which drives Word) or written to, so a
hand-edited/foreign JSON is refused unless every stored path is a strict descendant
of the storage root using only the sanitized alphabet (locate.stored_path_is_safe).
"""
import os
import shutil
import sys

import sanitize
import locate
import selector as sel
import entry as entry_mod
import html as html_mod
import metadata as metadata_mod
import pdfgen
import addcmd


_STATUS = {
    "generated": "generated",
    "already_pdf": "the stored copy already is a PDF",
    "no_converter": "skipped (docx2pdf is not installed -- pip install docx2pdf)",
    "unsupported": "skipped (not an Office or PDF file)",
    "failed": "not generated (see the warning above)",
}


def _entry_for_card(m, pdf_exists):
    """The Entry the card is rendered from: every field straight out of the JSON,
    with the PDF button gated on the file existing on disk -- exactly as add and
    update do, so the card stays byte-identical to what they would write."""
    return entry_mod.Entry(
        title=m.title, item_type=m.item_type, authors=m.authors, date=m.date,
        tags=m.tags, description=m.description, version=m.version,
        short_title=m.short_title, reference=m.reference, citekey=m.citekey,
        local_path=m.local_file_path, remote_path=m.remote_path,
        pdf_path=m.pdf_local_path if pdf_exists else None)


def _attach_arg(rest):
    """The PDF path given on the command line, or None when there is none. Run
    through the usual source-path cleanup (surrounding quotes stripped, and a
    trailing '*' -- meaningless here, but a habit from `add`)."""
    if not rest or not rest[0]:
        return None
    path, _ = sanitize.parse_source_path(rest[0])
    return path or None


def _pdf_destination(m):
    """Where the entry's local PDF belongs. The recorded pdfLocalPath when there is
    one (add always records it, whether or not the file was produced); otherwise
    the name add would have reserved -- the stored copy's stem, '.pdf' -- inside the
    storage folder, falling back to the reference for a JSON with no stored copy."""
    folder = m.local_folder_path
    if m.pdf_local_path:
        return m.pdf_local_path
    if m.local_file_path:
        stem = sanitize.strip_extension(sanitize.base_name(m.local_file_path))
    else:
        stem = sanitize.sanitize_base(m.reference or m.citekey or "entry")
    return os.path.join(folder, stem + ".pdf")


def _attach_pdf(config, found, source, out, prompt):
    """`hib pdf <ctk> <file.pdf>`: copy an existing PDF into the entry's storage
    folder as its local PDF, then refresh the card. Returns an exit code (0 on
    success or a graceful cancel, 1 on a bad source / unsafe stored paths / a
    copy or write failure)."""
    m = found.meta

    out("hib - attach an existing PDF")
    out("")
    out("  Title:   %s" % m.title)
    out("  citekey: %s" % m.citekey)
    out("  Source:  %s" % source)
    out("")

    if not os.path.isfile(source):
        out("hib: no such file: %s" % source)
        return 1
    if sanitize.extension(sanitize.base_name(source)).lower() != ".pdf":
        out("hib: '%s' is not a .pdf; the local PDF button and `hib opdf` expect "
            "one. Nothing changed." % sanitize.base_name(source))
        return 1
    if not m.local_folder_path:
        out("hib: this entry has no local folder recorded; nowhere to put the PDF.")
        return 1

    dest = _pdf_destination(m)
    storage_root = config.file_storage_path.rstrip("\\/")
    if not (locate.stored_path_is_safe(storage_root, m.local_folder_path)
            and locate.stored_path_is_safe(storage_root, dest)):
        out("hib: this entry's stored paths are outside the storage root or contain "
            "unsafe characters; refusing to write a PDF there.")
        return 1

    if locate.same_path(source, dest):
        out("  Copy:    %s  (the source already IS the entry's PDF)" % dest)
    else:
        # Overwriting is the destructive part of this command -- a generated PDF is
        # reproducible, a previously attached one is not -- so it is always asked.
        if os.path.exists(dest):
            out("  A PDF is already attached at %s." % dest)
            answer = prompt("  Replace it? (y/n): ")
            if (answer or "").strip(" \t\r\n")[:1].lower() != "y":
                out("")
                out("Cancelled - nothing changed.")
                return 0
        try:
            os.makedirs(m.local_folder_path, exist_ok=True)
            shutil.copyfile(source, dest)
        except (OSError, shutil.SameFileError) as err:
            out("hib: failed to copy the PDF (%s). Nothing changed." % err)
            return 1
        out("  Copy:    %s" % dest)

    # The JSON only needs writing when it did not already point at this PDF (an
    # entry added by hib always does, so the common case leaves it untouched).
    if not (m.pdf_local_path and locate.same_path(m.pdf_local_path, dest)):
        m.pdf_local_path = dest
        meta = metadata_mod.Metadata(
            citekey=m.citekey, entry=_entry_for_card(m, True),
            local_file_path=m.local_file_path, local_folder_path=m.local_folder_path,
            html_path=m.html_path, pdf_local_path=dest, remote_path=m.remote_path)
        try:
            addcmd._write_text_file(found.json_path, metadata_mod.render(meta))
        except OSError as err:
            out("hib: the PDF is in place but writing the JSON '%s' failed (%s)."
                % (found.json_path, err))
            return 1
        out("  JSON:    %s  (pdfLocalPath recorded)" % found.json_path)

    if not m.html_path:
        out("  Card:    (none recorded)")
        return 0
    try:
        addcmd._write_text_file(m.html_path,
                                html_mod.render_entry(_entry_for_card(m, True)))
    except OSError as err:
        out("  Card:    %s  FAILED (%s)" % (m.html_path, err))
        out("hib: the PDF is attached but the card has no button for it yet; "
            "re-render it with `hib update -html`.")
        return 1
    out("  Card:    %s  (refreshed)" % m.html_path)
    return 0


def run_pdf(config, args):
    """Run pdf. Prompts on stdout; reads stdin (for a pick list, and for the
    replace confirmation of the attach mode). With a <file.pdf> after the selector,
    attaches that PDF instead of generating one. Returns an exit code (0 success,
    1 on a selector miss / missing copy / unsafe paths / card-write failure)."""

    def out(s):
        sys.stdout.write(s + "\n")

    def prompt(text):
        sys.stdout.write(text)
        sys.stdout.flush()
        return sys.stdin.readline()

    parsed = sel.parse_selector(args, out)
    if parsed is None:
        return 1
    kind, value = parsed
    # parse_selector reads 1 arg (a citekey/reference) or 2 (-citekey/-html/-ref
    # <value>); whatever follows is an existing PDF to attach.
    consumed = 2 if args[0].startswith("-") else 1
    found = sel.resolve_entry(config, kind, value, prompt, out)
    if found is None:
        return 1
    m = found.meta

    source = _attach_arg(args[consumed:])
    if source is not None:
        return _attach_pdf(config, found, source, out, prompt)

    out("hib - generate PDF")
    out("")
    out("  Title:   %s" % m.title)
    out("  citekey: %s" % m.citekey)
    out("")

    if not m.local_file_path:
        out("hib: this entry has no stored local file; cannot generate a PDF.")
        return 1
    if not os.path.exists(m.local_file_path):
        out("hib: stored copy not found at %s; cannot generate a PDF." % m.local_file_path)
        return 1

    storage_root = config.file_storage_path.rstrip("\\/")
    if not (locate.stored_path_is_safe(storage_root, m.local_folder_path)
            and locate.stored_path_is_safe(storage_root, m.local_file_path)
            and locate.stored_path_is_safe(storage_root, m.pdf_local_path)):
        out("hib: this entry's stored paths are outside the storage root or contain "
            "unsafe characters; refusing to run the converter.")
        return 1

    res = pdfgen.generate_pdf(config, sanitize.base_name(m.local_file_path),
                              m.local_file_path, m.local_folder_path, m.pdf_local_path, out)
    pdf_exists = os.path.exists(m.pdf_local_path)

    # Refresh the card in place (no rename, no JSON change) so the button state
    # reflects the PDF on disk -- byte-identical to what add/update would render.
    if m.html_path:
        try:
            addcmd._write_text_file(
                m.html_path, html_mod.render_entry(_entry_for_card(m, pdf_exists)))
        except OSError as err:
            out("hib: PDF handled but refreshing the card failed for '%s' (%s)." % (m.html_path, err))
            return 1

    out("")
    out("  PDF:  %s  [%s]" % (m.pdf_local_path, _STATUS.get(res, res)))
    out("  Card: %s  (refreshed)" % m.html_path)
    return 0
