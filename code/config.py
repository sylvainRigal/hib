"""hib configuration: read config.toml (or the legacy pathToFilesLocation.txt),
and resolve where hib's files live.
"""
import os
import sys

import hibtoml

CONFIG_SUBDIR = os.path.join("hib", "config")   # under %LOCALAPPDATA%


class ConfigError(Exception):
    pass


class Config(object):
    def __init__(self, file_path, html_path, json_path,
                 trash_path=None, pdf_ps=None, pdf_cmd=None, backup_target=None):
        self.file_storage_path = file_path
        self.html_storage_path = html_path
        self.json_storage_path = json_path
        self.trash_storage_path = trash_path      # None -> default <file>/trash
        # [pdf] powershell/cmd: an external converter command (soffice, pandoc...).
        # hib does NOT use them -- it converts Word -> PDF in Python
        # (pdfgen.py -> docx2pdf -> Word). They are still parsed, and preserved by
        # the legacy-.txt migration, so an existing config that declares them
        # survives a round-trip unchanged.
        self.pdf_converter_ps = pdf_ps            # "" kept distinct from None
        self.pdf_converter_cmd = pdf_cmd
        # [backup] target: default destination of `hib backup` (None -> must be
        # given on the command line). Taken literally, like the storage paths.
        self.backup_target = backup_target


def _nonempty(v):
    return v if v else None   # None or "" -> None


# --- parsers ---------------------------------------------------------------

def parse_toml(text):
    t = hibtoml.parse(text)
    file_path = _nonempty(t.get_value("storage", "file"))
    html_path = _nonempty(t.get_value("storage", "html"))
    json_path = _nonempty(t.get_value("storage", "json"))
    if file_path is None:
        raise ConfigError("missing [storage] file")
    if html_path is None:
        raise ConfigError("missing [storage] html")
    if json_path is None:
        raise ConfigError("missing [storage] json")
    return Config(
        file_path, html_path, json_path,
        trash_path=_nonempty(t.get_value("storage", "trash")),
        pdf_ps=t.get_value("pdf", "powershell"),
        pdf_cmd=t.get_value("pdf", "cmd"),
        backup_target=_nonempty(t.get_value("backup", "target")),
    )


def parse_legacy(text):
    """The old `pathToFilesLocation.txt` format.
    `<label>: <value>`, split on the first ':', one wrapping pair of quotes
    stripped, routed by the keyword the label starts with. Rejects TOML content
    (a label containing '=' means a drive colon was mis-split)."""
    file_path = html_path = json_path = trash_path = None
    pdf_ps = pdf_cmd = None
    for raw in text.split("\n"):
        line = raw.strip(" \t\r")
        if not line:
            continue
        colon = line.find(":")
        if colon < 0:
            continue
        label = line[:colon].strip(" \t")
        if "=" in label:
            raise ConfigError("looks like TOML, not the legacy format: " + line)
        value = line[colon + 1:].strip(" \t")
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        if label.startswith("file"):
            file_path = value
        elif label.startswith("html"):
            html_path = value
        elif label.startswith("json"):
            json_path = value
        elif label.startswith("trash"):
            trash_path = value
        elif label.startswith("pdf"):
            if "(powershell)" in label:
                pdf_ps = value
            elif "(cmd)" in label:
                pdf_cmd = value
    if file_path is None:
        raise ConfigError("missing file storage path")
    if html_path is None:
        raise ConfigError("missing html storage path")
    if json_path is None:
        raise ConfigError("missing json storage path")
    return Config(file_path, html_path, json_path,
                  trash_path=_nonempty(trash_path),
                  pdf_ps=pdf_ps, pdf_cmd=pdf_cmd)


def parse_by_ext(path, text):
    """.toml (case-insensitive) -> TOML parser; anything else -> legacy."""
    if os.path.splitext(path)[1].lower() == ".toml":
        return parse_toml(text)
    return parse_legacy(text)


# --- resolution / migration / bootstrap ------------------------------------

def _read(path):
    # Read bytes and decode tolerantly: UTF-8
    # (BOM-stripped) first, then cp1252 (Notepad's ANSI on a Western Windows),
    # then latin-1 which never fails. A strict UTF-8 decode would crash on a
    # hand-edited config whose path has an accented ANSI byte (e.g. 0xE9 'é').
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _render_toml(config):
    storage = {
        "file": config.file_storage_path,
        "html": config.html_storage_path,
        "json": config.json_storage_path,
    }
    if config.trash_storage_path:
        storage["trash"] = config.trash_storage_path
    pdf = {}
    if config.pdf_converter_ps is not None:
        pdf["powershell"] = config.pdf_converter_ps
    if config.pdf_converter_cmd is not None:
        pdf["cmd"] = config.pdf_converter_cmd
    return hibtoml.render(storage, pdf)


def _migrate(config, toml_path, out):
    if os.path.exists(toml_path):       # never clobber an existing config.toml
        return
    text = _render_toml(config)
    try:
        parse_toml(text)                # never write a config.toml that won't re-parse
    except Exception:
        return
    try:
        os.makedirs(os.path.dirname(toml_path), exist_ok=True)
        with open(toml_path, "w", encoding="utf-8") as f:
            f.write(text)
        out("hib: migrated your config to %s (the old .txt is kept)." % toml_path)
    except OSError as e:
        out("hib: note: could not write %s (%s); still using the legacy config." % (toml_path, e))


def _bootstrap(toml_path, out):
    try:
        os.makedirs(os.path.dirname(toml_path), exist_ok=True)
        with open(toml_path, "w", encoding="utf-8") as f:
            f.write(hibtoml.TEMPLATE)
        out("hib: no config found. Created a template at %s." % toml_path)
        out("Fill in your storage paths, then re-run hib.")
    except OSError as e:
        out("hib: no config found and could not create %s (%s)." % (toml_path, e))


def load(environ, out=None):
    """Resolve, read and parse the config. Returns (Config, config_dir), or None
    after printing a message when hib cannot proceed."""
    if out is None:
        out = lambda msg: print(msg)

    # 1) HIB_CONFIG override (set and non-empty); format by extension.
    hib_config = environ.get("HIB_CONFIG")
    if hib_config:
        try:
            text = _read(hib_config)
        except OSError as e:
            out("hib: cannot read config '%s' (%s)." % (hib_config, e))
            return None
        try:
            config = parse_by_ext(hib_config, text)
        except (ConfigError, hibtoml.TomlError) as e:
            out("hib: invalid config '%s' (%s)." % (hib_config, e))
            return None
        return config, os.path.dirname(hib_config) or "."

    local = environ.get("LOCALAPPDATA")
    if not local:
        out("hib: cannot locate the config (set HIB_CONFIG or LOCALAPPDATA).")
        return None
    config_dir = os.path.join(local, CONFIG_SUBDIR)
    toml_path = os.path.join(config_dir, "config.toml")
    txt_path = os.path.join(config_dir, "pathToFilesLocation.txt")

    # 2) config.toml.
    if os.path.exists(toml_path):
        try:
            config = parse_toml(_read(toml_path))
        except (OSError, ConfigError, hibtoml.TomlError) as e:
            out("hib: invalid config '%s' (%s)." % (toml_path, e))
            return None
        return config, config_dir

    # 3) legacy .txt -> parse and migrate.
    if os.path.exists(txt_path):
        try:
            config = parse_legacy(_read(txt_path))
        except (OSError, ConfigError) as e:
            out("hib: invalid config '%s' (%s)." % (txt_path, e))
            return None
        _migrate(config, toml_path, out)
        return config, config_dir

    # 4) nothing yet -> write a template and stop.
    _bootstrap(toml_path, out)
    return None
