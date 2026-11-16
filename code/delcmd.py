"""The `delete` flow.

Locate the entry, show a recap, ask for confirmation (default NO), then MOVE the
card, the whole storage folder and the JSON into `<trash>\\<folder name>\\` instead
of erasing them. Best-effort / never fatal: every target comes from the matched
JSON (never the arg), nothing is removed unless its move succeeded, the storage
folder is moved only when it is a strict descendant of the storage root (guard
against a tampered/relative JSON), and a missing target is a note.
"""
import os
import sys

import sanitize
import locate
import selector as sel
import trash as trash_mod


def run_delete(config, args):
    """Run the interactive delete. Prompts on stdout; reads stdin. Returns an exit
    code (0 success/abort, 1 on a selector miss or a hard failure)."""

    def out(s):
        sys.stdout.write(s + "\n")

    def ask(label, default):
        if default:
            sys.stdout.write("%s [%s]: " % (label, default))
        else:
            sys.stdout.write("%s: " % label)
        sys.stdout.flush()
        line = sys.stdin.readline()
        if line == "":
            return default
        t = line.strip(" \t\r\n")
        return t if t else default

    def prompt(text):
        sys.stdout.write(text)
        sys.stdout.flush()
        return sys.stdin.readline()

    parsed = sel.parse_selector(args, out)
    if parsed is None:
        return 1
    kind, value = parsed
    found = sel.resolve_entry(config, kind, value, prompt, out)
    if found is None:
        out("Nothing was moved.")
        return 1
    m = found.meta

    troot = trash_mod.trash_root(config)
    # The trash subfolder is named after the storage folder being removed; fall
    # back to the citekey, the card base, then a constant, so it is always set. A
    # "."/".." leaf (tampered path) is treated as no name so the fallback engages.
    leaf = sanitize.base_name(m.local_folder_path.rstrip("\\/"))
    if leaf in (".", ".."):
        leaf = ""
    if not leaf:
        leaf = m.citekey
    if not leaf:
        leaf = sanitize.strip_extension(sanitize.base_name(m.html_path))
    if not leaf:
        leaf = "entry"

    try:
        dest = trash_mod.free_trash_dest(troot, leaf)
    except OSError as e:
        out("hib: could not allocate a trash folder under '%s' (%s); nothing moved." % (troot, e))
        return 1

    out("hib - delete an entry")
    out("")
    out("  Title:  %s" % m.title)
    out("  Type:   %s" % m.item_type)
    out("")
    out("The following will be MOVED to the trash (not erased):")
    out("  [card]   %s" % m.html_path)
    if m.local_folder_path:
        out("  [folder] %s" % m.local_folder_path)
    else:
        out("  [folder] (none recorded)")
    out("  [json]   %s" % found.json_path)
    out("  -> into: %s" % dest)

    ans = ask("\nMove this entry to the trash? (y/N)", "n")
    if not (ans and ans[0].lower() == "y"):
        out("")
        out("Aborted - nothing was moved.")
        return 0

    out("")
    try:
        os.makedirs(troot, exist_ok=True)
    except OSError as e:
        out("hib: could not create the trash folder '%s' (%s); nothing moved." % (troot, e))
        return 1

    # 1) The storage folder (with all its files). Only ever move a strict
    # descendant of the configured storage root, never cwd or a system dir. A
    # successful move CREATES `dest`.
    storage_root = config.file_storage_path.rstrip("\\/")
    dest_exists = False
    if not m.local_folder_path:
        out("  note: no local folder recorded.")
    elif not locate.is_within(storage_root, m.local_folder_path):
        out("  WARNING: folder %s is outside the storage root; left in place." % m.local_folder_path)
    elif trash_mod.move_dir_to(m.local_folder_path, dest, out):
        out("  moved folder: %s" % dest)
        dest_exists = True

    # The card and JSON go into the same subfolder; make sure it exists even when
    # no folder was moved into it.
    if not dest_exists:
        try:
            os.makedirs(dest, exist_ok=True)
        except OSError as e:
            out("hib: could not create the trash subfolder '%s' (%s); card/json left in place." % (dest, e))
            return 1

    # 2) Card, then 3) JSON, into the trash subfolder.
    trash_mod.move_file_into(m.html_path, dest, "card", out)
    trash_mod.move_file_into(found.json_path, dest, "json", out)

    out("")
    out("Done. Entry moved to %s" % dest)
    return 0
