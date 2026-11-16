"""Word -> PDF generation, in two stages.

  1. **Python**: docx2pdf, which drives an installed Microsoft Word (win32com on
     Windows, JXA on macOS). No pandoc, no soffice, no operator command template.

  2. **Fallback**: if stage 1 produces no PDF -- Word not installed, docx2pdf not
     installed, an .xlsx Word will not open -- an external converter (pandoc,
     soffice, ...) is tried. *Where* that converter is declared is written, in
     plain text, in `<this folder>/config/config.toml`:

         [pdf]
         fallback_config = '%LOCALAPPDATA%\\hib\\config.toml'

     (environment variables are expanded; if the key or the file is missing, that
     same path is used as the built-in default). That second file names the
     executable:

         [pdf]
         converter = 'C:\\Users\\me\\AppData\\Local\\Pandoc\\pandoc.exe'
         args = '{input} -o {output}'    # optional; inferred for known tools
         # or, the whole command line in one string (the legacy hib key, so the
         # existing configs work as-is):
         cmd = '"C:\\...\\soffice.exe" --headless --convert-to pdf --outdir {outdir} {input}'

     Placeholders: {input}, {output}, {outdir}. Substitution happens *after*
     tokenizing, so a path containing spaces stays a single argument, and the
     command is never handed to a shell.

Both stages run in a child process with a timeout and no console window, and the
whole module is best-effort: it never raises, so a PDF failure can never abort an
`add` and orphan the storage folder.
"""
import os
import sys
import subprocess
import hibtoml
import sanitize
import uri

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_WORD_TIMEOUT = 60
_FALLBACK_TIMEOUT = 120        # soffice's first, cold start is slow

# PyInstaller (and friends) set sys.frozen: sys.executable is then hib.exe itself,
# not a Python interpreter, so the conversion child is invoked differently.
_FROZEN = getattr(sys, "frozen", False)
CHILD_FLAG = "--hib-convert-docx"   # private; dispatched by hib.main

# Where the *pointer* to the fallback config is written (hard-coded, editable
# without touching any Python), and the default used when it says nothing.
# A frozen build looks NEXT TO hib.exe (its own modules live in a throwaway
# unpack directory), so dropping a config\config.toml beside the .exe works the
# same as editing it in the source tree; with neither, the default below applies.
_BASE_DIR = (os.path.dirname(os.path.abspath(sys.executable)) if _FROZEN
             else os.path.dirname(os.path.abspath(__file__)))
_LOCAL_CONFIG = os.path.join(_BASE_DIR, "config", "config.toml")
_DEFAULT_FALLBACK_CONFIG = "%LOCALAPPDATA%\\hib\\config.toml"

# Argument template per known converter, used when the fallback config gives a
# bare `converter` path and no `args`.
_SOFFICE_ARGS = "--headless --convert-to pdf --outdir {outdir} {input}"
_ARGS_BY_TOOL = {          # keyed by the executable's stem, lowercased
    "pandoc": "{input} -o {output}",
    "soffice": _SOFFICE_ARGS,
    "libreoffice": _SOFFICE_ARGS,
    "swriter": _SOFFICE_ARGS,
}
_DEFAULT_ARGS = "{input} {output}"

# Sonde : docx2pdf (et sa dépendance tqdm, importée au niveau module) est-il
# importable dans CET interpréteur ? On s'en sert uniquement pour distinguer
# "convertisseur non installé" ('no_converter') de "conversion échouée"
# ('failed'). La conversion elle-même tourne dans un process enfant (plus bas)
# pour garder le timeout, la fenêtre masquée, et -- surtout -- l'isolation
# vis-à-vis du chemin macOS de docx2pdf, qui fait sys.exit(1) en cas d'échec
# (un SystemExit qui échapperait autrement à `except Exception`).
# NB : win32com est importé paresseusement dans docx2pdf, donc cette sonde
# réussit même sans pywin32 ni Word installés ; ces échecs-là remontent au
# moment de la conversion et sont rapportés en 'failed'.
try:
    import docx2pdf as _docx2pdf  # noqa: F401
except ImportError:
    _docx2pdf = None


# --- child process ---------------------------------------------------------

def _run_child(argv, timeout):
    """Run argv hidden, with a timeout. Returns (returncode, stderr_bytes, error)
    where `error` is a short phrase when the process could not be run or waited
    for at all (and returncode is then None). Never raises."""
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    except (OSError, ValueError) as e:
        # ValueError covers Popen's "embedded null character" (a NUL in a path);
        # keep the "never raises" guarantee so a bad path can never abort the add
        # and orphan the storage folder.
        return None, b"", "failed to run (%s)" % e
    try:
        _, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return None, b"", "timed out"
    return proc.returncode, err, None


def _reason(err):
    """Last non-empty line of the child's stderr, as a short ': ...' suffix.
    The converter's own message (Word missing, pywin32 missing, file locked) is
    far more actionable than a bare exit code. Best-effort: never raises."""
    try:
        text = (err or b"").decode("utf-8", "replace")
    except Exception:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # docx2pdf paints a tqdm progress bar on stderr; those lines are noise, and
    # they come AFTER the traceback, so they would hide the real message.
    lines = [ln for ln in lines if "it/s" not in ln and "%|" not in ln] or lines
    if not lines:
        return ""
    # Prefer the exception line ("...Error: ...") over whatever came last.
    raised = [ln for ln in lines if "Error" in ln or "Exception" in ln]
    last = (raised or lines)[-1]
    if len(last) > 200:
        last = last[:200] + "..."
    return ": " + last


# --- stage 1: Python (docx2pdf -> Word) ------------------------------------

def _child_python_flags():
    """Options d'isolation de ce process, à répercuter sur l'enfant (-I, ou
    -E/-s) : s'il a fallu `python -E` pour démarrer ici (PYTHONHOME/PYTHONPATH
    pollués par un autre logiciel), l'enfant en a besoin aussi."""
    if sys.flags.isolated:
        return ["-I"]
    flags = []
    if sys.flags.ignore_environment:
        flags.append("-E")
    if sys.flags.no_user_site:
        flags.append("-s")
    return flags


def convert_child(args):
    """Entry point of the conversion child process of a FROZEN build, reached as
    `hib.exe --hib-convert-docx <input> <output>` (hib.main dispatches it before
    anything else). Deliberately bare: docx2pdf's exception is left to propagate,
    so the traceback lands on stderr -- where _reason() reads it -- and the process
    exits non-zero, exactly like the `python -c` child of a source checkout."""
    if len(args) != 2:
        sys.stderr.write("usage: %s <input.docx> <output.pdf>\n" % CHILD_FLAG)
        return 2
    import docx2pdf
    docx2pdf.convert(args[0], args[1])
    return 0


def _word_child_argv(input_path, output_path):
    """The command that converts in a child process. A frozen build has no
    separate Python interpreter -- sys.executable IS hib.exe -- so it re-invokes
    itself with the private CHILD_FLAG instead of `python -c` (which the exe would
    parse as a file to add). Same timeout, same hidden window, same "any failure
    becomes a non-zero exit code" contract either way."""
    if _FROZEN:
        return [sys.executable, CHILD_FLAG, input_path, output_path]
    # There is no `python -m docx2pdf` entry point, hence -c.
    return [sys.executable] + _child_python_flags() + [
        "-c",
        "import sys, docx2pdf; docx2pdf.convert(sys.argv[1], sys.argv[2])",
        input_path, output_path,
    ]


def _convert_with_word(input_path, output_path, out):
    """Returns (True, None) on success, (False, message) otherwise -- the message
    has no trailing clause, the caller appends "continuing without a PDF" or
    "trying the fallback converter"."""
    # Run docx2pdf's convert() in a child process. This keeps the timeout and the
    # no-console-window behavior, and turns any docx2pdf failure -- exception,
    # AssertionError on a bad extension, or the macOS sys.exit(1) -- into a
    # non-zero exit code we handle as a failure.
    argv = _word_child_argv(input_path, output_path)

    out("Generating PDF...")
    code, err, error = _run_child(argv, _WORD_TIMEOUT)
    if error is not None:
        return False, "hib: PDF generation " + error
    if code != 0:
        return False, ("hib: PDF converter exited abnormally (code %s)%s"
                       % (code, _reason(err)))
    if os.path.exists(output_path):
        return True, None
    return False, "hib: converter reported success but produced no PDF"


# --- stage 2: fallback external converter ----------------------------------

def _read_text(path):
    """Read a config file, decoding tolerantly (UTF-8, then cp1252, then latin-1
    which never fails) like the rest of hib. Returns None if unreadable."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _toml_value(path, section, key):
    """One [section] key from a TOML file, or None (missing file, unreadable,
    malformed, absent key -- all the same to us: no fallback)."""
    text = _read_text(path)
    if text is None:
        return None
    try:
        value = hibtoml.parse(text).get_value(section, key)
    except Exception:
        return None
    return value or None


def fallback_config_path():
    """The file that declares the fallback converter. Its location is written in
    <this folder>/config/config.toml ([pdf] fallback_config); %VARS% expanded."""
    declared = _toml_value(_LOCAL_CONFIG, "pdf", "fallback_config")
    return os.path.expandvars(declared or _DEFAULT_FALLBACK_CONFIG)


def _tokenize(s):
    """Split a command template on whitespace, honoring double quotes (so a
    quoted path with spaces stays one token). Raises ValueError on an
    unterminated quote."""
    tokens, cur, in_quote, started = [], [], False, False
    for ch in s:
        if ch == '"':
            in_quote = not in_quote
            started = True
        elif not in_quote and ch in " \t":
            if started:
                tokens.append("".join(cur))
                cur, started = [], False
        else:
            cur.append(ch)
            started = True
    if in_quote:
        raise ValueError("unterminated quote")
    if started:
        tokens.append("".join(cur))
    return tokens


def _substitute(tokens, input_path, out_dir, output_path):
    subs = (("{input}", input_path), ("{output}", output_path),
            ("{outdir}", out_dir or os.path.dirname(output_path)))
    result = []
    for tok in tokens:
        for placeholder, value in subs:
            tok = tok.replace(placeholder, value)
        result.append(tok)
    return result


def fallback_argv(input_path, out_dir, output_path):
    """Build the fallback converter's argv from the operator's config. Returns
    (argv, exe) or None when no usable converter is declared. Never raises."""
    path = fallback_config_path()
    cmd = _toml_value(path, "pdf", "cmd")
    exe = _toml_value(path, "pdf", "converter")
    try:
        if exe:
            args = _toml_value(path, "pdf", "args")
            if not args:
                stem = os.path.splitext(os.path.basename(exe))[0].lower()
                args = _ARGS_BY_TOOL.get(stem, _DEFAULT_ARGS)
            tokens = [exe] + _tokenize(args)
        elif cmd:
            tokens = _tokenize(cmd)     # exe included in the template
        else:
            return None
    except ValueError:
        return None
    if not tokens:
        return None
    return _substitute(tokens, input_path, out_dir, output_path), tokens[0]


def _reconcile_output(out_dir, input_path, output_path):
    """soffice & co. name their output after the *input* stem, in --outdir. When
    that is not where hib wants it, move it. Returns True if the PDF is now at
    output_path."""
    if os.path.exists(output_path):
        return True
    produced = os.path.join(out_dir or os.path.dirname(output_path),
                            os.path.splitext(os.path.basename(input_path))[0] + ".pdf")
    if produced == output_path or not os.path.exists(produced):
        return False
    try:
        os.replace(produced, output_path)
    except OSError:
        return False
    return True


def _convert_with_fallback(argv, exe, input_path, out_dir, output_path, out):
    """Run the operator's converter. Returns True when the PDF exists afterwards.
    Prints its own failure message. Never raises."""
    code, err, error = _run_child(argv, _FALLBACK_TIMEOUT)
    if error is not None:
        out("hib: fallback converter %s; continuing without a PDF." % error)
        return False
    if code != 0:
        out("hib: fallback converter exited abnormally (code %s)%s; continuing "
            "without a PDF." % (code, _reason(err)))
        return False
    if _reconcile_output(out_dir, input_path, output_path):
        return True
    out("hib: fallback converter '%s' reported success but produced no PDF; "
        "continuing." % exe)
    return False


# --- entry point -----------------------------------------------------------

def generate_pdf(config, copy_name, input_path, out_dir, output_path, out):
    """Returns one of: 'already_pdf', 'generated', 'no_converter', 'unsupported',
    'failed'. `out` prints a status line. Best-effort: any error -> 'failed'.

    Conversion is done in Python (docx2pdf -> Word); if that yields no PDF, the
    external converter declared in the operator's fallback config is tried (see
    the module docstring). 'no_converter' means neither was available.

    NOTE: `config` is unused -- the [pdf] keys of hib's own config.toml are
    only kept for compatibility; the fallback converter is read from its own file. It is kept for
    call-site compatibility."""
    ext = sanitize.extension(copy_name)
    if ext.lower() == ".pdf":
        return "already_pdf"          # the stored copy already IS the PDF
    if not uri.is_office_ext(ext):
        return "unsupported"

    status, message = "no_converter", None
    if _docx2pdf is not None:
        ok, message = _convert_with_word(input_path, output_path, out)
        if ok:
            return "generated"
        status = "failed"

    fallback = fallback_argv(input_path, out_dir, output_path)
    if fallback is None:
        if message:
            out(message + "; continuing without a PDF.")
        return status
    argv, exe = fallback

    if message:
        out(message + "; trying the fallback converter '%s'..." % exe)
    else:
        out("Generating PDF with '%s'..." % exe)
    if _convert_with_fallback(argv, exe, input_path, out_dir, output_path, out):
        return "generated"
    return "failed"
