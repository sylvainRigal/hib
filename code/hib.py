#!/usr/bin/env python3
"""hib -- archive files indexed by tags, and open/navigate them by citekey.
Reads and writes a config.toml + f/html/json archive. Opening uses os.startfile
(no PowerShell/base64), so it is not "malware-shaped".

Usage:
  hib                    add an entry (interactive)
  hib <source-file>      add that file directly (skips the source prompt)
  hib add [<source-file>] same as above
  hib update <citekey>   re-edit an entry's metadata (rewrites card + JSON)
  hib update -html [-n]   re-render ALL HTML cards from their JSON (no editing); -n lists only
  hib update -json-names [-n]  rename ALL metadata files after their reference
  hib update -json <ctk>  rewrite an entry's JSON from its hand-edited HTML card
  hib update -remote <ctk> [<path>]  set/replace/remove ONLY the remote path
  hib update -ctk <ctk> [<new>]      change ONLY the citekey (nothing is renamed)
  hib delete <citekey>   move an entry (card, storage folder, JSON) to the trash
  hib purge [-n]         move orphan cards/folders (in no JSON) to the trash; -n lists only
  hib backup [<dir>] [-n] incremental copy of every item (JSON, card, folder) into
                         <dir> (default: [backup] target); never deletes there.
                         Tag nobackup = item left out; copies no longer in the
                         archive get the tag old. -n lists only
  hib backup --purge old [<dir>] [-n]  permanently delete from the BACKUP every
                         entry tagged old (JSON, card, folder; a card/folder a
                         live copy shares is kept). Asks first; -n lists only
  hib pdf <citekey>      (re)generate the PDF and refresh the card
  hib pdf <ctk> <f.pdf>  attach an EXISTING PDF (copied into the entry's folder)
  hib config             print the storage paths hib uses (flags any missing folder)
  hib o   <citekey>      open the stored file in its app (else its folder)
  hib opdf <citekey>     open the local PDF (else its folder)
  hib or  <citekey>      open the remote source file (else its folder)
  hib oe / oer <citekey> open the local / remote folder in Explorer
                         (aliases: openfolder / openremotefolder)
  hib of                 open the HTML directory in Explorer
  hib cd / cdr <citekey> cd into the local / remote folder (via hib.ps1 / hib.bat)
  hib cdf                cd into the HTML directory
Selector: a citekey OR a reference (default, interchangeable; partial -> a numbered
pick list). Restrict it with -citekey (short: -ctk) / -ref / -html <value>.
  (-ctk right after `update` is the re-key mode above; use -citekey to select.)
Add -n / --dry-run to print what would open without launching.
"""
import os
import sys


def _foreign_env(pythonhome, pythonpath):
    """Whether a foreign PYTHONHOME/PYTHONPATH is set (e.g. another app's Anaconda
    on the same locked-down PC). Such a variable can put the WRONG Python standard
    library ahead of ours on sys.path; importing `re` then loads an sre_compile.py
    whose MAGIC differs from THIS interpreter's builtin _sre, raising
    'AssertionError: SRE module mismatch'."""
    return bool(pythonhome or pythonpath)


def _repair_stdlib_path():
    """When a foreign PYTHONHOME/PYTHONPATH is set, put THIS interpreter's own
    standard library right after the script directory on sys.path, so the `import`s
    below (json -> re) load the sre_compile.py that matches our builtin _sre. This
    keeps a bare `python hib.py` working even without the hib wrapper's -E -s, and
    without spawning a child -- subprocess would import `re` and trip the very
    assert we are dodging, and os.spawnve mis-quotes args and is flaky here. Insert
    at index 1 (after sys.path[0], our own dir) so hib's sibling modules (e.g.
    html.py) still win over same-named stdlib ones (the stdlib `html` package)."""
    if not _foreign_env(os.environ.get("PYTHONHOME"), os.environ.get("PYTHONPATH")):
        return
    real_lib = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "Lib")
    if os.path.isdir(real_lib) and real_lib not in sys.path[:2]:
        sys.path.insert(1, real_lib)


_repair_stdlib_path()

import config as config_mod
import selector as sel
import locate
import addcmd
import updcmd
import delcmd
import purgecmd
import backupcmd
import pdfcmd
import pdfgen


def _force_utf8_stdio():
    """Make stdio UTF-8 both ways: read piped stdin as UTF-8 (not the
    Windows locale code page cp1252, which would mojibake accented answers) and
    write stdout/stderr as UTF-8 (so an accented path/prompt never raises a
    UnicodeEncodeError). surrogateescape/backslashreplace keep us from crashing on
    bytes that are not valid UTF-8. The interactive console is already UTF-8
    (Python's _WindowsConsoleIO), so reconfiguring it is a harmless no-op. Best
    effort: a stream without reconfigure (pre-3.7) or a detached stream is skipped.
    """
    for stream, errors in ((sys.stdin, "surrogateescape"),
                           (sys.stdout, "backslashreplace"),
                           (sys.stderr, "backslashreplace")):
        try:
            stream.reconfigure(encoding="utf-8", errors=errors)
        except (AttributeError, ValueError, OSError):
            pass


def _stdout(msg):
    sys.stdout.write(msg + "\n")


def _stderr(msg):
    sys.stderr.write(msg + "\n")


def _prompt(text):
    sys.stderr.write(text)
    sys.stderr.flush()
    try:
        return sys.stdin.readline()
    except Exception:
        return ""


def take_dry_run(args):
    dry = False
    rest = []
    for a in args:
        if a in ("-n", "--dry-run"):
            dry = True
        else:
            rest.append(a)
    return dry, rest


def _add_source(first, extra):
    """The source path for `add`, re-attaching a lone trailing '*' that PowerShell
    split off into its own argument. PowerShell tokenizes `"path"*` (a remote
    marker glued OUTSIDE the closing quote) as TWO args -- 'path' and '*' -- which
    would drop the marker; cmd.exe and an in-quote '*' keep it in one token. add
    uses only the first source, so a bare trailing '*' can only be that marker."""
    if first and not first.endswith("*") and extra and extra[-1] == "*":
        return first + "*"
    return first


def parent_dir(p):
    s = p[:-1] if p and p[-1] in "\\/" else p   # drop exactly ONE trailing sep
    i = max(s.rfind("\\"), s.rfind("/"))
    if i < 0:
        return ""
    if i == 2 and len(s) > 1 and s[1] == ":":   # drive root "C:\x" -> "C:\"
        return s[:3]
    return s[:i]


def shell_open(path, dry, out):
    if dry:
        out("would open: %s" % path)
        return
    try:
        os.startfile(path)          # Windows ShellExecute: file->app, dir->Explorer
    except OSError as e:
        out("hib: could not open %s (%s)." % (path, e))
        return
    out("Opening: %s" % path)


def open_file_else_folder(file_path, folder, label, dry, out):
    if file_path and os.path.exists(file_path):
        shell_open(file_path, dry, out)
        return
    if folder and os.path.exists(folder):
        out("hib: %s not found; opening its folder instead." % label)
        shell_open(folder, dry, out)
        return
    out("hib: neither the %s nor its folder exists." % label)


def cmd_open(config, args, kind):
    dry, rest = take_dry_run(args)
    s = sel.parse_selector(rest, _stdout)
    if s is None:
        return 1
    found = sel.resolve_entry(config, s[0], s[1], _prompt, _stdout)
    if found is None:
        return 1
    m = found.meta
    if kind == "local_file":
        open_file_else_folder(m.local_file_path, m.local_folder_path, "local file", dry, _stdout)
    elif kind == "local_pdf":
        open_file_else_folder(m.pdf_local_path, m.local_folder_path, "local PDF", dry, _stdout)
    elif kind == "local_folder":
        if m.local_folder_path:
            shell_open(m.local_folder_path, dry, _stdout)
        else:
            _stdout("hib: this entry has no local folder recorded.")
    elif kind in ("remote_file", "remote_folder"):
        rp = m.remote_path
        if not rp:
            _stdout("hib: this entry has no remote path recorded.")
            return 1
        if kind == "remote_file":
            open_file_else_folder(rp, parent_dir(rp), "remote file", dry, _stdout)
        else:
            rd = parent_dir(rp)
            if rd:
                shell_open(rd, dry, _stdout)
            else:
                _stdout("hib: the remote path has no folder.")
    return 0


def cmd_cd(config, args, kind):
    """Print the target directory on STDOUT (for `Set-Location (hib cd X)`);
    disambiguation/errors go to STDERR so the captured stdout is just the path.
    With -n, print 'would cd: <dir>' to stderr instead."""
    dry, rest = take_dry_run(args)
    s = sel.parse_selector(rest, _stderr)
    if s is None:
        return 1
    found = sel.resolve_entry(config, s[0], s[1], _prompt, _stderr)
    if found is None:
        return 1
    m = found.meta
    if kind == "local":
        d = m.local_folder_path
    else:
        rp = m.remote_path
        if not rp:
            _stderr("hib: this entry has no remote path recorded.")
            return 1
        d = parent_dir(rp)
    if not d:
        _stderr("hib: no folder recorded for this entry.")
        return 1
    if dry:
        _stderr("would cd: %s" % d)
    else:
        sys.stdout.write(d + "\n")      # bare path for the shell wrapper
    return 0


def _path_with_status(path):
    """A configured path with a trailing [MISSING] when the folder is absent --
    the quick way to spot a storage path that points nowhere on this PC."""
    if not path:
        return "(not set)"
    return path + ("" if os.path.isdir(path) else "    [MISSING]")


def _config_source(config_dir):
    """The file the config was actually read from (HIB_CONFIG wins; else the
    config.toml, or the legacy .txt, under %LOCALAPPDATA%\\hib\\config)."""
    hc = os.environ.get("HIB_CONFIG")
    if hc:
        return hc
    toml_path = os.path.join(config_dir, "config.toml")
    if os.path.exists(toml_path):
        return toml_path
    txt_path = os.path.join(config_dir, "pathToFilesLocation.txt")
    if os.path.exists(txt_path):
        return txt_path
    return toml_path


def cmd_config(config, config_dir):
    """Print the storage paths hib resolved, flagging any folder that is missing
    (so a wrong/relocated html path on this PC is obvious)."""
    _stdout("config file  : %s" % _config_source(config_dir))
    _stdout("file  storage: %s" % _path_with_status(config.file_storage_path))
    _stdout("html  storage: %s" % _path_with_status(config.html_storage_path))
    _stdout("json  storage: %s" % _path_with_status(config.json_storage_path))
    if config.trash_storage_path:
        _stdout("trash storage: %s" % _path_with_status(config.trash_storage_path))
    else:
        default_trash = os.path.join(config.file_storage_path, "trash")
        _stdout("trash storage: (default) %s" % _path_with_status(default_trash))
    if config.pdf_converter_cmd is not None:
        _stdout("pdf (cmd)    : %s" % config.pdf_converter_cmd)
    if config.pdf_converter_ps is not None:
        _stdout("pdf (ps)     : %s" % config.pdf_converter_ps)
    _stdout("backup target: %s" % _path_with_status(config.backup_target))
    return 0


def cmd_open_dir(html_dir, args, shell):
    dry, _ = take_dry_run(args)
    d = html_dir.rstrip("\\/")
    if shell:                           # cdf -> emit the dir for a Set-Location wrapper
        if dry:
            _stderr("would cd: %s" % d)
        else:
            sys.stdout.write(d + "\n")
    else:                               # of -> open in Explorer
        shell_open(d, dry, _stdout)
    return 0


def print_usage():
    sys.stdout.write(__doc__)


OPEN_CMDS = {
    "o": "local_file", "opdf": "local_pdf", "or": "remote_file",
    "oe": "local_folder", "oer": "remote_folder",
    # Spelled-out aliases for the two Explorer commands. They must be listed
    # here: an unknown command is treated as a source file path for `add`, so
    # `hib openfolder X` would otherwise start adding a file named "openfolder".
    "openfolder": "local_folder", "openremotefolder": "remote_folder",
}
CD_CMDS = {"cd": "local", "cdr": "remote"}
# An unknown command is treated as a source file path for `add`, so there is
# nothing to reserve here.
NOT_PORTED = ()


def main(argv):
    _force_utf8_stdio()
    # Private: in a frozen build (hib.exe) the PDF conversion re-invokes this very
    # executable as its child process, since sys.executable is no longer a Python
    # interpreter. Dispatched FIRST -- before the config is loaded, and before the
    # "unknown command -> a file to add" fallthrough could swallow it.
    if argv and argv[0] == pdfgen.CHILD_FLAG:
        return pdfgen.convert_child(argv[1:])
    if argv and argv[0] in ("help", "-h", "--help"):
        print_usage()
        return 0

    loaded = config_mod.load(os.environ, out=_stderr)   # messages to stderr (keep cd's stdout clean)
    if loaded is None:
        return 1
    config, config_dir = loaded

    cmd = argv[0] if argv else ""
    rest = argv[1:]

    # add: `hib`, `hib add [path]`, or `hib <path>` (an unknown cmd is the source).
    if cmd == "" or cmd == "add":
        source = _add_source(rest[0], rest[1:]) if (cmd == "add" and rest) else ""
        return addcmd.run_add(config, source, config_dir)
    if cmd in ("update", "edit"):
        return updcmd.run_update(config, rest, config_dir)
    if cmd in ("delete", "rm"):
        return delcmd.run_delete(config, rest)
    if cmd == "purge":
        return purgecmd.run_purge(config, rest)
    if cmd == "backup":
        return backupcmd.run_backup(config, rest)
    if cmd == "pdf":
        return pdfcmd.run_pdf(config, rest)
    if cmd in ("config", "paths"):
        return cmd_config(config, config_dir)

    if cmd in OPEN_CMDS:
        return cmd_open(config, rest, OPEN_CMDS[cmd])
    if cmd in CD_CMDS:
        return cmd_cd(config, rest, CD_CMDS[cmd])
    if cmd == "of":
        return cmd_open_dir(config.html_storage_path, rest, shell=False)
    if cmd == "cdf":
        return cmd_open_dir(config.html_storage_path, rest, shell=True)
    if cmd in NOT_PORTED:
        _stderr('hib: "%s" is not implemented yet.' % cmd)
        return 1

    # Not a known subcommand: treat the whole argument as a source path -> add.
    return addcmd.run_add(config, _add_source(cmd, rest), config_dir)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
