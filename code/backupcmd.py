"""The `backup` flow: an incremental, additive mirror of the archive.

    hib backup [<target-dir>] [-n]
    hib backup --purge old [<target-dir>] [-n]

The target (command line, else `[backup] target` in the config) receives the
three storage dirs by name:

    <target>\\json\\<name>.json     every item's JSON
    <target>\\html\\<card>.html     its card
    <target>\\file\\<folder>\\...   its whole storage folder, recursively

An ITEM is a readable JSON of the json dir; only what a JSON references is
backed up (orphan cards/folders are left out, and counted). An item tagged
`nobackup` (any case) is skipped entirely: no JSON, no card, no folder.

A file is copied only when it is missing in the target or differs (size, or
mtime beyond a 2 s tolerance for FAT/exFAT; JSONs and cards are also compared
byte for byte, see _unchanged). shutil.copy2 keeps the mtime. The backup NEVER
deletes anything in the target.

After copying, what the target holds that is NOT a live item of this run gets
the tag `old`: a target JSON whose name was not backed up in this run (item
deleted, now tagged nobackup, or JSON renamed), its card, and any target card
referenced by no target JSON. A card that belongs to a live item of this run is
never touched, even when an old JSON points at the same card name. The tag is
idempotent, and an item that comes back loses it on the next run, because its
archive JSON/card then differ from the tagged copies and are copied over them.

Safety, as in purge: reparse points are skipped, the trash/json/html dirs are
never descended into when nested under the file dir, card/folder paths are only
taken inside their storage root, and a target inside a storage dir (or the
reverse) is refused. An unreadable JSON is reported and skipped (its old backup
copy is left untouched); the run goes on and exits 1 at the end.

`--purge old` (no backup is run) is the one way anything is deleted in the
target: every backup JSON tagged old, with its card and storage folder unless a
backup JSON NOT tagged old names the same card/folder, plus every card tagged
old that no such JSON names. Preview, then confirmation (default NO); -n lists
only. Any unreadable backup JSON aborts it (nothing deleted). See run_purge_old.
"""
import collections
import json
import os
import re
import shutil
import stat
import sys

import sanitize
import locate
import model
import metadata as metadata_mod
import entry as entry_mod
import addcmd
import trash as trash_mod
from purgecmd import _is_reparse, _touches_dir, _ascii_lower

NOBACKUP_TAG = "nobackup"
OLD_TAG = "old"
MTIME_TOLERANCE = 2.0           # seconds: FAT/exFAT store mtimes at 2 s resolution

# Files compared byte for byte on top of size+mtime (they are small, and a
# tagged-old copy must never pass for the archive version it came from).
_CONTENT_EXTS = (".json", ".html")

USAGE = ("usage: hib backup [<target-dir>] [-n]\n"
         "       hib backup --purge old [<target-dir>] [-n]")


def has_tag(tags, name):
    """True when `name` is one of `tags` (trimmed, case-insensitive exact match)."""
    n = name.strip().lower()
    return any(isinstance(t, str) and t.strip().lower() == n for t in tags)


def _key(name):
    """Case-insensitive key for a basename (Windows file names)."""
    return _ascii_lower(name)


def _norm_root(p):
    """Absolute form of a root dir. abspath already drops a trailing separator
    but keeps the one of a drive root: 'E:\\' stays 'E:\\' (stripping it first
    would give 'E:', i.e. the CURRENT directory on E:)."""
    return os.path.abspath(p) if p else p


def _safe_base(path):
    """The basename of a recorded card/folder path, or None when it cannot be
    used as a plain name inside a root: empty, '.', '..', or carrying a ':'
    (a drive-relative 'C:card.html' would make os.path.join drop the root; a
    'card.html:x' would name an alternate data stream)."""
    base = sanitize.base_name(path.rstrip("\\/"))
    if base in ("", ".", "..") or ":" in base:
        return None
    return base


def _is_link(full):
    """True when `full` is a reparse point (junction/symlink). Unlike
    purgecmd._is_reparse, a path that cannot be lstat'd RAISES OSError: the
    backup reports it as a failure instead of skipping it silently as a link."""
    st = os.lstat(full)
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _is_link_if_exists(full):
    """_is_link, False when `full` does not exist (other lstat errors raise)."""
    try:
        return _is_link(full)
    except FileNotFoundError:
        return False


def _file_id(p):
    try:
        st = os.stat(p)
    except OSError:
        return None
    if not st.st_ino:           # no stable file id on this file system
        return None
    return (st.st_dev, st.st_ino)


def _ancestors(p):
    out = []
    while True:
        out.append(p)
        parent = os.path.dirname(p)
        if not parent or parent == p:
            return out
        p = parent


def _final_path(p):
    """Windows only: the fully resolved path of the existing `p`, as the OS sees
    it (GetFinalPathNameByHandleW), every junction / symlink / 8.3 name / subst
    drive resolved. None when not on Windows or on any failure. Needed because
    os.path.realpath does NOT resolve junctions before Python 3.8 on Windows."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = k32.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                           ctypes.c_void_p]
        create.restype = ctypes.c_void_p
        final = k32.GetFinalPathNameByHandleW
        final.argtypes = [ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        final.restype = wintypes.DWORD
        close = k32.CloseHandle
        close.argtypes = [ctypes.c_void_p]
        close.restype = wintypes.BOOL
        # access 0 (attributes only), share read|write|delete, OPEN_EXISTING,
        # FILE_FLAG_BACKUP_SEMANTICS (needed to open a directory).
        h = create(p, 0, 7, None, 3, 0x02000000, None)
        if h is None or h == ctypes.c_void_p(-1).value:
            return None
        try:
            size = 1024
            while True:
                buf = ctypes.create_unicode_buffer(size)
                n = final(h, buf, size, 0)
                if n == 0:
                    return None
                if n < size:
                    break
                size = n + 1
        finally:
            close(h)
        r = buf.value
    except Exception:
        return None
    if r.startswith("\\\\?\\UNC\\"):
        return "\\\\" + r[8:]
    if r.startswith("\\\\?\\"):
        return r[4:]
    return r


def _resolved(p):
    """`p` with every link resolved, also for a path that does not exist yet
    (its deepest existing ancestor is resolved, the rest appended): the OS view
    via _final_path on Windows, else os.path.realpath."""
    p = os.path.abspath(p)
    cur, tail = p, []
    while not os.path.lexists(cur):
        parent = os.path.dirname(cur)
        if not parent or parent == cur:
            break
        tail.insert(0, os.path.basename(cur))
        cur = parent
    fp = _final_path(cur)
    if fp is None:
        return os.path.realpath(p)
    return os.path.join(fp, *tail) if tail else fp


def _overlaps(target, d):
    """True when `target` IS `d`, lies inside it or contains it -- by path
    string (as purge) AND on disk: resolved paths (realpath, and the OS final
    path, which also resolves junctions on Python < 3.8), and the file identity
    (st_dev, st_ino) of every ancestor, so a junction, symlink, 8.3 short name
    or subst drive leading back into the archive is caught too."""
    if _touches_dir(target, d):
        return True
    for resolve in (os.path.realpath, _resolved):
        try:
            if _touches_dir(resolve(target), resolve(d)):
                return True
        except (OSError, ValueError):
            pass
    tid, did = _file_id(target), _file_id(d)
    if did is not None and any(_file_id(a) == did for a in _ancestors(target)):
        return True
    if tid is not None and any(_file_id(a) == tid for a in _ancestors(d)):
        return True
    return False


def _make_writable(p):
    """Clear the read-only attribute of `p` (shutil.copy2 copies it from the
    archive; a read-only backup copy could never be updated or tagged).
    Returns True when it was read-only."""
    st = os.stat(p)
    if st.st_mode & stat.S_IWRITE:
        return False
    os.chmod(p, st.st_mode | stat.S_IWRITE)
    return True


_TMP_SUFFIX = ".~hib-backup-tmp"


def _replace_atomically(dst, fill):
    """Write `dst` through a temp file in the same folder and os.replace: an
    interruption never leaves a truncated backup copy (often the only copy left
    of a deleted item), and a hard link in the backup is never written through.
    `fill(tmp)` creates the temp file."""
    tmp = dst + _TMP_SUFFIX
    try:
        if os.path.lexists(tmp):
            _make_writable(tmp)
            os.remove(tmp)          # a leftover of ours from an interrupted run
        fill(tmp)
        if os.path.exists(dst):
            _make_writable(dst)
        os.replace(tmp, dst)
    except BaseException:
        try:
            if os.path.lexists(tmp):
                _make_writable(tmp)
                os.remove(tmp)
        except OSError:
            pass
        raise


def _write_text_atomically(path, text):
    """Rewrite an existing backup file (old tagging); keeps its read-only flag."""
    was_ro = _make_writable(path) if os.path.exists(path) else False

    def fill(tmp):
        addcmd._write_text_file(tmp, text)
    _replace_atomically(path, fill)
    if was_ro:
        os.chmod(path, os.stat(path).st_mode & ~stat.S_IWRITE)


# --- file comparison / copy -------------------------------------------------

def _inside_or_same(p, d):
    """True when `p` IS `d` or lies inside it. (A folder that merely CONTAINS a
    guarded dir is still copied; _sync_tree skips that sub-folder.) Only valid
    with guard dirs that do not contain the file dir (see _guards)."""
    return locate.same_path(p, d) or locate.is_within(d, p)


def _guards(dirs, file_dir):
    """The guard dirs that matter under the file dir: one that IS the file dir
    or CONTAINS it (html = C:\\hib, file = C:\\hib\\f) contains every item
    folder by construction and must not make them all look 'guarded'."""
    return tuple(g for g in dirs
                 if not (locate.same_path(g, file_dir) or locate.is_within(g, file_dir)))


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _unchanged(src, dst):
    """True when `dst` already mirrors `src`: same size, mtime within the 2 s
    tolerance and, for a JSON/card, the same bytes. The byte check makes the
    restore case exact: a copy we tagged `old` can never look 'unchanged' next
    to the archive version, whatever its size/mtime turned out to be."""
    try:
        ss = os.stat(src)
        ds = os.stat(dst)
    except OSError:
        return False
    if ss.st_size != ds.st_size:
        return False
    if abs(ss.st_mtime - ds.st_mtime) > MTIME_TOLERANCE:
        return False
    if os.path.splitext(src)[1].lower() in _CONTENT_EXTS:
        try:
            return _read_bytes(src) == _read_bytes(dst)
        except OSError:
            return False
    return True


class _Stats(object):
    def __init__(self):
        self.items = 0
        self.nobackup = 0
        self.copied = 0
        self.unchanged = 0
        self.tagged_old_json = 0
        self.tagged_old_card = 0
        self.already_old = 0
        self.failures = 0
        self.notes = 0


def _sync_file(src, dst, dry, stats, out, label):
    """Copy `src` to `dst` unless unchanged. Returns True on success/skip."""
    try:
        dst_link = _is_link_if_exists(dst)
    except OSError as e:
        out("    FAIL copy %s  %s (cannot check the backup copy: %s)" % (label, src, e))
        stats.failures += 1
        return False
    if dst_link:
        out("    FAIL copy %s  %s (%s is a link / junction in the backup; not written)"
            % (label, src, dst))
        stats.failures += 1
        return False
    if os.path.isdir(dst):
        out("    FAIL copy %s  %s (a folder %s is in the backup; the backup never "
            "deletes it)" % (label, src, dst))
        stats.failures += 1
        return False
    if os.path.exists(dst) and _unchanged(src, dst):
        stats.unchanged += 1
        return True
    if dry:
        out("    would copy %s  %s" % (label, dst))
        stats.copied += 1
        return True
    try:
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        _replace_atomically(dst, lambda tmp: shutil.copy2(src, tmp))
    except (OSError, shutil.Error) as e:
        out("    FAIL copy %s  %s (%s)" % (label, src, e))
        stats.failures += 1
        return False
    out("    copied %s  %s" % (label, dst))
    stats.copied += 1
    return True


def _sync_tree(src_dir, dst_dir, guard_dirs, dry, stats, out):
    """Mirror `src_dir` into `dst_dir` recursively (files + sub-folders), skipping
    reparse points and any of `guard_dirs` (trash/json/html nested under the file
    dir). Never deletes anything under `dst_dir`."""
    try:
        names = sorted(os.listdir(src_dir))
    except OSError as e:
        out("    FAIL list  %s (%s)" % (src_dir, e))
        stats.failures += 1
        return
    try:
        dst_link = _is_link_if_exists(dst_dir)
    except OSError as e:
        out("    FAIL check %s (%s)" % (dst_dir, e))
        stats.failures += 1
        return
    if dst_link:
        out("    FAIL  %s is a link / junction in the backup; %s not copied" % (dst_dir, src_dir))
        stats.failures += 1
        return
    if os.path.lexists(dst_dir) and not os.path.isdir(dst_dir):
        out("    FAIL  %s is a file in the backup; folder %s not copied (the backup "
            "never deletes)" % (dst_dir, src_dir))
        stats.failures += 1
        return
    if not dry and not os.path.isdir(dst_dir):
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as e:
            out("    FAIL mkdir %s (%s)" % (dst_dir, e))
            stats.failures += 1
            return
    for name in names:
        full = os.path.join(src_dir, name)
        try:
            link = _is_link(full)
        except OSError as e:
            out("    FAIL  %s  (cannot read: %s)" % (full, e))
            stats.failures += 1
            continue
        if link:
            out("    skip  %s  (link / junction)" % full)
            stats.notes += 1
            continue
        if os.path.isdir(full):
            if any(_touches_dir(full, g) for g in guard_dirs):
                out("    skip  %s  (a hib storage/trash folder)" % full)
                stats.notes += 1
                continue
            _sync_tree(full, os.path.join(dst_dir, name), guard_dirs, dry, stats, out)
        elif os.path.isfile(full):
            _sync_file(full, os.path.join(dst_dir, name), dry, stats, out, "file")


# --- old tagging --------------------------------------------------------------

def _meta_from_parsed(m, tags):
    """A metadata.Metadata rebuilt from a model.parse entry, with `tags`."""
    e = entry_mod.Entry(
        title=m.title, item_type=m.item_type, authors=m.authors, date=m.date,
        tags=tags, description=m.description, version=m.version,
        short_title=m.short_title, reference=m.reference, citekey=m.citekey)
    return metadata_mod.Metadata(
        citekey=m.citekey, entry=e,
        local_file_path=m.local_file_path, local_folder_path=m.local_folder_path,
        html_path=m.html_path, pdf_local_path=m.pdf_local_path,
        remote_path=m.remote_path)


def tag_json_text_old(text):
    """Return `text` (a hib JSON) with the `old` tag added, or None when it is
    already tagged. Lossless: when the JSON is exactly what hib writes (the
    model.parse + metadata.render round-trip reproduces it byte for byte), it is
    re-rendered the canonical way with one more tag; otherwise (extra keys,
    hand-edited formatting...) it is edited at the JSON level, keeping every key
    and its order. Raises ValueError when it cannot be tagged."""
    m = model.parse(text)
    obj = json.loads(text, object_pairs_hook=collections.OrderedDict)
    raw_tags = obj.get("tags")
    if raw_tags is not None and not isinstance(raw_tags, list):
        raise ValueError('"tags" is not a list')
    if has_tag(m.tags, OLD_TAG):
        return None
    if metadata_mod.render(_meta_from_parsed(m, m.tags)) == text:
        return metadata_mod.render(_meta_from_parsed(m, m.tags + [OLD_TAG]))
    obj["tags"] = list(raw_tags or []) + [OLD_TAG]
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


_TAG_SPAN_OLD = re.compile(r'<span class="tag">\s*old\s*</span>', re.IGNORECASE)
_TAGS_BLOCK = re.compile(r"<strong>Tags:</strong>(.*?)</p>", re.DOTALL)
_KEYWORDS = re.compile(r'(<meta name="keywords" content=")([^"]*)(")')


def tag_card_text_old(text):
    """Return the card `text` with the `old` tag added in place, or None when it
    already carries it. The card is NOT re-rendered (its absolute links, PDF
    button... stay as they are): a `<span class="tag">old</span>` line is
    inserted at the end of the Tags block, and `old` is appended to the
    `<meta name="keywords">` list. Raises ValueError when the card has no Tags
    block (not a hib card)."""
    m = _TAGS_BLOCK.search(text)
    if m is None:
        raise ValueError("no Tags block in the card")
    changed = False
    if not _TAG_SPAN_OLD.search(m.group(1)):
        nl = "\r\n" if "\r\n" in text else "\n"
        close = m.end() - len("</p>")
        line_start = text.rfind("\n", m.start(), close) + 1
        if line_start > 0 and text[line_start:close].strip() == "":
            ins_at, ins = line_start, '    <span class="tag">old</span>' + nl
        else:
            ins_at, ins = close, '<span class="tag">old</span>'
        text = text[:ins_at] + ins + text[ins_at:]
        changed = True
    k = _KEYWORDS.search(text)
    if k is not None:
        words = [w.strip() for w in k.group(2).split(",") if w.strip()]
        if not has_tag(words, OLD_TAG):
            new = k.group(2) + (", old" if words else "old")
            text = text[:k.start(2)] + new + text[k.end(2):]
            changed = True
    return text if changed else None


def _listdir(d):
    try:
        return sorted(os.listdir(d))
    except OSError:
        return []


def _read_text(path):
    return _read_bytes(path).decode("utf-8", "surrogateescape")


def _tag_card_file(path, dry, stats, out):
    try:
        text = _read_text(path)
        new = tag_card_text_old(text)
    except (OSError, ValueError) as e:
        out("    note  card %s not tagged (%s)" % (path, e))
        stats.notes += 1
        return
    if new is None:
        stats.already_old += 1
        return
    if dry:
        out("    would tag old  card %s" % path)
        stats.tagged_old_card += 1
        return
    try:
        _write_text_atomically(path, new)
    except OSError as e:
        out("    FAIL tag old  card %s (%s)" % (path, e))
        stats.failures += 1
        return
    out("    tagged old  card %s" % path)
    stats.tagged_old_card += 1


def _tag_json_file(path, text, dry, stats, out):
    try:
        new = tag_json_text_old(text)
    except ValueError as e:
        out("    note  JSON %s not tagged (%s)" % (path, e))
        stats.notes += 1
        return
    if new is None:
        stats.already_old += 1
        return
    if dry:
        out("    would tag old  json %s" % path)
        stats.tagged_old_json += 1
        return
    try:
        _write_text_atomically(path, new)
    except OSError as e:
        out("    FAIL tag old  json %s (%s)" % (path, e))
        stats.failures += 1
        return
    out("    tagged old  json %s" % path)
    stats.tagged_old_json += 1


def _tag_old(t_json, t_html, live_json, live_cards, protected_json, dry, stats, out,
             live_json_cards=None):
    """Tag `old` every target JSON not live in this run, its card (unless that
    card is live), and every target card referenced by no target JSON. The
    backup copy of a JSON that is unreadable in the archive (`protected_json`)
    is left alone, and so is its card. `live_json_cards` (dry run): target
    JSON key -> card basename the archive JSON names; the dry run did not copy
    those JSONs, so their card reference is taken from the archive, exactly as
    the real run will see it after copying."""
    live_json_cards = live_json_cards or {}
    referenced = set()          # card keys named by ANY target JSON
    keep = set(live_cards)      # card keys never to touch
    cards_to_tag = []
    try:
        names = sorted(os.listdir(t_json))
    except OSError:
        names = []
    for name in names:
        full = os.path.join(t_json, name)
        if not name.endswith(".json"):
            continue
        k = _key(name)
        if k in live_json_cards:
            if live_json_cards[k]:
                referenced.add(_key(live_json_cards[k]))
            continue
        try:
            link = _is_link(full)
        except OSError as e:
            out("    FAIL  backup JSON %s cannot be read (%s)" % (full, e))
            stats.failures += 1
            continue
        if link or not os.path.isfile(full):
            continue
        try:
            text = _read_bytes(full).decode("utf-8")
            m = model.parse(text)
        except Exception:
            out("    note  backup JSON %s is unreadable; left as is" % full)
            stats.notes += 1
            continue
        card_base = (_safe_base(m.html_path) or "") if m.html_path else ""
        if card_base:
            referenced.add(_key(card_base))
        if k in live_json:
            continue
        if k in protected_json:
            if card_base:
                keep.add(_key(card_base))
            continue
        _tag_json_file(full, text, dry, stats, out)
        # Its card -- unless a live item of this run owns a card of that name
        # (JSON renamed, title kept: old and new JSON name the same card).
        if card_base:
            cards_to_tag.append(card_base)

    # Cards referenced by no target JSON at all (e.g. a renamed card).
    try:
        card_names = sorted(os.listdir(t_html))
    except OSError:
        card_names = []
    for name in card_names:
        if name.endswith(".html") and _key(name) not in referenced:
            cards_to_tag.append(name)

    seen = set()
    for base in cards_to_tag:
        k = _key(base)
        if k in seen or k in keep:
            continue
        seen.add(k)
        if _safe_base(base) != base:
            continue
        full = os.path.join(t_html, base)
        if not locate.is_within(t_html, full):
            continue
        try:
            link = _is_link_if_exists(full)
        except OSError as e:
            out("    FAIL  backup card %s cannot be read (%s)" % (full, e))
            stats.failures += 1
            continue
        if link or not os.path.isfile(full):
            continue
        _tag_card_file(full, dry, stats, out)


# --- entry point ----------------------------------------------------------------

def _parse_args(args):
    dry = False
    pos = []
    for a in args:
        if a in ("-n", "--dry-run"):
            dry = True
        elif a.startswith("-") and len(a) > 1:
            return None
        else:
            pos.append(a)
    if len(pos) > 1:
        return None
    return dry, (pos[0] if pos else None)


def _string_tags(text):
    """A hand-edited `"tags": "nobackup"` (a string, not a list): model.parse
    would split it into characters, so it is read here as one tag."""
    obj = json.loads(text)
    t = obj.get("tags") if isinstance(obj, dict) else None
    return [t] if isinstance(t, str) else []


def _path_state(p):
    """'missing', 'link', 'plain', or the OSError when `p` cannot be lstat'd
    for another reason (too long a path, access denied...)."""
    try:
        return "link" if _is_link(p) else "plain"
    except FileNotFoundError:
        return "missing"
    except OSError as e:
        return e


def _resolve_in_root(root, recorded):
    """The on-disk path of a recorded card/folder, confined to `root`: the
    recorded path when it lies inside `root`, else `<root>\\<its basename>` (the
    JSON was written under another drive/prefix -- purge matches by basename for
    the same reason). Returns (path or None, used_fallback)."""
    base = _safe_base(recorded)
    if base is None:
        return None, False
    if locate.is_within(root, recorded):
        return recorded, False
    return os.path.join(root, base), True


def _checked_target_dirs(config, target, out, purge):
    """The safety checks shared by the backup and `--purge old`: `target` (already
    normalized) must not overlap any storage/trash dir, must be a folder when it
    exists, and none of its json/html/file sub-dirs may be a link / junction.
    Returns (t_json, t_html, t_file), or None after printing why it is refused."""
    json_dir = _norm_root(config.json_storage_path)
    html_dir = _norm_root(config.html_storage_path)
    file_dir = _norm_root(config.file_storage_path)
    troot = _norm_root(trash_mod.trash_root(config))

    for label, d in (("file", file_dir), ("html", html_dir), ("json", json_dir), ("trash", troot)):
        if _overlaps(target, d):
            if purge:
                out("hib: refusing to purge '%s': it overlaps the %s storage folder "
                    "'%s' (the purge would delete inside the archive itself)." % (target, label, d))
            else:
                out("hib: refusing to back up into '%s': it overlaps the %s storage "
                    "folder '%s' (the backup would copy into the archive itself)." % (target, label, d))
            return None
    if os.path.exists(target) and not os.path.isdir(target):
        out("hib: the backup target '%s' is not a folder." % target)
        return None

    t_json = os.path.join(target, "json")
    t_html = os.path.join(target, "html")
    t_file = os.path.join(target, "file")
    for d in (t_json, t_html, t_file):
        try:
            link = _is_link_if_exists(d)
        except OSError as e:
            out("hib: cannot check the backup folder '%s' (%s)." % (d, e))
            return None
        if link:
            out("hib: refusing to %s: '%s' is a link / junction (it could lead "
                "back into the archive)." % ("purge" if purge else "back up", d))
            return None
    return t_json, t_html, t_file


def run_backup(config, args):
    """Run the backup. Never prompts. Returns 0 on success, 1 on a usage error,
    a refused/missing target, or when anything failed along the way.
    `--purge old` in `args` runs run_purge_old instead (no backup)."""

    def out(s):
        sys.stdout.write(s + "\n")

    if "--purge" in args:
        return run_purge_old(config, args)

    parsed = _parse_args(args)
    if parsed is None:
        out(USAGE)
        return 1
    dry, cli_target = parsed
    target = cli_target or getattr(config, "backup_target", None)
    if not target:
        out("hib: no backup target: give one (hib backup <target-dir>) or set "
            "[backup] target = '...' in the config.")
        return 1
    target = _norm_root(target)

    json_dir = _norm_root(config.json_storage_path)
    html_dir = _norm_root(config.html_storage_path)
    file_dir = _norm_root(config.file_storage_path)
    troot = _norm_root(trash_mod.trash_root(config))

    dirs = _checked_target_dirs(config, target, out, purge=False)
    if dirs is None:
        return 1
    t_json, t_html, t_file = dirs

    try:
        json_names = sorted(os.listdir(json_dir))
    except OSError as e:
        out("hib: cannot read the json directory '%s' (%s); nothing backed up." % (json_dir, e))
        return 1

    if not dry:
        try:
            for d in (t_json, t_html, t_file):
                os.makedirs(d, exist_ok=True)
        except OSError as e:
            out("hib: cannot create the backup folders under '%s' (%s)." % (target, e))
            return 1

    stats = _Stats()
    out("hib - backup%s" % ("  (dry run: nothing is written)" if dry else ""))
    out("  from: %s | %s | %s" % (json_dir, html_dir, file_dir))
    out("  to:   %s" % target)
    out("")

    live_json, live_cards = set(), set()
    known_cards, known_folders = set(), set()   # named by any readable JSON
    protected_json = set()      # unreadable in the archive: leave its backup alone
    unreadable = []
    guard_dirs = _guards((troot, json_dir, html_dir, target), file_dir)
    live_json_cards = {}        # dry run only: see _tag_old

    for name in json_names:
        if not name.endswith(".json"):
            continue
        full = os.path.join(json_dir, name)
        state = _path_state(full)
        if state in ("link", "missing") or (state == "plain" and not os.path.isfile(full)):
            continue
        try:
            if isinstance(state, OSError):
                raise state
            text = _read_bytes(full).decode("utf-8")
            m = model.parse(text)
            tags = list(m.tags) + _string_tags(text)
        except Exception:
            unreadable.append(full)
            protected_json.add(_key(name))
            out("  FAIL  %s  (unreadable / not hib JSON; not backed up)" % name)
            stats.failures += 1
            continue
        card_base = _safe_base(m.html_path) if m.html_path else None
        if card_base:
            known_cards.add(_key(card_base))
        folder_base = _safe_base(m.local_folder_path) if m.local_folder_path else None
        if folder_base:
            known_folders.add(_key(folder_base))
        if has_tag(tags, NOBACKUP_TAG):
            stats.nobackup += 1
            out("  skip  %s  (tagged nobackup)" % name)
            continue

        out("  item  %s" % name)
        stats.items += 1
        live_json.add(_key(name))
        if dry:
            live_json_cards[_key(name)] = card_base or ""
        _sync_file(full, os.path.join(t_json, name), dry, stats, out, "json")

        # The card.
        if m.html_path:
            if card_base:
                live_cards.add(_key(card_base))
            card, fallback = _resolve_in_root(html_dir, m.html_path)
            state = _path_state(card) if card is not None else None
            if card is None:
                out("    note  card path %s is not usable; skipped" % m.html_path)
                stats.notes += 1
            elif isinstance(state, OSError):
                out("    FAIL  card %s cannot be read (%s)" % (card, state))
                stats.failures += 1
            elif state != "plain" or not os.path.isfile(card):
                out("    note  card %s is missing; skipped" % card)
                stats.notes += 1
            else:
                if fallback:
                    out("    note  card recorded outside the html folder; using %s" % card)
                _sync_file(card, os.path.join(t_html, sanitize.base_name(card)),
                           dry, stats, out, "card")

        # The whole storage folder.
        if m.local_folder_path:
            folder, fallback = _resolve_in_root(file_dir, m.local_folder_path)
            state = _path_state(folder) if folder is not None else None
            if folder is None:
                out("    note  folder path %s is not usable; skipped" % m.local_folder_path)
                stats.notes += 1
            elif isinstance(state, OSError):
                out("    FAIL  folder %s cannot be read (%s)" % (folder, state))
                stats.failures += 1
            elif state != "plain" or not os.path.isdir(folder):
                out("    note  folder %s is missing; skipped" % folder)
                stats.notes += 1
            elif any(_inside_or_same(folder, g) for g in guard_dirs):
                out("    note  folder %s is a hib storage/trash folder; skipped" % folder)
                stats.notes += 1
            else:
                if fallback:
                    out("    note  folder recorded outside the file folder; using %s" % folder)
                leaf = _safe_base(folder)
                _sync_tree(folder, os.path.join(t_file, leaf), guard_dirs, dry, stats, out)

    # Orphans (referenced by no readable JSON, nobackup ones included): reported,
    # never backed up. Not counted when a JSON was unreadable -- its live card /
    # folder would look orphaned.
    orphan_cards = orphan_folders = 0
    if not unreadable:
        for name in _listdir(html_dir):
            full = os.path.join(html_dir, name)
            if (name.endswith(".html") and _key(name) not in known_cards
                    and not _is_reparse(full) and os.path.isfile(full)):
                orphan_cards += 1
        for name in _listdir(file_dir):
            full = os.path.join(file_dir, name)
            if _key(name) in known_folders or _is_reparse(full) or not os.path.isdir(full):
                continue
            if any(_touches_dir(full, g) for g in guard_dirs):
                continue
            orphan_folders += 1

    # Tag `old` what only the backup still holds.
    out("")
    out("Tagging old copies (in the backup only)...")
    if os.path.isdir(t_json) or os.path.isdir(t_html):
        _tag_old(t_json, t_html, live_json, live_cards, protected_json, dry, stats, out,
                 live_json_cards)

    out("")
    out("Summary%s:" % (" (dry run)" if dry else ""))
    out("  items backed up       : %d" % stats.items)
    out("  items skipped nobackup: %d" % stats.nobackup)
    out("  files %-16s: %d" % ("to copy" if dry else "copied", stats.copied))
    out("  files unchanged       : %d" % stats.unchanged)
    out("  tagged old            : %d JSON, %d card(s)%s" % (
        stats.tagged_old_json, stats.tagged_old_card,
        ("  (%d already old)" % stats.already_old) if stats.already_old else ""))
    if unreadable:
        out("  orphans ignored       : not counted (unreadable JSON present)")
    else:
        out("  orphans ignored       : %d card(s), %d folder(s) (in no JSON; not backed up)"
            % (orphan_cards, orphan_folders))
    out("  notes                 : %d" % stats.notes)
    out("  failures              : %d" % stats.failures)
    if unreadable:
        out("")
        out("Unreadable JSON (not backed up; fix them and re-run):")
        for p in unreadable:
            out("  %s" % p)
    if dry:
        out("")
        out("(dry run: nothing was written.)")
    return 1 if stats.failures else 0


# --- hib backup --purge old ----------------------------------------------------

def card_is_old(text):
    """True when the card `text` carries the `old` tag span in its Tags block
    (the form tag_card_text_old writes; trimmed, any case)."""
    m = _TAGS_BLOCK.search(text)
    return bool(m and _TAG_SPAN_OLD.search(m.group(1)))


def _parse_purge_args(args):
    """(dry, target or None) for `--purge old [<target>] [-n]`, None on a usage
    error. Only `old` (trimmed, any case, like the tag) may follow --purge."""
    dry = False
    pos = []
    what = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--purge":
            if what is not None or i + 1 >= len(args):
                return None
            what = args[i + 1]
            i += 2
            continue
        if a in ("-n", "--dry-run"):
            dry = True
        elif a.startswith("-") and len(a) > 1:
            return None
        else:
            pos.append(a)
        i += 1
    if what is None or what.strip().lower() != OLD_TAG or len(pos) > 1:
        return None
    return dry, (pos[0] if pos else None)


def _ask(label, default):
    """Prompt on stdout, read one line of stdin (as purgecmd's ask): EOF or an
    empty answer gives `default`."""
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


def _lstat_is_dir(st):
    """True for a directory-like entry from lstat: a plain dir, or a junction /
    directory symlink (FILE_ATTRIBUTE_DIRECTORY on Windows)."""
    if stat.S_ISDIR(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10))


def _remove_link(path):
    """Remove the link / junction `path` ITSELF, never what it points to:
    RemoveDirectory for a junction / directory symlink, DeleteFile otherwise."""
    st = os.lstat(path)
    if _lstat_is_dir(st):
        try:
            os.rmdir(path)
            return
        except OSError:
            if not stat.S_ISLNK(st.st_mode):
                raise
    os.remove(path)


def _remove_file(path):
    _make_writable(path)        # copy2 copies the read-only attribute
    os.remove(path)


def _remove_tree(path, errors):
    """Delete `path` recursively WITHOUT following any link: a link / junction
    met anywhere (`path` itself included) is removed as a link, never descended
    into. shutil.rmtree is not used: before Python 3.8 it does not see a
    junction as a link on Windows and would empty the junction's target.
    Failures are appended to `errors` as (path, error); the rest goes on."""
    try:
        link = _is_link(path)
    except FileNotFoundError:
        return
    except OSError as e:
        errors.append((path, e))
        return
    try:
        if link:
            _remove_link(path)
            return
        if not os.path.isdir(path):
            _remove_file(path)
            return
    except OSError as e:
        errors.append((path, e))
        return
    try:
        names = os.listdir(path)
    except OSError as e:
        errors.append((path, e))
        return
    for name in names:
        _remove_tree(os.path.join(path, name), errors)
    try:
        _make_writable(path)
        os.rmdir(path)
    except OSError as e:
        errors.append((path, e))


def _list_target_dir(d):
    """Sorted names of `d`; [] when it does not exist. Raises OSError when it
    exists but cannot be listed."""
    if not os.path.lexists(d):
        return []
    return sorted(os.listdir(d))


def _purge_base(path):
    """The basename of a recorded card/folder path as Windows resolves it: the
    _safe_base, minus the trailing dots and spaces Win32 strips when it opens a
    path ('Live.html.' IS 'Live.html' on disk). None when unusable. The purge
    compares and deletes by this name only, so a hand-edited 'X.' can never
    slip past the shared-with-live check and then resolve to the live 'X'."""
    base = _safe_base(path)
    if base is None:
        return None
    base = base.rstrip(" .")
    if not base or _safe_base(base) != base:
        return None
    return base


def _entry_in(root, base, want_dir):
    """(path, is_link, problem) for `<root>\\<base>`: (path, is_link, None) when
    it is strictly inside `root` and exists as a link / junction, or as a plain
    dir (want_dir) / file (not want_dir); (None, False, None) when it does not
    exist or the name is unusable; (None, False, reason) when it exists but
    cannot be checked (lstat error) or has the wrong type -- the caller must
    then keep the JSON naming it, never orphan it."""
    if not base or _purge_base(base) != base:
        return None, False, None
    full = os.path.join(root, base)
    if not locate.is_within(root, full):
        return None, False, None
    state = _path_state(full)
    if state == "link":
        return full, True, None
    if state == "missing":
        return None, False, None
    if isinstance(state, OSError):
        return None, False, "cannot be checked (%s)" % state
    if os.path.isdir(full) if want_dir else os.path.isfile(full):
        return full, False, None
    return None, False, ("is not a folder" if want_dir else "is not a file")


def run_purge_old(config, args):
    """`hib backup --purge old [<target>] [-n]`: permanently delete from the
    BACKUP every entry tagged `old` -- its JSON, its card and its storage folder,
    except a card / folder that a JSON of the backup NOT tagged old also names
    (a renamed item shares it with its old copy) -- and every card tagged old
    that no such live JSON names. Never runs a backup; never touches the
    archive (same target checks as the backup). Safe behaviour on doubt: when
    any JSON of the backup cannot be read (or is a link), what it references is
    unknown, so NOTHING is deleted and the purge exits 1; a card/folder of an
    old JSON that exists but cannot be checked keeps that JSON (failure).
    Names compare as Win32 resolves them (_purge_base). Prompts (default NO)
    unless -n. Returns 0, or 1 on a usage error / refusal / any failure."""

    def out(s):
        sys.stdout.write(s + "\n")

    parsed = _parse_purge_args(args)
    if parsed is None:
        out(USAGE)
        return 1
    dry, cli_target = parsed
    target = cli_target or getattr(config, "backup_target", None)
    if not target:
        out("hib: no backup target: give one (hib backup --purge old <target-dir>) or "
            "set [backup] target = '...' in the config.")
        return 1
    target = _norm_root(target)
    dirs = _checked_target_dirs(config, target, out, purge=True)
    if dirs is None:
        return 1
    if not os.path.isdir(target):
        out("hib: the backup target '%s' does not exist; nothing to purge." % target)
        return 1
    t_json, t_html, t_file = dirs

    # 1) Classify the backup JSONs: old ones, and what the live ones name.
    try:
        json_names = _list_target_dir(t_json)
    except OSError as e:
        out("hib: cannot read the backup json folder '%s' (%s); nothing deleted." % (t_json, e))
        return 1
    old_json = []           # (path, card_base or None, folder_base or None)
    live_cards = {}         # card key -> name of a live JSON naming it
    live_folders = {}       # folder key -> name of a live JSON naming it
    unreadable = []
    for name in json_names:
        if not name.lower().endswith(".json"):
            continue
        full = os.path.join(t_json, name)
        state = _path_state(full)
        if state == "missing" or (state == "plain" and not os.path.isfile(full)):
            continue
        try:
            if isinstance(state, OSError):
                raise state
            if state == "link":
                raise OSError("a link / junction, not read")
            text = _read_bytes(full).decode("utf-8")
            m = model.parse(text)
            tags = list(m.tags) + _string_tags(text)
        except Exception as e:
            unreadable.append((full, e))
            continue
        card_base = _purge_base(m.html_path) if m.html_path else None
        folder_base = _purge_base(m.local_folder_path) if m.local_folder_path else None
        if has_tag(tags, OLD_TAG):
            old_json.append((full, card_base, folder_base))
        else:
            if card_base:
                live_cards.setdefault(_key(card_base), name)
            if folder_base:
                live_folders.setdefault(_key(folder_base), name)

    out("hib - purge old entries from the backup%s"
        % ("  (dry run: nothing is deleted)" if dry else ""))
    out("  target: %s" % target)
    out("")
    if unreadable:
        out("hib: %d JSON file(s) of the backup could not be read/parsed; purge aborted "
            "(the cards/folders they name are unknown, so nothing is deleted):"
            % len(unreadable))
        for p, e in unreadable:
            out("  %s  (%s)" % (p, e))
        out("Fix or remove those JSON files, then re-run.")
        return 1

    failures = 0
    cards = collections.OrderedDict()       # key -> (path, is_link)
    folders = collections.OrderedDict()     # key -> (path, is_link)
    kept = collections.OrderedDict()        # (kind, key) -> preview line
    json_deps = []                  # (json path, card key, folder key, blocked)

    def keep(kind, root, base, owner):
        # Only what is really there is reported as kept.
        if _path_state(os.path.join(root, base)) == "missing":
            return
        kept.setdefault((kind, _key(base)), "  [%s] %s  (also named by %s)"
                        % (kind, os.path.join(root, base), owner))

    # 2) What each old JSON takes with it. A card/folder that exists but cannot
    # be checked (or has the wrong type) is a failure, and its JSON is KEPT: it
    # is the only thing that names that card/folder, so a re-run still finds it.
    for full, card_base, folder_base in old_json:
        ck = fk = None
        blocked = False
        for kind, base, root, live, table, want_dir in (
                ("card", card_base, t_html, live_cards, cards, False),
                ("folder", folder_base, t_file, live_folders, folders, True)):
            if not base:
                continue
            if _key(base) in live:
                keep(kind, root, base, live[_key(base)])
                continue
            p, link, problem = _entry_in(root, base, want_dir=want_dir)
            if problem:
                out("  FAIL  %s %s %s; not deleted, %s kept"
                    % (kind, os.path.join(root, base), problem, full))
                failures += 1
                blocked = True
            elif p:
                table.setdefault(_key(base), (p, link))
                if kind == "card":
                    ck = _key(base)
                else:
                    fk = _key(base)
        json_deps.append((full, ck, fk, blocked))

    # 3) Cards tagged old in the html folder, named by no live JSON.
    try:
        card_names = _list_target_dir(t_html)
    except OSError as e:
        out("hib: cannot read the backup html folder '%s' (%s); nothing deleted." % (t_html, e))
        return 1
    for name in card_names:
        # A name Win32 would not resolve to itself (trailing dot/space) is
        # never addressed: deleting it could hit another card.
        if (not name.lower().endswith(".html") or _purge_base(name) != name
                or _key(name) in cards):
            continue
        full = os.path.join(t_html, name)
        state = _path_state(full)
        if isinstance(state, OSError):
            out("  FAIL  card %s cannot be read (%s); not deleted" % (full, state))
            failures += 1
            continue
        if state != "plain" or not os.path.isfile(full):
            continue
        try:
            is_old = card_is_old(_read_text(full))
        except OSError as e:
            out("  FAIL  card %s cannot be read (%s); not deleted" % (full, e))
            failures += 1
            continue
        if not is_old:
            continue
        if _key(name) in live_cards:
            keep("card", t_html, name, live_cards[_key(name)])
        elif _safe_base(name) == name and locate.is_within(t_html, full):
            cards[_key(name)] = (full, False)

    # Preview.
    def link_note(is_link):
        return "  (link / junction: only the link is removed)" if is_link else ""

    n_json_del = sum(1 for d in json_deps if not d[3])
    if old_json:
        out("Old JSON (%d):" % len(old_json))
        for full, _, _, blocked in json_deps:
            out("  [json]   %s%s" % (full, "  (kept: see FAIL above)" if blocked else ""))
    if cards:
        out("Cards (%d):" % len(cards))
        for p, link in cards.values():
            out("  [card]   %s%s" % (p, link_note(link)))
    if folders:
        out("Folders, with everything inside (%d):" % len(folders))
        for p, link in folders.values():
            out("  [folder] %s%s" % (p, link_note(link)))
    if kept:
        out("Kept, shared with an item not tagged old (%d):" % len(kept))
        for line in kept.values():
            out(line)
    if not (old_json or cards or folders):
        out("Nothing to purge - no entry tagged old in the backup.")
        return 1 if failures else 0
    if not (n_json_del or cards or folders):
        out("Nothing can be deleted (see the failures above).")
        out("  failures     : %d" % failures)
        return 1

    if dry:
        out("")
        out("Summary (dry run):")
        out("  to delete    : %d JSON, %d card(s), %d folder(s)"
            % (n_json_del, len(cards), len(folders)))
        out("  kept (shared): %d" % len(kept))
        out("  failures     : %d" % failures)
        out("")
        out("(dry run: nothing was deleted.)")
        return 1 if failures else 0

    ans = _ask("\nDelete these old entries from the backup permanently? (y/N)", "n")
    if not (ans and ans[0].lower() == "y"):
        out("")
        out("Aborted - nothing was deleted.")
        return 1 if failures else 0
    out("")

    # Folders, then cards, then the JSONs: a JSON whose folder/card could not be
    # deleted is kept, so a re-run still finds (and finishes) that entry.
    failed = set()
    n_folders = n_cards = n_json = 0
    for kind, root, table in (("folder", t_file, folders), ("card", t_html, cards)):
        for k, (p, link) in table.items():
            if not locate.is_within(root, p):
                failed.add((kind, k))
                continue
            errors = []
            if kind == "folder":
                _remove_tree(p, errors)
            else:
                try:
                    if link:
                        _remove_link(p)
                    else:
                        _remove_file(p)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    errors.append((p, e))
            if errors:
                failed.add((kind, k))
                failures += 1
                out("  FAIL delete %s %s" % (kind, p))
                for ep, e in errors[:10]:
                    out("       %s (%s)" % (ep, e))
                if len(errors) > 10:
                    out("       ... and %d more" % (len(errors) - 10))
                continue
            out("  deleted %s  %s" % (kind, p))
            if kind == "folder":
                n_folders += 1
            else:
                n_cards += 1
    for full, ck, fk, blocked in json_deps:
        if blocked:
            out("  kept json  %s (its card/folder could not be checked; re-run)" % full)
            continue
        if ("card", ck) in failed or ("folder", fk) in failed:
            out("  kept json  %s (its card/folder could not be deleted; re-run)" % full)
            continue
        if not locate.is_within(t_json, full):
            continue
        try:
            _remove_file(full)
        except FileNotFoundError:
            pass
        except OSError as e:
            out("  FAIL delete json %s (%s)" % (full, e))
            failures += 1
            continue
        out("  deleted json  %s" % full)
        n_json += 1

    out("")
    out("Summary:")
    out("  deleted      : %d JSON, %d card(s), %d folder(s)" % (n_json, n_cards, n_folders))
    out("  kept (shared): %d" % len(kept))
    out("  failures     : %d" % failures)
    return 1 if failures else 0
