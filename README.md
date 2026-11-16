# hib

**hib** is a small command-line tool for Windows that archives documents and
indexes them by tags. Every document you add becomes an *entry* made of:

- a **storage folder** with a random name (`a<yyyymmdd><8 hex>`) that holds a copy
  of the source file and, when it can be generated, its PDF;
- a **JSON metadata record** (item type, title, authors, date, tags, description,
  citekey, reference, local and remote paths);
- an **HTML card** you can open in a browser, with buttons to open the file, its
  folder or its PDF and to copy its citekey, reference or path.

Entries are found again by **citekey** (e.g. `Smith2026`) or by **reference**,
exact or partial: `hib o smith` opens the stored file, `hib cd smith` moves your
shell into its folder.

hib is written in Python 3, uses the standard library only (the optional Word to
PDF conversion excepted) and needs no installer.

## Features

- Interactive `add`, with optional field import from a BibTeX (`.bib`) file and an
  extensible item-type list (book, report, journalArticle, ...).
- Word -> PDF conversion through an installed Microsoft Word (`docx2pdf`), with an
  optional external converter (pandoc, LibreOffice, ...) as a fallback; or attach
  a PDF you already have.
- Open the stored file, its PDF, its folder, or the original (remote) file; `cd`
  into the entry's folder from PowerShell or cmd.exe.
- Selectors by citekey or reference, exact or partial, with a numbered pick list.
- Re-edit an entry's metadata, change its citekey, set its remote path, or sync a
  hand-edited HTML card back to its JSON.
- `delete` and `purge` never erase: they move things to a trash folder.
- Incremental `backup` to another folder or drive, with `nobackup` / `old` tags
  and an explicit `--purge old` to clean the backup.
- Optional standalone `hib.exe` built with PyInstaller.

## Requirements

- Windows (opening and Explorer integration use the Windows shell).
- Python 3.6 or newer, from [python.org](https://www.python.org/) (the `py`
  launcher is used when present, else `python`).
- Optional, for Word -> PDF conversion: Microsoft Word and the `docx2pdf` package:

  ```
  py -3 -m pip install -r code/requirements.txt
  ```

  Without it, hib simply skips the PDF.

## Installation

Clone or download the repository, for example to `C:\tools\hib`. The program is
in the `code` folder. Then choose how to call it:

**PowerShell (recommended).** Add this line to your PowerShell profile
(`notepad $PROFILE`; create it with `New-Item -ItemType File -Path $PROFILE -Force`
if it does not exist):

```powershell
. C:\tools\hib\code\hib.ps1
```

Open a new PowerShell window and `hib` works from any directory, including
`hib cd <citekey>`. If PowerShell refuses to load the profile, allow local scripts
once (no admin rights needed):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**cmd.exe.** Add `C:\tools\hib\code` to your `PATH` and use `hib.bat`. `hib cd`
works there too when typed at a cmd.exe prompt.

**Standalone hib.exe (optional).** To run hib on a machine without Python:

```
py -3 -m pip install pyinstaller docx2pdf
py -3 code\build_exe.py          # -> code\bin\hib.exe
```

`hib.ps1` and `hib.bat` use `hib.exe` automatically when it is next to them or at
`bin\hib.exe` (the default one-file build; a `--onedir` build is not picked up). Note that antivirus software may flag an unsigned PyInstaller binary;
the plain Python setup above avoids that.

## Configuration

hib reads `%LOCALAPPDATA%\hib\config\config.toml`, or the file named by the
`HIB_CONFIG` environment variable. On the first run it creates an empty template
there and stops: fill in your folders, then run it again.

Start from [`code/config/config.example.toml`](code/config/config.example.toml):

```toml
[storage]
file  = 'C:\hib\files'    # stored copies: one folder per entry
html  = 'C:\hib\html'     # the HTML cards
json  = 'C:\hib\json'     # the JSON metadata records
# trash = 'C:\hib\trash'  # optional; defaults to <file>\trash

[backup]
target = 'D:\hib-backup'  # default destination of `hib backup`
```

Use single quotes so Windows backslashes are kept as-is. `hib config` shows the
paths in use and flags any missing folder. The list of item types lives in
`itemTypes.txt` next to the config (created on first use) and can be extended.

## Quick start

```powershell
hib config                         # check the configured folders
hib "C:\docs\Annual report.docx"   # add a document (answers a few prompts)
hib o annual                       # open the stored copy (partial match)
hib opdf annual                    # open its PDF
hib oe annual                      # open its folder in Explorer
hib cd annual                      # cd into its folder
hib of                             # open the folder of HTML cards
hib update annual                  # edit its metadata
hib backup E:\hib-backup           # incremental backup
```

## Commands

| Command | Purpose |
| --- | --- |
| `hib`, `hib <file>`, `hib add [<file>]` | add an entry |
| `hib update <sel>` | re-edit an entry's metadata |
| `hib update -ctk <sel> [<new>]` | change only the citekey |
| `hib update -remote <sel> [<path>]` | set, replace or remove the remote path |
| `hib update -json <sel>` | write a hand-edited card back to its JSON |
| `hib update -html [-n]` | re-render all cards from their JSON |
| `hib update -json-names [-n]` | rename all metadata files after their reference |
| `hib delete <sel>` | move an entry to the trash |
| `hib purge [-n]` | move orphan cards and folders to the trash |
| `hib backup [<dir>] [-n]` | incremental backup |
| `hib backup --purge old [<dir>] [-n]` | delete entries tagged `old` from the backup |
| `hib pdf <sel> [<file.pdf>]` | regenerate the PDF, or attach an existing one |
| `hib o` / `opdf` / `or <sel>` | open the stored file / its PDF / the remote file |
| `hib oe` / `oer <sel>` | open the local / remote folder in Explorer |
| `hib of` | open the HTML cards folder |
| `hib cd` / `cdr <sel>`, `hib cdf` | cd into the local / remote folder, or the HTML folder |
| `hib config` | show the paths in use |
| `hib help` | print the usage |

`<sel>` is a citekey or a reference (partial values give a pick list); restrict it
with `-citekey` (`-ctk`), `-ref` or `-html <value>`. `-n` / `--dry-run` shows what
would happen without doing it.

The full reference -- every option, the backup rules, the PDF fallback converter,
building `hib.exe` -- is in [code/README.md](code/README.md).

## Running the tests

```
cd code
py -3 -m unittest -q
```

or, from the repository root, `py -3 -m unittest discover -s code -q`.

## License

[MIT](LICENSE) -- Copyright (c) 2026 Sylvain Rigal.
