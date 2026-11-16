"""Locate entries by selector.

A BARE value (the default for every command) is matched against the citekey AND
the reference, interchangeably: exact on either wins, and failing any exact match,
case-insensitive SUBSTRING on either offers a pick list. The explicit flags stay
strict for disambiguation: -citekey (short form -ctk) matches citekeys only
(exact, then substring), -ref references only (exact), -html by full path then
basename. Exact/full always win over partial.

NOTE: matching a bare value against the reference too only widens what resolves;
the files hib writes are unaffected.
"""
import os

import model
import locate

KIND_LABEL = {"any": "citekey/reference", "citekey": "citekey",
              "reference": "reference", "html": "html path"}


def parse_selector(args, out):
    """Parse args after a subcommand into (kind, value): `<value>` (citekey OR
    reference), or -citekey (= -ctk) / -html / -ref <value> to restrict the match.
    None (after a message) when nothing is given or a flag is malformed."""
    if not args or not args[0]:
        out("hib: needs a selector: <citekey or reference>  "
            "(or -citekey/-ctk / -html / -ref <value>)")
        return None
    a0 = args[0]
    if a0.startswith("-"):
        kind = {"-citekey": "citekey", "-ctk": "citekey",     # -ctk: short -citekey
                "-html": "html", "-ref": "reference"}.get(a0)
        if kind is None:
            out('hib: unknown option "%s" (use -citekey/-ctk / -html / -ref).' % a0)
            return None
        if len(args) < 2 or not args[1]:
            out('hib: %s needs a value.' % a0)
            return None
        return kind, args[1]
    return "any", a0


class Found(object):
    def __init__(self, json_path, meta):
        self.json_path = json_path
        self.meta = meta


def find_entries(config, kind, value):
    json_dir = config.json_storage_path.rstrip("\\/")
    primary = []    # exact citekey/ref, full html-path
    fallback = []   # partial citekey, html basename-only
    try:
        names = sorted(os.listdir(json_dir))
    except OSError:
        return []
    for name in names:
        if not name.endswith(".json"):     # case-sensitive on purpose
            continue
        full = os.path.join(json_dir, name)
        try:
            with open(full, encoding="utf-8") as f:
                md = model.parse(f.read())
        except Exception:
            continue                 # skip non-hib / unreadable JSON
        fnd = Found(full, md)
        if kind == "any":
            # A bare selector: citekey and reference are interchangeable. Exact on
            # either is primary; a substring of either is the pick-list fallback.
            # Each entry is added at most once, even when both fields match.
            if value and value.lower() in (md.citekey.lower(), (md.reference or "").lower()):
                primary.append(fnd)
            elif (locate.contains_fold(md.citekey, value)
                  or locate.contains_fold(md.reference or "", value)):
                fallback.append(fnd)
        elif kind == "citekey":
            if value and md.citekey.lower() == value.lower():
                primary.append(fnd)
            elif locate.contains_fold(md.citekey, value):
                fallback.append(fnd)
        elif kind == "reference":
            if md.reference and value and md.reference.lower() == value.lower():
                primary.append(fnd)
        elif kind == "html":
            mk = locate.html_match(md.html_path, value)
            if mk == "full":
                primary.append(fnd)
            elif mk == "base":
                fallback.append(fnd)
    return primary if primary else fallback


def resolve_entry(config, kind, value, prompt, out):
    """One entry -> it; none -> message + None; several -> numbered list, prompt
    to pick (blank/invalid -> None). `out` receives messages, `prompt` asks."""
    matches = find_entries(config, kind, value)
    label = KIND_LABEL.get(kind, kind)
    if not matches:
        out('hib: no entry found for %s "%s".' % (label, value))
        return None
    if len(matches) == 1:
        return matches[0]
    out('Multiple entries match %s "%s":' % (label, value))
    for i, fnd in enumerate(matches):
        out("  %d) %s - citekey %s - ref %s - %s" % (
            i + 1, fnd.meta.title, fnd.meta.citekey, fnd.meta.reference,
            locate._basename(fnd.meta.html_path)))
    ans = (prompt("Pick (number, or blank to cancel): ") or "").strip()
    # ASCII digits only: str.isdigit() is True for non-ASCII
    # numerics like '²' that int() then rejects with ValueError.
    if ans and all("0" <= c <= "9" for c in ans):
        n = int(ans)
        if 1 <= n <= len(matches):
            return matches[n - 1]
    out("Cancelled - no entry selected.")
    return None
