# hib -- command reference

This is the detailed reference. For an overview, installation and a quick start,
see the [README at the repository root](../README.md).

hib archives documents indexed by tags. Each entry gets a randomly named storage
folder holding a copy of the source file (and its PDF), a JSON metadata record and
an HTML card, and is selected afterwards by its citekey or its reference. Opening
uses `os.startfile` (native Windows ShellExecute): no PowerShell, no base64
encoded commands.

## Requirements

Python 3 (3.6+). On Windows the `py -3` launcher is used when present, else
`python`. `tomllib` is NOT required (a small TOML parser is bundled,
`hibtoml.py`).

Everything is stdlib-only except the Word -> PDF conversion, which is done **in
Python** by `docx2pdf` (it drives an installed Microsoft Word through COM; an
external converter is only used as an optional fallback, see below):

```
py -3 -m pip install -r requirements.txt
```

It is optional: without it, `hib add` / `hib pdf` just skip the PDF (status
`skipped (docx2pdf is not installed)`) instead of failing -- and a PDF you
already have can be attached by hand (see *Attaching a PDF you already have*).

### Fallback converter (optional)

When the Python conversion produces no PDF -- Word not installed, `docx2pdf` not
installed, a format Word will not open -- hib falls back to an external converter
(pandoc, soffice, ...). Two files, so the machine-specific part stays out of the
source tree:

1. `code/config/config.toml` (next to the sources; for `hib.exe`,
   `config\config.toml` next to the exe) says **where** the declaration lives
   (`%VARS%` expanded; this is also the built-in default when the file or the key
   is missing):

   ```toml
   [pdf]
   fallback_config = '%LOCALAPPDATA%\hib\config.toml'
   ```

2. that file names the **executable**:

   ```toml
   [pdf]
   converter = 'C:\Program Files\Pandoc\pandoc.exe'
   args      = '{input} -o {output}'   # optional: inferred for pandoc/soffice/libreoffice
   # or the whole command line in one string (the legacy key, so existing
   # configs work as-is):
   # cmd = '"C:\...\soffice.exe" --headless --convert-to pdf --outdir {outdir} {input}'
   ```

Placeholders: `{input}`, `{output}`, `{outdir}`. They are substituted *after*
tokenizing, so a quoted path with spaces stays one argument and nothing is ever
handed to a shell. Converters that name their output after the input (soffice)
are reconciled with the name hib expects. No file, or no converter in it, means
no fallback -- hib just skips the PDF.

## Setup

Pick one:

- **PowerShell function (recommended):** add to your `$PROFILE`
  (`New-Item -ItemType File -Path $PROFILE -Force` creates it if needed):
  ```powershell
  . C:\path\to\hib\code\hib.ps1
  ```
  Then `hib <args>` works everywhere, from any directory, without touching `PATH`.
  Windows will not run that profile under the default **Restricted** execution
  policy; once per machine, no admin needed:
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```

- **Batch launcher:** put the `code` folder on your `PATH` and use `hib.bat`
  (`hib o <citekey>`, etc.). No execution policy applies to a `.bat`, so this is
  the way in on a PC where group policy locks PowerShell down.

- **Standalone `hib.exe` (no Python needed):** build it once with
  `py -3 build_exe.py` (see [Building hib.exe](#building-hibexe)), then put
  `bin\hib.exe` on your `PATH`. Read the caveats first -- antivirus software
  often flags unsigned one-file binaries.

Both wrappers drive `hib.exe` when one sits next to them (or at `.\bin\hib.exe`,
where the default one-file build puts it), else the Python sources. A
`--onedir` build (`bin\hib\hib.exe`) is not picked up by the wrappers: put
that folder on your `PATH` instead. They run Python with `-E -s` (ignore `PYTHONPATH`,
`PYTHONHOME` and the user site directory), so a foreign Python installation set
by another application cannot get mixed in.

### Configuration

By default hib reads `%LOCALAPPDATA%\hib\config\config.toml`. Override it with
the `HIB_CONFIG` environment variable pointing at a `.toml` (or at a legacy
`pathToFilesLocation.txt`). On the first run with no config at all, hib writes an
empty template there and stops; fill in the storage paths and run it again. A
legacy `pathToFilesLocation.txt` found in that folder is read and migrated to
`config.toml` (the `.txt` is kept).

A commented example is in [`config/config.example.toml`](config/config.example.toml):

```toml
[storage]
file  = 'C:\hib\files'   # stored copies: one folder per entry
html  = 'C:\hib\html'    # the HTML cards
json  = 'C:\hib\json'    # the per-entry JSON metadata
# trash = 'C:\hib\trash' # optional; defaults to <file>\trash

[backup]
target = 'D:\hib-backup' # default destination of `hib backup`
```

Single-quoted strings keep backslashes as-is. Storage and backup paths are taken
literally (no `%VARS%` expansion).

The item types offered by `add` come from `itemTypes.txt`, in the same folder as
the config (created with the built-in defaults when missing). Edit it to add
your own types, one per line.

`hib config` prints the paths hib resolved and flags any folder that does not
exist.

### `hib cd` really changes the directory

`cd` / `cdr` / `cdf` print nothing but the target folder on stdout (prompts and
errors go to stderr), and both wrappers capture that line and move the shell:
`hib.ps1` with `Set-Location`, `hib.bat` with `cd /d`. A batch file can only do
that when it is typed at a **cmd.exe** prompt -- it then runs inside that very
cmd.exe. Called from PowerShell it is a child process and moves nothing, so use
the function there. Either way, a cancelled pick list, an unknown citekey or
`-n` leaves the current directory untouched.

## Commands

```
hib                    add an entry (interactive)
hib <source-file>      add that file directly (skips the source prompt)
hib add [<source-file>] same as above
hib update <citekey>   re-edit an entry's metadata (rewrites card + JSON, renaming on change)
hib update -html [-n]  re-render ALL cards from their JSON (no editing); -n lists only
hib update -json-names [-n]            rename ALL metadata files after their reference
hib update -json <citekey>             rewrite an entry's JSON from its hand-edited HTML card
hib update -remote <citekey> [<path>]  set/replace/remove ONLY the remote path
hib update -ctk <citekey> [<new>]      change ONLY the citekey
hib delete <citekey>   move an entry (card, storage folder, JSON) to the trash (not erased)
hib purge [-n]         move orphan cards/folders (referenced by no JSON) to the trash; -n lists only
hib backup [<dir>] [-n] incremental copy of every item into <dir> (default: [backup] target); -n lists only
hib backup --purge old [<dir>] [-n]    delete for good from the backup every entry tagged old; asks first
hib pdf  <citekey>     (re)generate the PDF from the stored copy and refresh the card
hib pdf  <citekey> <file.pdf>          attach an EXISTING PDF (copied into the entry's folder)
hib config             print the storage paths hib uses (flags any missing folder)
hib o    <citekey>     open the stored file in its default app (else its folder)
hib opdf <citekey>     open the local PDF (else its folder)
hib or   <citekey>     open the remote source file (else its folder)
hib oe / oer <citekey> open the local / remote folder in Explorer
                       aliases: openfolder / openremotefolder
hib of                 open the HTML directory in Explorer
hib cd / cdr <citekey> cd into the local / remote folder (via hib.ps1 / hib.bat)
hib cdf                cd into the HTML directory
hib help               print the usage
```

Selector (for every command that takes one -- open/navigate, `update`, `delete`,
`pdf`): a bare value matches the **citekey or the reference, interchangeably** --
exact on either wins, and a value that is exact for neither lists the partial
matches (of both fields) to pick from. Restrict the match with `-citekey`
(short form: `-ctk`) / `-ref` / `-html <value>`. Add `-n` / `--dry-run` to print the target without
launching.

> **One exception:** `-ctk` **immediately after `update`** is the re-key mode
> (`hib update -ctk <citekey|reference> [<new citekey>]`), not the selector
> shorthand. Use the long `-citekey <value>` to select an entry for the
> interactive update; `-ctk` keeps its selector meaning everywhere else, and
> even inside the mode itself (`hib update -ctk -ctk <value> <new>`).

### Adding an entry

`add` optionally imports field defaults from a `.bib` file, then prompts for the
item type (matched against the extensible `itemTypes.txt` table — `?` lists it, a
number picks, an unknown value is confirmed), title, short title, version, authors,
date, tags, description and reference, copies the source into a fresh
`a<yyyymmdd><8 hex>` folder under the file-storage path, best-effort-generates a
PDF, then writes the HTML card and the JSON metadata.

PDF generation runs **in Python** (`docx2pdf` -> Word via COM, in a child
interpreter with a 60 s timeout and no console window), with an optional external
converter as a fallback (see [Fallback converter](#fallback-converter-optional)).
`powershell -EncodedCommand` (the base64 form antivirus software flags) is never
used. The `[pdf] powershell` / `cmd` keys of the main `config.toml` are read and
written back unchanged, for compatibility with existing configs, but hib does not
run them.

### Changing a citekey

```
hib update -ctk <citekey|reference> [<new citekey>]
```

Only the citekey changes: every metadata field, the stored file, its folder, the
PDF and the remote path stay exactly as they are. **Nothing is renamed** — the
JSON is named after the reference and the card after the title — but the card is
re-rendered so its Citekey line and its Copy Citekey button follow. With no
`<new citekey>`, the current one is offered as the prompt default.

The value is folded the same way a generated citekey is (`rapport final 2026` ->
`Rapportfinal2026`); the adjustment is printed when it differs from what you
typed, and a value with nothing usable left is refused rather than replaced by an
invented one. hib tolerates two entries sharing a citekey but says so, since a
bare selector will then list both.

### The reference identifies the entry

The **reference** is hib's internal identifier. It is chosen once, when the entry
is added, and never changes afterwards:

- the metadata file is named after it — `<reference>.json`, with only what a file
  name cannot hold folded away (so `report_Doc__20260603` keeps its `__`);
- `hib update <citekey>` does **not** re-prompt it, so the JSON is never renamed
  by an edit;
- `hib update -json <citekey>` ignores the Reference line of a hand-edited card;
- there is deliberately no command to change it. Re-add the entry if you need a
  different one.

Only the *citekey* is free to change (`hib update -ctk`), which is why it is not
what names the file. Two entries may still end up with the same reference
(the same document added twice on the same day): nothing is overwritten, the
second file is numbered `_1`, and `add` says so.

Archives created by earlier versions name the metadata file after the citekey.
They keep working — hib finds entries by reading the files, never by their names
— and this migrates them:

```
hib update -json-names -n     # list what would be renamed
hib update -json-names        # rename them
```

Only file names change: the JSON content, the cards and the stored files are left
alone.

### Editing a card by hand

The card is plain HTML. After editing its fields in a text editor, write them
back to the JSON with:

```
hib update -json <citekey>
```

The reverse, `hib update -html`, rewrites every card from its JSON (see
[Card buttons](#card-buttons)).

### Deleting and purging

`hib delete <citekey>` moves the entry's card, storage folder and JSON into the
trash folder (`[storage] trash`, default `<file>\trash`); nothing is erased.
`hib purge` moves to the trash the cards and storage folders that no JSON
references any more; `-n` only lists them.

### Backing up the archive

```
hib backup [<target-dir>] [-n]
```

Copies the archive into a backup folder, incrementally. The folder is the one
given on the command line, else the `[backup] target` key of the config:

```toml
[backup]
target = 'E:\hib-backup'
```

The path is taken literally, like the storage paths (no `%VARS%` expansion).
With neither, hib stops with an error. The target is created if needed; one
inside a storage folder (or containing one) is refused.

The target mirrors the three storage folders by name:

```
<target>\json\<name>.json     the item's JSON
<target>\html\<card>.html     its card
<target>\file\<folder>\...   its whole storage folder, sub-folders included
```

- **What is an item:** every readable JSON of the json folder. Only what a JSON
  references is copied; orphan cards/folders are counted in the summary but not
  backed up (see `hib purge`). An unreadable JSON is reported and skipped (its
  previous backup copy is left alone); the rest is still backed up and hib exits
  with code 1.
- **`nobackup`:** an item tagged `nobackup` (any case) is left out entirely --
  no JSON, no card, no folder.
- **Incremental:** a file is copied only when it is missing in the target or
  differs: other size, or an mtime more than 2 s away (FAT/exFAT drives round
  to 2 s). JSONs and cards are also compared byte for byte. Copies keep the
  original mtime.
- **Nothing is ever deleted in the target.** Instead, a copy that no longer
  matches a live item gets the tag **`old`**: a JSON whose name was not backed
  up in this run (item deleted, tagged `nobackup` since, or its JSON renamed),
  its card, and any card no JSON of the backup refers to (a renamed card). A
  renamed item thus leaves its old JSON/card in the backup, tagged `old`, next
  to the new ones. A card that belongs to a live item is never tagged, even
  when an old JSON points to the same card name.
  In a card, `old` is inserted in the Tags block and the keywords line; the
  card is not re-rendered, so its links stay as they were. The tag is added
  once. An item that comes back (restored, `nobackup` removed) loses it on the
  next run: its archive JSON and card replace the tagged copies.
- As in `purge`, links/junctions are skipped, the trash/json/html folders are
  never copied when they sit under the file folder, and card/folder paths are
  read inside their storage folder only (a JSON written under another drive
  letter is matched by name inside the configured folder).

`-n` / `--dry-run` lists what would be copied and tagged, and writes nothing.
The run never asks for confirmation.

#### Purging the old copies

```
hib backup --purge old [<target-dir>] [-n]
```

The only command that deletes anything in the backup, and only there: it does
not run a backup, and the same checks as the backup refuse a target that
overlaps the archive or whose `json`/`html`/`file` folder is a link/junction.
`old` is the only word accepted after `--purge`.

- Every JSON of `<target>\json` tagged `old` (any case; a hand-written
  `"tags": "old"` string counts too) is deleted, with its card
  (`<target>\html\<card>`) and its whole storage folder
  (`<target>\file\<folder>`).
- A card or folder that a JSON of the backup **not** tagged `old` also names is
  **kept**: a renamed item shares its folder (and maybe its card name) between
  the old copy and the live one. The preview lists those as kept.
- Every card of `<target>\html` tagged `old` that no such live JSON names is
  deleted too (for instance the old card of a renamed card).
- If any JSON of the backup cannot be read, the cards and folders it names
  cannot be known: the purge stops, deletes **nothing**, lists those JSONs and
  exits with code 1. Fix or remove them, then re-run.
- Links/junctions are never followed: one met inside a folder being deleted is
  removed as a link, its target is left untouched. Read-only copies are deleted
  too.
- Folders go first, then cards, then JSONs; a JSON whose card or folder could
  not be deleted is kept, so a re-run finds that entry again. The same goes
  for a card or folder that exists but cannot be checked (access denied, path
  too long) or has the wrong type: it is reported as a failure and its JSON is
  kept.
- Names are compared the way Windows resolves them: case-insensitively, and
  without trailing dots or spaces (`Live.html.` is `Live.html`), so a
  hand-edited old JSON can never reach the card or folder of a live item.

hib shows the list (`[json]`, `[card]`, `[folder]` lines, then what is kept
because it is shared) and asks `Delete these old entries from the backup
permanently? (y/N)` -- anything but `y` deletes nothing. `-n` / `--dry-run`
only lists. A summary of what was deleted ends the run; the exit code is 1 if
anything failed.

### Attaching a PDF you already have

When the conversion cannot be done -- a scanned document, a publisher's PDF, an
`.xlsx` Word will not open, or simply a PDF you produced yourself -- give the PDF
to `hib pdf`:

```
hib pdf <citekey|reference> "C:\path\to\the file.pdf"
```

The PDF is **copied** into the entry's storage folder, under the name hib reserves
for it (the stored copy's stem + `.pdf`, i.e. the `pdfLocalPath` already recorded
in the JSON), so the entry stays self-contained: nothing points at the original,
which is left untouched. Then the card is re-rendered, which is what makes the
**Local PDF** button appear, and `hib opdf <citekey>` starts working.

* A source that is not a `.pdf` is refused -- the button and `hib opdf` expect one.
* Replacing a PDF already attached is always confirmed (`Replace it? (y/n)`): a
  generated PDF is reproducible, one you attached by hand is not.
* The JSON is rewritten only when it had no `pdfLocalPath` (an entry added by hib
  always has one, so the usual case touches only the copy and the card).
* Stored paths are checked first, exactly as generation does: a JSON whose folder
  escapes the storage root, or uses characters outside the sanitized alphabet, is
  refused rather than written into.

`hib pdf <citekey>` with no path keeps its original meaning -- generate from the
stored copy.

### Card buttons

Each card carries **Copy Citekey** and **Copy Reference** buttons next to those
two values, alongside the Local File / Open File Location / Copy Path /
Copy Folder Path / Local PDF / remote ones. Each value sits in an id'd `<span>`
(`citekeyValue`, `referenceValue`) that the `copyPath` helper reads from the DOM,
so nothing is interpolated into an `onclick` attribute and a reference containing
a quote cannot break the markup.

`cardparse` reads the reference from the span when it is there and falls back to
the plain `<strong>Reference:</strong> ...` form, so `hib update -json` keeps
working on cards written before the buttons existed.

Cards created earlier do not have the buttons. Retrofit them all from their JSON:

```
hib update -html -n     # list what would be refreshed
hib update -html        # rewrite the cards
```

That rewrites each card from its JSON, so any hand-edit made in a card and not
yet synced back (`hib update -json <citekey>`) is lost — sync first if in doubt.

## Building hib.exe

```
py -3 -m pip install pyinstaller docx2pdf
py -3 build_exe.py             # -> bin\hib.exe  (~12 MB, one file)
py -3 build_exe.py --onedir    # -> bin\hib\    (a folder; starts instantly;
                               #    not used by hib.ps1/hib.bat, see above)
```

Everything travels inside the binary, docx2pdf and pywin32 included, so Word
conversion works on a machine with no Python at all. Three caveats:

- **Antivirus.** A PyInstaller one-file binary is the most heuristically-flagged
  shape there is, and an unsigned `.exe` may be quarantined or deleted. Test it on
  the target machine; `hib.bat` / `hib.ps1` over the plain `.py` files remain the
  safe fallback.
- **Startup.** A one-file exe unpacks into `%TEMP%` on every run (roughly
  0.5-1 s), and the PDF conversion child pays it again. `--onedir` removes that
  cost.
- **Snapshot.** The exe embeds a copy of the code; rebuild after every change.

Config is *not* bundled: the exe still reads `%LOCALAPPDATA%\hib\config\config.toml`
(or `HIB_CONFIG`) and `itemTypes.txt` at run time, so it shares one archive with
the source checkout.

Frozen builds convert PDFs by re-invoking themselves: `sys.executable` is
`hib.exe`, not a Python interpreter, so `pdfgen` spawns
`hib.exe --hib-convert-docx <in> <out>` (a private flag `hib.main` dispatches
before anything else) instead of `python -c ...`. Same 60 s timeout, same hidden
window, same "any failure becomes a non-zero exit code".

## Source layout

- config (TOML + legacy `.txt`, migration, bootstrap) — `config.py` / `hibtoml.py`
- entry model + selector (citekey exact + partial, ref, html) — `model.py` / `selector.py`
- command dispatch, open / navigate commands — `hib.py`
- add (interactive, citekey, copy, HTML card, JSON, best-effort PDF) — `addcmd.py` + `html.py` / `metadata.py` / `cmdline.py` / `pdfgen.py`
- `.bib` import — `bib.py`; item-type table — `item_types.py`
- Word → PDF in Python (`docx2pdf` / Word COM) with a declared external converter as fallback — `pdfgen.py`
- update (re-edit, `-html`, `-json`, `-json-names`, `-remote`, `-ctk`) — `updcmd.py` / `cardparse.py`
- delete → trash — `delcmd.py` / `trash.py`
- purge → trash — `purgecmd.py`
- backup and `--purge old` — `backupcmd.py`
- pdf (regenerate, or attach an existing PDF) — `pdfcmd.py`
- standalone `hib.exe` (PyInstaller, frozen-aware PDF conversion) — `build_exe.py`

## Tests

From the `code` folder:

```
py -3 -m unittest -q
```

or from the repository root:

```
py -3 -m unittest discover -s code -q
```

The PDF conversion has its own three-level suite in `test_docx2pdf_convercion.py`
(mocked child, real child with a fake `docx2pdf` injected, and a real Word
conversion enabled with `HIB_PDF_INTEGRATION=1`).
