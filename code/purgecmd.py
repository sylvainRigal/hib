"""The `purge` flow.

Move to the trash every card (.html in the html dir) and storage folder (subdir of
the file dir) referenced by NO json -- the orphans left by manual edits, crashes,
or legacy output. The json directory is the source of truth and is NEVER touched.
Shows a preview, then asks to confirm (default NO); `-n`/`--dry-run` only lists.
Orphans go into a single `<trash>\\purge_<yyyymmdd>\\` session folder.

Safety rules: orphan detection compares BASENAMES (immune to
how a JSON's path prefix is spelled); ANY unreadable/unparseable JSON ABORTS the
purge (a skipped json would make its live card/folder look orphaned); and the
trash/json/html directories are never moved even if nested under the file dir.
"""
import os
import stat
import sys

import sanitize
import dates
import locate
import model
import trash as trash_mod


def _is_reparse(full):
    """True when `full` is a reparse point (a Windows junction/symlink or a POSIX
    symlink) or cannot be stat'd. A reparse point is classified as a link (tested
    BEFORE the directory check, so a junction counts as a link, not a dir) and the
    purge loops skip anything that is not exactly a regular file / plain directory.
    os.path.isfile/isdir would FOLLOW the link, so we gate on lstat to match."""
    try:
        st = os.lstat(full)
    except OSError:
        return True                 # cannot stat -> never a purge candidate
    if stat.S_ISLNK(st.st_mode):    # POSIX symlink
        return True
    return bool(getattr(st, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _ascii_lower(s):
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


def _contains_name_fold(names, name):
    """True when `name` matches an entry of `names` case-insensitively (ASCII fold).
    Basenames are ASCII slugs/hex, so it is exact."""
    nl = _ascii_lower(name)
    return any(_ascii_lower(p) == nl for p in names)


def _touches_dir(candidate, target):
    """True when `candidate` IS `target`, lies inside it, or contains it -- so a
    purge of the file dir never moves the trash/json/html dirs a user could nest
    under it."""
    nc = locate.normalize_path(candidate)
    nt = locate.normalize_path(target)
    if nc == nt:
        return True
    if locate.is_within(target, candidate):     # candidate under target
        return True
    if locate.is_within(candidate, target):     # target under candidate
        return True
    return False


def run_purge(config, args):
    """Run purge. Prompts on stdout; reads stdin. Returns an exit code (0 success/
    abort/nothing-to-do, 1 on an abort-guard or hard failure)."""

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

    dry_run = any(a in ("-n", "--dry-run") for a in args)

    json_dir = config.json_storage_path.rstrip("\\/")
    html_dir = config.html_storage_path.rstrip("\\/")
    file_dir = config.file_storage_path.rstrip("\\/")
    troot = trash_mod.trash_root(config)

    # 1) Build the "live" BASENAME sets from every json. A json that fails to read
    # or parse is COUNTED as unreadable: skipping it would make its real, live
    # card/folder look orphaned, so any failure aborts the purge.
    live_html = []
    live_folder = []
    unreadable = []
    try:
        json_names = sorted(os.listdir(json_dir))
    except OSError as e:
        out("hib: cannot read the json directory '%s' (%s); purge aborted." % (json_dir, e))
        return 1
    for name in json_names:
        if not name.endswith(".json"):
            continue
        full = os.path.join(json_dir, name)
        # Gate on entry kind (regular files only): skip a directory or a
        # reparse point named "*.json" so it is not (mis)read as an unreadable
        # file -- which would otherwise abort the whole purge.
        if _is_reparse(full) or not os.path.isfile(full):
            continue
        try:
            with open(full, "rb") as f:
                md = model.parse(f.read().decode("utf-8"))
        except Exception:               # OSError / decode / json / not-an-object
            unreadable.append(full)
            continue
        if md.html_path:
            live_html.append(sanitize.base_name(md.html_path))
        if md.local_folder_path:
            live_folder.append(sanitize.base_name(md.local_folder_path))

    if unreadable:
        out("hib: %d JSON file(s) could not be read/parsed; purge aborted so a live "
            "entry is not mistaken for an orphan:" % len(unreadable))
        for p in unreadable:
            out("  %s" % p)
        out("Fix or remove those JSON files, then re-run.")
        return 1

    # 2) Orphan cards: .html files in the html dir whose basename is in no json.
    orphan_cards = []
    try:
        html_names = sorted(os.listdir(html_dir))
    except OSError:
        html_names = []
    for name in html_names:
        full = os.path.join(html_dir, name)
        if not name.endswith(".html") or _is_reparse(full) or not os.path.isfile(full):
            continue
        if not _contains_name_fold(live_html, name):
            orphan_cards.append(full)

    # 3) Orphan folders: direct subdirs of the file dir whose leaf is in no json,
    # EXCLUDING the trash / json / html directories.
    orphan_folders = []
    try:
        file_names = sorted(os.listdir(file_dir))
    except OSError:
        file_names = []
    for name in file_names:
        full = os.path.join(file_dir, name)
        # Skip reparse points (a junction counts as a link, not a dir)
        # so a user-placed junction/symlink is never relocated as an "orphan".
        if _is_reparse(full) or not os.path.isdir(full):
            continue
        if _touches_dir(full, troot) or _touches_dir(full, json_dir) or _touches_dir(full, html_dir):
            continue
        if not _contains_name_fold(live_folder, name):
            orphan_folders.append(full)

    # Preview.
    out("hib - purge orphans (referenced by no JSON)")
    out("")
    if not orphan_cards and not orphan_folders:
        out("Nothing to purge - every card and folder is referenced by a JSON.")
        return 0
    out("Orphan cards (%d):" % len(orphan_cards))
    for c in orphan_cards:
        out("  [card]   %s" % c)
    out("Orphan folders (%d):" % len(orphan_folders))
    for f in orphan_folders:
        out("  [folder] %s" % f)

    if dry_run:
        out("")
        out("(dry run: nothing was moved.)")
        return 0

    out("")
    out("-> into: %s\\purge_<yyyymmdd>\\" % troot)
    ans = ask("\nMove these orphans to the trash? (y/N)", "n")
    if not (ans and ans[0].lower() == "y"):
        out("")
        out("Aborted - nothing was moved.")
        return 0

    # One session folder for the whole run: <trash>\purge_<yyyymmdd>[_N].
    y, mo, d = dates.today()
    session_leaf = "purge_%s" % dates.compact_ymd(y, mo, d)
    try:
        session = trash_mod.free_trash_dest(troot, session_leaf)
    except OSError as e:
        out("hib: could not allocate a purge folder under '%s' (%s); nothing moved." % (troot, e))
        return 1
    try:
        os.makedirs(session, exist_ok=True)
    except OSError as e:
        out("hib: could not create the purge folder '%s' (%s); nothing moved." % (session, e))
        return 1
    out("")

    for c in orphan_cards:
        trash_mod.move_file_into(c, session, "card", out)
    for f in orphan_folders:
        try:
            dest = trash_mod.free_trash_dest(session, sanitize.base_name(f))
        except OSError:
            out("  WARNING: could not place folder %s in the purge dir; left in place." % f)
            continue
        if trash_mod.move_dir_to(f, dest, out):
            out("  moved folder: %s" % dest)

    out("")
    out("Done. Orphans moved to %s" % session)
    return 0
