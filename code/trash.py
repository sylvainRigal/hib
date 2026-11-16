"""Move-to-trash helpers shared by `delete` and `purge`.
Nothing is ever erased: targets are MOVED into the
trash. Never fatal: failures are warnings via `out`, and a file is only removed
once its move/copy succeeded.

shutil.move handles the cross-volume case (a rename cannot cross drives) by
copying then deleting. (It follows symlinks rather than refusing them, but hib
only ever writes flat folders of regular files.)
"""
import os
import shutil

import sanitize


def trash_root(config):
    """The configured `trash` path (trailing seps trimmed), else
    `<file_storage_path>\\trash`."""
    t = config.trash_storage_path
    if t:
        trimmed = t.rstrip("\\/")
        if trimmed:
            return trimmed
    return os.path.join(config.file_storage_path.rstrip("\\/"), "trash")


def free_trash_dest(troot, leaf):
    """First not-yet-existing '<troot>\\<leaf>', numbering '_N' on collision."""
    n = 0
    while n <= 1000000:
        name = leaf if n == 0 else "%s_%d" % (leaf, n)
        cand = os.path.join(troot, name)
        if not os.path.exists(cand):
            return cand
        n += 1
    raise OSError("no free trash folder")


def free_name_in_dir(directory, basename):
    """First not-yet-existing '<dir>\\<basename>', else '<dir>\\<stem>_N<ext>', so a
    moved file never overwrites one already in the trash subfolder."""
    stem = sanitize.strip_extension(basename)
    ext = basename[len(stem):]          # includes the dot, or "" when none
    n = 0
    while n <= 1000000:
        name = basename if n == 0 else "%s_%d%s" % (stem, n, ext)
        cand = os.path.join(directory, name)
        if not os.path.exists(cand):
            return cand
        n += 1
    raise OSError("no free trash name")


def move_dir_to(src_path, dest_path, out):
    """Move the directory `src_path` to `dest_path` (which must not yet exist).
    Returns True on success; a failure is a warning and False."""
    try:
        # A plain rename() FAILS when dest already exists; refuse here too.
        # Without this guard shutil.move would move src INSIDE an existing
        # dest (nesting/merging it with an unrelated trashed entry) and report
        # success. (A small exists/move TOCTOU remains; the silent nest is gone.)
        if os.path.exists(dest_path):
            raise FileExistsError("destination already exists: %s" % dest_path)
        shutil.move(src_path, dest_path)
        return True
    except (OSError, ValueError, shutil.Error) as e:
        # ValueError covers shutil.move's "embedded null character" on a tampered
        # JSON path -- keep the never-fatal guarantee instead of crashing.
        out("  WARNING: could not move folder (%s): %s" % (src_path, e))
        return False


def move_file_into(src_path, dest_dir, label, out):
    """Move the single file `src_path` into `dest_dir` under a NON-colliding name.
    A missing source is a note; any other failure a warning. Never fatal."""
    try:
        dst = free_name_in_dir(dest_dir, sanitize.base_name(src_path))
    except OSError:
        out("  WARNING: could not place %s in the trash (%s); left in place." % (label, src_path))
        return
    try:
        shutil.move(src_path, dst)
        out("  moved %s:   %s" % (label, dst))
    except FileNotFoundError:
        out("  note: %s already gone (%s)." % (label, src_path))
    except (OSError, ValueError, shutil.Error) as e:
        # ValueError covers a NUL in a tampered JSON path -- never fatal.
        out("  WARNING: could not move %s (%s): %s" % (label, src_path, e))
