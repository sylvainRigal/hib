"""The interactive `update` flow.

Re-runs the metadata prompts (no source/.bib step) pre-filled with the stored
values; for short title and date it offers a 1/2 choice between the stored value
and a freshly-computed add-style default. The REFERENCE is not among them: it is
hib's internal identifier, fixed for the life of the entry (and the name of its
JSON file), so this flow keeps it verbatim (it is never re-prompted). The stored file/folder/pdf/remote are kept exactly as recorded;
only the metadata fields and the card path change. Writes the new card, then the
JSON, then deletes the old card if it moved -- so a failure never leaves the entry
in a torn state. The JSON is never renamed.

Five targeted modes skip the interactive flow entirely:
  -html [-n]           re-render EVERY card from its JSON (no editing)
  -json-names [-n]     rename EVERY metadata file after its reference (migration)
  -json <ctk>          rewrite one JSON from its hand-edited card
  -remote <ctk> [path] set/replace/remove ONLY the remote path of one entry
  -ctk <ctk> [new]     change ONLY the citekey of one entry
"""
import os
import sys

import sanitize
import dates
import entry as entry_mod
import citekey as citekey_mod
import naming
import locate
import item_types
import html as html_mod
import metadata as metadata_mod
import selector as sel
import model
import cardparse
import addcmd


def _ask_choice(label, current, fresh, ask, out):
    """Offer a field as a 1/2 choice between the STORED `current` and a freshly
    computed `fresh` default. "1"/Enter keeps current, "2" takes fresh, a leading
    '=' escapes to a verbatim value, anything else is used as-is. When the two
    coincide it is a plain single-default prompt."""
    if current == fresh:
        return ask(label, current)
    out("%s:" % label)
    out("  1) %s   (current)" % current)
    out("  2) %s   (new default)" % fresh)
    ans = ask("%s (1/2 or a value)" % label, "1")
    if ans == "1":
        return current
    if ans == "2":
        return fresh
    if ans and ans[0] == "=":
        return ans[1:]
    return ans


def _refresh_all_html(config, dry, out):
    """`hib update -html [-n]`: re-render EVERY entry's HTML card from its stored
    JSON, with no metadata editing and no PDF work -- the way to roll a template
    change (e.g. new card buttons) out to existing cards. Each card is rebuilt
    exactly like add/update/pdf would (byte-identical), written to the JSON's own
    htmlPath; a card whose htmlPath escapes the html folder is skipped (a tampered
    JSON must not make a bulk run overwrite an arbitrary file). `-n` lists only.
    Returns 0, or 1 if any card failed to write."""
    json_dir = config.json_storage_path.rstrip("\\/")
    html_root = config.html_storage_path.rstrip("\\/")
    try:
        names = sorted(os.listdir(json_dir))
    except OSError as err:
        out("hib: cannot list the json folder %s (%s)." % (json_dir, err))
        return 1
    refreshed = skipped = failed = 0
    out("hib - refresh HTML cards from JSON%s" % ("  (dry run)" if dry else ""))
    out("")
    for name in names:
        if not name.endswith(".json"):          # case-sensitive on purpose
            continue
        full = os.path.join(json_dir, name)
        if not os.path.isfile(full):            # ignore a dir/junction named *.json
            continue
        try:
            with open(full, encoding="utf-8") as f:
                m = model.parse(f.read())
        except Exception:
            out("  skip  %s  (unreadable / not hib JSON)" % name)
            skipped += 1
            continue
        if not m.html_path:
            out("  skip  %s  (no htmlPath recorded)" % name)
            skipped += 1
            continue
        if not locate.is_within(html_root, m.html_path):
            out("  skip  %s  (htmlPath is outside the html folder)" % name)
            skipped += 1
            continue
        # Rebuild the card exactly like pdfcmd's in-place refresh: the PDF button is
        # a render-time function of the .pdf existing on disk.
        pdf_exists = os.path.exists(m.pdf_local_path)
        e = entry_mod.Entry(
            title=m.title, item_type=m.item_type, authors=m.authors, date=m.date,
            tags=m.tags, description=m.description, version=m.version,
            short_title=m.short_title, reference=m.reference, citekey=m.citekey,
            local_path=m.local_file_path, remote_path=m.remote_path,
            pdf_path=m.pdf_local_path if pdf_exists else None)
        if dry:
            out("  would refresh  %s  ->  %s" % (m.citekey, m.html_path))
            refreshed += 1
            continue
        try:
            addcmd._write_text_file(m.html_path, html_mod.render_entry(e))
        except OSError as err:
            out("  FAIL  %s  (%s)" % (m.html_path, err))
            failed += 1
            continue
        out("  ok    %s" % m.html_path)
        refreshed += 1
    out("")
    verb = "would refresh" if dry else "refreshed"
    out("hib: %s %d card(s); %d skipped, %d failed." % (verb, refreshed, skipped, failed))
    return 1 if failed else 0


def _rename_all_json(config, dry, out):
    """`hib update -json-names [-n]`: rename every metadata file to '<reference>
    .json'. hib used to name it after the citekey, so
    this is the one-shot migration for an existing archive; it is also how a file
    hand-renamed out of step is put back. Nothing but the file name changes -- the
    JSON content, the card and the stored file are untouched, and hib finds entries
    by reading the files, so an un-migrated archive keeps working.

    A name already taken by another entry gets the usual '_1' suffix rather than
    overwriting it. `-n` lists only. Returns 0, or 1 if any rename failed."""
    json_dir = config.json_storage_path.rstrip("\\/")
    try:
        names = sorted(os.listdir(json_dir))
    except OSError as err:
        out("hib: cannot list the json folder %s (%s)." % (json_dir, err))
        return 1
    renamed = kept = skipped = failed = 0
    out("hib - rename metadata files after their reference%s"
        % ("  (dry run)" if dry else ""))
    out("")
    for name in names:
        if not name.endswith(".json"):          # case-sensitive on purpose
            continue
        full = os.path.join(json_dir, name)
        if not os.path.isfile(full):            # ignore a dir/junction named *.json
            continue
        try:
            with open(full, encoding="utf-8") as f:
                m = model.parse(f.read())
        except Exception:
            out("  skip  %s  (unreadable / not hib JSON)" % name)
            skipped += 1
            continue
        wanted = addcmd.resolve_json_path(
            json_dir, naming.json_base(m.reference, m.citekey), exclude=full)
        if locate.same_path(wanted, full):
            kept += 1
            continue
        if dry:
            out("  would rename  %s  ->  %s" % (name, os.path.basename(wanted)))
            renamed += 1
            continue
        try:
            os.rename(full, wanted)
        except OSError as err:
            out("  FAIL  %s  (%s)" % (name, err))
            failed += 1
            continue
        out("  ok    %s  ->  %s" % (name, os.path.basename(wanted)))
        renamed += 1
    out("")
    verb = "would rename" if dry else "renamed"
    out("hib: %s %d file(s); %d already named after their reference, %d skipped, "
        "%d failed." % (verb, renamed, kept, skipped, failed))
    return 1 if failed else 0


def _update_json_from_card(config, sel_args, out, prompt):
    """`hib update -json <ctk>`: re-read the entry's (hand-edited) HTML card and
    rewrite its JSON to match. Text fields (title/type/version/short title/date/
    tags/description/remote path) come from the card; the citekey, the REFERENCE
    and the local file/folder/html/pdf paths are KEPT from the JSON -- the paths
    are not meaningful to edit via the card's display, and the reference is hib's
    fixed internal identifier (it names the JSON file). Editing the Reference line
    of a card therefore has no effect. The card is left untouched and the entry is
    NOT re-keyed or renamed (use `hib update <ctk>` for that). Returns 0, or 1 on a
    selector miss / unreadable card / JSON-write failure."""
    parsed = sel.parse_selector(sel_args, out)
    if parsed is None:
        return 1
    found = sel.resolve_entry(config, parsed[0], parsed[1], prompt, out)
    if found is None:
        return 1
    m = found.meta
    if not m.html_path:
        out("hib: this entry has no card path recorded; nothing to read.")
        return 1
    try:
        with open(m.html_path, "rb") as f:
            html = f.read().decode("utf-8", "surrogateescape")
    except OSError as err:
        out("hib: cannot read the card '%s' (%s)." % (m.html_path, err))
        return 1

    fields = cardparse.parse_card(html)
    e = entry_mod.Entry(
        title=fields.get("title", m.title),
        item_type=fields.get("item_type", m.item_type),
        authors=fields.get("authors", m.authors),
        date=fields.get("date", m.date),
        tags=fields.get("tags", m.tags),
        description=fields.get("description", m.description),
        version=fields.get("version", m.version),
        short_title=fields.get("short_title", m.short_title),
        reference=m.reference,          # fixed identifier: never taken from the card
        citekey=m.citekey)
    meta = metadata_mod.Metadata(
        citekey=m.citekey, entry=e,
        local_file_path=m.local_file_path, local_folder_path=m.local_folder_path,
        html_path=m.html_path, pdf_local_path=m.pdf_local_path,
        remote_path=fields.get("remote_path", m.remote_path))
    try:
        addcmd._write_text_file(found.json_path, metadata_mod.render(meta))
    except OSError as err:
        out("hib: failed to write the JSON '%s' (%s)." % (found.json_path, err))
        return 1
    out("hib - update JSON from card")
    out("")
    out("  citekey: %s" % m.citekey)
    out("  card:    %s" % m.html_path)
    out("  JSON:    %s  (updated)" % found.json_path)
    return 0


def _remote_arg(rest):
    """The remote path given on the command line, or None when there is none.
    Re-attaches a lone trailing '*' that PowerShell split into its own argument
    (same reason as hib._add_source), then runs the usual source-path cleanup
    (surrounding quotes and the '*' remote marker stripped)."""
    if not rest or not rest[0]:
        return None
    raw = rest[0]
    if not raw.endswith("*") and len(rest) > 1 and rest[-1] == "*":
        raw += "*"
    if raw.strip(" \t\r\n") == "-":          # explicit "remove it"
        return "-"
    path, _ = sanitize.parse_source_path(raw)
    return path or None


def _update_remote_path(config, args, out, ask, prompt):
    """`hib update -remote <ctk> [<path>]`: set, replace or remove JUST the remote
    source path -- whether or not the entry has one recorded. Nothing else moves:
    no re-keying, no card rename, no re-prompting of the metadata. The JSON is
    rewritten first (it is the source of truth), then the card is re-rendered in
    place so the Remote buttons appear or disappear.

    With no <path>, prompts with the stored value as default; '-' removes the
    remote path. Returns 0, or 1 on a selector miss / write failure."""
    parsed = sel.parse_selector(args, out)
    if parsed is None:
        return 1
    # parse_selector reads 1 arg (a citekey) or 2 (-citekey/-html/-ref <value>);
    # whatever follows is the new remote path.
    consumed = 2 if args[0].startswith("-") else 1
    found = sel.resolve_entry(config, parsed[0], parsed[1], prompt, out)
    if found is None:
        return 1
    m = found.meta
    current = m.remote_path

    out("hib - update the remote path")
    out("")
    out("  Title:   %s" % m.title)
    out("  citekey: %s" % m.citekey)
    out("  Current: %s" % (current if current else "(none recorded)"))
    out("")

    value = _remote_arg(args[consumed:])
    if value is None:                        # nothing on the command line -> ask
        answer = ask("Remote path ('-' removes it)", current or "")
        value = _remote_arg([answer]) if answer else None
        if value is None and not current:
            out("")
            out("Cancelled - nothing changed.")
            return 0
        if value is None:                    # empty answer with a stored value
            value = current
    new_remote = None if value == "-" else value

    if new_remote == current:
        out("Unchanged - the remote path is already %s."
            % (("'%s'" % current) if current else "not recorded"))
        return 0
    if new_remote and not os.path.exists(new_remote):
        out("  Note: %s does not exist right now (an offline share is fine); "
            "recording it anyway." % new_remote)

    # The card's PDF button is gated on the PDF existing on disk, exactly as
    # add/update/pdf do, so this never silently drops a real PDF button.
    pdf_for_card = m.pdf_local_path if (m.pdf_local_path and os.path.exists(m.pdf_local_path)) else None
    e = entry_mod.Entry(
        title=m.title, item_type=m.item_type, authors=m.authors, date=m.date,
        tags=m.tags, description=m.description, version=m.version,
        short_title=m.short_title, reference=m.reference, citekey=m.citekey,
        local_path=m.local_file_path, remote_path=new_remote, pdf_path=pdf_for_card)
    meta = metadata_mod.Metadata(
        citekey=m.citekey, entry=e, local_file_path=m.local_file_path,
        local_folder_path=m.local_folder_path, html_path=m.html_path,
        pdf_local_path=m.pdf_local_path, remote_path=new_remote)
    try:
        addcmd._write_text_file(found.json_path, metadata_mod.render(meta))
    except OSError as err:
        out("hib: failed to write the JSON '%s' (%s). Nothing changed." % (found.json_path, err))
        return 1

    out("  Remote:  %s" % (new_remote if new_remote else "(removed)"))
    out("  JSON:    %s  (updated)" % found.json_path)
    if not m.html_path:
        out("  Card:    (none recorded)")
        return 0
    try:
        addcmd._write_text_file(m.html_path, html_mod.render_entry(e))
    except OSError as err:
        out("  Card:    %s  FAILED (%s)" % (m.html_path, err))
        out("hib: the JSON is up to date but the card is stale; "
            "re-render it with `hib update -html`.")
        return 1
    out("  Card:    %s  (refreshed)" % m.html_path)
    return 0


def _update_citekey(config, args, out, ask, prompt):
    """`hib update -ctk <ctk|ref> [<new citekey>]`: change JUST the citekey. The
    stored file/folder/pdf/remote and every metadata field stay as they are; only
    the citekey moves. Nothing is renamed: the JSON is named after the reference
    (hib's fixed identifier) and the card after the title, so both keep their
    names -- the card is simply re-rendered so its Citekey line and its Copy
    Citekey button follow.

    With no <new citekey>, prompts with the current one as the default. The value
    is folded through citekey.clean, so it stays a usable identifier. Returns 0,
    or 1 on a selector miss, an unusable citekey, or a write failure."""
    parsed = sel.parse_selector(args, out)
    if parsed is None:
        return 1
    # parse_selector reads 1 arg (a citekey/reference) or 2 (-citekey/-html/-ref
    # <value>); whatever follows is the new citekey.
    consumed = 2 if args[0].startswith("-") else 1
    found = sel.resolve_entry(config, parsed[0], parsed[1], prompt, out)
    if found is None:
        return 1
    m = found.meta

    out("hib - update the citekey")
    out("")
    out("  Title:   %s" % m.title)
    out("  Current: %s" % m.citekey)
    out("")

    raw = args[consumed] if len(args) > consumed else ask("New citekey", m.citekey)
    raw = (raw or "").strip(" \t\r\n")
    new_citekey = citekey_mod.clean(raw)
    if not new_citekey:
        out("hib: '%s' leaves no usable citekey "
            "(letters, digits, '.', '_' and '-' are kept). Nothing changed." % raw)
        return 1
    if new_citekey != raw:
        out("  Note: adjusted to '%s' so it stays a safe file name." % new_citekey)
    if new_citekey == m.citekey:
        out("Unchanged - the citekey is already '%s'." % m.citekey)
        return 0

    # hib tolerates two entries sharing a citekey (the JSON name is auto-numbered),
    # but it makes every bare selector ambiguous -- so say so instead of hiding it.
    clash = [f for f in sel.find_entries(config, "citekey", new_citekey)
             if not locate.same_path(f.json_path, found.json_path)
             and f.meta.citekey.lower() == new_citekey.lower()]
    if clash:
        out("  Note: '%s' is already the citekey of: %s. A bare selector on it "
            "will list them all." % (new_citekey,
                                     ", ".join(f.meta.title for f in clash)))

    # The card's PDF button is gated on the PDF existing on disk, exactly as
    # add/update/pdf do, so this never silently drops a real PDF button.
    pdf_for_card = m.pdf_local_path if (m.pdf_local_path and os.path.exists(m.pdf_local_path)) else None
    e = entry_mod.Entry(
        title=m.title, item_type=m.item_type, authors=m.authors, date=m.date,
        tags=m.tags, description=m.description, version=m.version,
        short_title=m.short_title, reference=m.reference, citekey=new_citekey,
        local_path=m.local_file_path, remote_path=m.remote_path, pdf_path=pdf_for_card)
    meta = metadata_mod.Metadata(
        citekey=new_citekey, entry=e, local_file_path=m.local_file_path,
        local_folder_path=m.local_folder_path, html_path=m.html_path,
        pdf_local_path=m.pdf_local_path, remote_path=m.remote_path)

    try:
        addcmd._write_text_file(found.json_path, metadata_mod.render(meta))
    except OSError as err:
        out("hib: failed to write the JSON '%s' (%s). Nothing changed."
            % (found.json_path, err))
        return 1

    out("  Citekey: %s" % new_citekey)
    out("  JSON:    %s  (updated)" % found.json_path)
    if not m.html_path:
        out("  Card:    (none recorded)")
        return 0
    try:
        addcmd._write_text_file(m.html_path, html_mod.render_entry(e))
    except OSError as err:
        out("  Card:    %s  FAILED (%s)" % (m.html_path, err))
        out("hib: the JSON is up to date but the card still shows the old citekey; "
            "re-render it with `hib update -html`.")
        return 1
    out("  Card:    %s  (refreshed)" % m.html_path)
    return 0


def run_update(config, args, config_dir):
    """Run the interactive update. Prompts on stdout; reads stdin. Returns an exit
    code (0 success or graceful cancel, 1 on a selector miss or hard I/O failure).

    `hib update -html [-n]` re-renders every card from its JSON (no editing).
    `hib update -json-names [-n]` renames the metadata files after their reference.
    `hib update -json <ctk>` does the inverse: rewrite a JSON from its edited card.
    `hib update -remote <ctk> [<path>]` sets only the remote path.
    `hib update -ctk <ctk> [<new>]` changes only the citekey.
    `-html <value>` keeps its selector meaning; `-citekey <value>` is how you
    select by citekey here, since `-ctk` in first position is the mode above."""

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

    def prompt(text):                    # for the selector pick list
        sys.stdout.write(text)
        sys.stdout.flush()
        return sys.stdin.readline()

    # Bulk-refresh mode: `hib update -html [-n]` re-renders EVERY card from its JSON
    # (no metadata editing). `-html <value>` still means "select by html path" below.
    if args and args[0] == "-html" and all(a in ("-n", "--dry-run") for a in args[1:]):
        dry = any(a in ("-n", "--dry-run") for a in args[1:])
        return _refresh_all_html(config, dry, out)

    # Migration: `hib update -json-names [-n]` renames the metadata files after
    # their reference. Matched BEFORE -json, which is a prefix of it.
    if args and args[0] == "-json-names" and all(a in ("-n", "--dry-run") for a in args[1:]):
        dry = any(a in ("-n", "--dry-run") for a in args[1:])
        return _rename_all_json(config, dry, out)

    # Inverse sync: `hib update -json <ctk>` reads the card, rewrites the JSON.
    if args and args[0] == "-json":
        return _update_json_from_card(config, args[1:], out, prompt)

    # Targeted edit: `hib update -remote <ctk> [<path>]` touches only the remote path.
    if args and args[0] == "-remote":
        return _update_remote_path(config, args[1:], out, ask, prompt)

    # Targeted edit: `hib update -ctk <ctk|ref> [<new>]` changes only the citekey.
    # This SHADOWS -ctk's selector meaning in first position (everywhere else, and
    # after this flag, -ctk still means "select by citekey"): `hib update -ctk X`
    # now re-keys X instead of editing it. Use the long `-citekey X` to select.
    if args and args[0] == "-ctk":
        return _update_citekey(config, args[1:], out, ask, prompt)

    parsed = sel.parse_selector(args, out)
    if parsed is None:
        return 1
    kind, value = parsed
    found = sel.resolve_entry(config, kind, value, prompt, out)
    if found is None:
        return 1
    m = found.meta

    out("hib - update an entry")
    out("")

    # Re-run the metadata prompts, pre-filled with the stored value. The item-type
    # default is canonicalized to the table's spelling when it matches.
    table = item_types.load_item_types(config_dir, out)
    canon = table.find_fold(m.item_type)
    item_type = item_types.choose_item_type(table, ask, out, canon if canon is not None else m.item_type)
    title = ask("Title", m.title)

    short_input = _ask_choice("Short title", m.short_title, sanitize.sanitize_base(title), ask, out)
    short_title, name_from_card = sanitize.parse_short_title(short_input)

    version = ask("Version", m.version)
    authors = entry_mod.parse_author_list(
        ask("Authors (Last:First, comma-separated)", entry_mod.authors_to_input(m.authors)))

    y, mo, d = dates.today()
    date = _ask_choice("Date (DD/MM/YYYY)", m.date, dates.format_dmy(y, mo, d), ask, out)

    tags = entry_mod.parse_tag_list(
        ask("Tags (comma-separated)", entry_mod.tags_to_input(m.tags)))
    description = ask("Description", m.description)

    yyyymmdd = dates.compact_dmy(date)
    citekey = citekey_mod.build(item_type, authors, yyyymmdd)
    # The reference is hib's internal identifier: fixed for the life of the entry,
    # and the name of its JSON file. It is NOT re-prompted here, so it cannot
    # drift.
    reference = m.reference

    # New card base: the short title when flagged with '*'; else the title slug
    # when the title changed; else the current card name (no surprise rename of an
    # auto-numbered / short-named / manually-named card).
    old_card_base = sanitize.strip_extension(sanitize.base_name(m.html_path))
    if name_from_card and short_title:
        new_card_base = sanitize.sanitize_base(short_title)
    elif title != m.title:
        new_card_base = sanitize.sanitize_base(title)
    else:
        new_card_base = old_card_base

    html_dir = config.html_storage_path.rstrip("\\/")
    json_dir = config.json_storage_path.rstrip("\\/")
    try:
        os.makedirs(html_dir, exist_ok=True)
        os.makedirs(json_dir, exist_ok=True)
    except OSError as err:
        out("hib: cannot create the html/json folder (%s)." % err)
        return 1

    # Resolve the new card/json paths, EXCLUDING this entry's own old files so an
    # unchanged name resolves back in place. [e]overwrite is DISABLED for update:
    # the only card that can collide belongs to another entry, and clobbering it
    # would orphan that entry.
    new_card_path = addcmd.resolve_card_path(
        html_dir, new_card_base, ask, out, exclude=m.html_path, allow_overwrite=False)
    if new_card_path is None:
        out("")
        out("Cancelled - nothing changed.")
        return 0
    # The JSON keeps its file name: it is derived from the reference, which this
    # flow no longer changes. (json_dir is still resolved/created above, and the
    # entry could not have been found without its file.)
    json_path = found.json_path

    # The card's PDF button is gated on the PDF actually existing on disk (exactly
    # as add/pdf do), so an update never silently drops a real PDF button.
    pdf_for_card = m.pdf_local_path if (m.pdf_local_path and os.path.exists(m.pdf_local_path)) else None
    e = entry_mod.Entry(
        title=title, item_type=item_type, authors=authors, date=date, tags=tags,
        description=description, version=version, short_title=short_title,
        reference=reference, citekey=citekey, local_path=m.local_file_path,
        remote_path=m.remote_path, pdf_path=pdf_for_card)

    # Write new card, then new JSON, then delete the old ones if they moved.
    try:
        addcmd._write_text_file(new_card_path, html_mod.render_entry(e))
    except OSError as err:
        out("hib: failed to write the card '%s' (%s). Nothing changed." % (new_card_path, err))
        return 1
    card_renamed = not locate.same_path(new_card_path, m.html_path)

    meta = metadata_mod.Metadata(
        citekey=citekey, entry=e, local_file_path=m.local_file_path,
        local_folder_path=m.local_folder_path, html_path=new_card_path,
        pdf_local_path=m.pdf_local_path, remote_path=e.remote_path)
    try:
        addcmd._write_text_file(json_path, metadata_mod.render(meta))
    except OSError as err:
        # The new card was already written. If it was a rename, remove it so the
        # still-valid old card + old JSON remain the single consistent state.
        if card_renamed:
            try:
                os.remove(new_card_path)
            except OSError:
                pass
        out("hib: metadata write failed (%s); the entry is unchanged." % err)
        return 1

    if card_renamed:
        try:
            os.remove(m.html_path)
        except OSError as err:
            out("  WARNING: old card not removed (%s): %s" % (m.html_path, err))

    out("")
    out("Updated entry:")
    out("  Card:     %s%s" % (new_card_path, " (renamed)" if card_renamed else ""))
    out("  Metadata: %s" % json_path)
    out("  Stored file (unchanged): %s" % m.local_file_path)
    return 0
