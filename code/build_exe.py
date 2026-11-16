#!/usr/bin/env python3
"""Build a standalone hib.exe with PyInstaller.

    py -3 -m pip install pyinstaller docx2pdf
    py -3 build_exe.py            ->  bin\\hib.exe

One self-contained file: no Python needed on the target machine, and docx2pdf /
pywin32 travel inside it, so Word conversion works out of the box.

READ THIS FIRST -- the .exe is not free:

  * ANTIVIRUS. A PyInstaller one-file binary is the most heuristically-flagged
    shape there is, and an unsigned .exe may be quarantined or deleted by the
    AV (see README). Test it on the target machine
    before relying on it; `hib.bat` / `hib.ps1` on the plain .py files stay the
    safe fallback.
  * STARTUP. A one-file exe unpacks itself into %TEMP% on every run (~0.5-1 s),
    and the PDF conversion child process pays that again. Pass --onedir for a
    folder build that starts instantly.
  * The .exe embeds a SNAPSHOT of the code. Rebuild after every change.

The build does NOT bundle config.toml or itemTypes.txt: those stay where hib
reads them at run time (%LOCALAPPDATA%\\hib\\config, or HIB_CONFIG).
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "bin")
WORK = os.path.join(HERE, "build")

# docx2pdf imports win32com lazily and PyInstaller cannot see through that;
# tqdm is docx2pdf's own module-level import.
HIDDEN = ["docx2pdf", "tqdm", "win32com", "win32com.client"]
# Nothing in hib draws a GUI; dropping these keeps the binary smaller.
EXCLUDE = ["tkinter", "unittest", "pydoc", "doctest"]


def main(argv):
    onedir = "--onedir" in argv
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("hib: PyInstaller is not installed (py -3 -m pip install pyinstaller).")
        return 1
    try:
        import docx2pdf  # noqa: F401
    except ImportError:
        # Not fatal: hib would simply fall back to the external converter, but a
        # PDF-less hib.exe is rarely what you want, so say so loudly.
        print("hib: WARNING - docx2pdf is not installed in THIS interpreter, so the")
        print("     .exe will be built without Word conversion (only the fallback")
        print("     converter would work). py -3 -m pip install docx2pdf")

    cmd = [sys.executable, "-m", "PyInstaller",
           "--onedir" if onedir else "--onefile",
           "--console", "--noconfirm", "--clean",
           "--name", "hib",
           "--distpath", DIST,
           "--workpath", os.path.join(WORK, "pyinstaller"),
           "--specpath", WORK]
    for name in HIDDEN:
        cmd += ["--hidden-import", name]
    for name in EXCLUDE:
        cmd += ["--exclude-module", name]
    cmd.append(os.path.join(HERE, "hib.py"))

    os.makedirs(WORK, exist_ok=True)
    print("$ " + subprocess.list2cmdline(cmd))
    code = subprocess.call(cmd)
    if code != 0:
        print("hib: PyInstaller failed (exit %s)." % code)
        return code

    exe = os.path.join(DIST, "hib.exe") if not onedir else os.path.join(DIST, "hib", "hib.exe")
    if not os.path.exists(exe):
        print("hib: build reported success but %s is missing (antivirus?)." % exe)
        return 1
    print("")
    print("Built %s (%.1f MB)" % (exe, os.path.getsize(exe) / 1048576.0))
    print("Smoke test:  %s help" % exe)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
