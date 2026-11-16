import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import updcmd
import addcmd


def _ask_returning(value):
    return lambda label, default: value


class _Cfg(object):
    """Minimal stand-in for config.Config: only the storage paths _refresh_all_html
    reads (json + html)."""
    def __init__(self, file_path, html_path, json_path):
        self.file_storage_path = file_path
        self.html_storage_path = html_path
        self.json_storage_path = json_path


class TestAskChoice(unittest.TestCase):
    def setUp(self):
        self.msgs = []

    def _out(self, s):
        self.msgs.append(s)

    def test_single_default_when_current_equals_fresh(self):
        # No 1/2 menu printed; ask is used directly with the current value.
        r = updcmd._ask_choice("Date", "X", "X", _ask_returning("typed"), self._out)
        self.assertEqual(r, "typed")
        self.assertEqual(self.msgs, [])

    def test_choice_one_keeps_current(self):
        r = updcmd._ask_choice("Date", "cur", "fresh", _ask_returning("1"), self._out)
        self.assertEqual(r, "cur")
        self.assertTrue(any("1) cur" in m for m in self.msgs))

    def test_choice_two_takes_fresh(self):
        r = updcmd._ask_choice("Date", "cur", "fresh", _ask_returning("2"), self._out)
        self.assertEqual(r, "fresh")

    def test_equals_escapes_to_verbatim(self):
        self.assertEqual(updcmd._ask_choice("D", "cur", "fresh", _ask_returning("=2"), self._out), "2")
        self.assertEqual(updcmd._ask_choice("D", "cur", "fresh", _ask_returning("=1"), self._out), "1")

    def test_other_value_used_verbatim(self):
        self.assertEqual(updcmd._ask_choice("D", "cur", "fresh", _ask_returning("hello"), self._out), "hello")


class TestExcludeResolvers(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hibpy_upd_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_json_exclude_lands_in_place(self):
        existing = os.path.join(self.d, "K.json")
        open(existing, "w").close()
        # Excluding the entry's own json -> it resolves back to it (no _1 bump).
        self.assertEqual(addcmd.resolve_json_path(self.d, "K", exclude=existing), existing)
        # Without exclude, a taken name bumps to _1.
        self.assertEqual(addcmd.resolve_json_path(self.d, "K"), os.path.join(self.d, "K_1.json"))

    def test_card_exclude_returns_without_prompting(self):
        existing = os.path.join(self.d, "Foo.html")
        open(existing, "w").close()

        def boom(label, default):
            raise AssertionError("must not prompt when the name is the entry's own card")
        r = addcmd.resolve_card_path(self.d, "Foo", boom, lambda s: None,
                                     exclude=existing, allow_overwrite=False)
        self.assertEqual(r, existing)


class TestRefreshAllHtml(unittest.TestCase):
    """`hib update -html`: re-render every card from its JSON."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_refresh_")
        for sub in ("f", "html", "json"):
            os.makedirs(os.path.join(self.tmp, sub))
        self.cfg = _Cfg(os.path.join(self.tmp, "f"),
                        os.path.join(self.tmp, "html"),
                        os.path.join(self.tmp, "json"))
        self.msgs = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _out(self, s):
        self.msgs.append(s)

    def _write_entry(self, name, card_name):
        card = os.path.join(self.tmp, "html", card_name)
        meta = {
            "citekey": name, "title": "T " + name, "shortTitle": "S",
            "itemType": "document", "version": "1", "date": "03/06/2026",
            "description": "", "localFilePath": os.path.join(self.tmp, "f", "a1", "x.docx"),
            "localFolderPath": os.path.join(self.tmp, "f", "a1"),
            "htmlPath": card, "pdfLocalPath": "", "authors": [], "tags": ["x"],
        }
        with open(os.path.join(self.tmp, "json", name + ".json"), "w",
                  encoding="utf-8", newline="") as f:
            f.write(json.dumps(meta))
        with open(card, "w", encoding="utf-8", newline="") as f:
            f.write("STALE")
        return card

    def test_refresh_regenerates_card(self):
        card = self._write_entry("K1", "Card1.html")
        rc = updcmd._refresh_all_html(self.cfg, False, self._out)
        self.assertEqual(rc, 0)
        with open(card, encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("STALE", html)
        self.assertIn("Open File Location", html)        # the new button is present
        self.assertIn("<title>T K1</title>", html)
        self.assertTrue(any("refreshed 1 card" in m for m in self.msgs))

    def test_dry_run_lists_without_writing(self):
        card = self._write_entry("K2", "Card2.html")
        rc = updcmd._refresh_all_html(self.cfg, True, self._out)
        self.assertEqual(rc, 0)
        with open(card, encoding="utf-8") as f:
            self.assertEqual(f.read(), "STALE")           # untouched
        self.assertTrue(any("would refresh" in m for m in self.msgs))

    def test_skips_htmlpath_outside_html_folder(self):
        outside = os.path.join(self.tmp, "evil.html")
        with open(outside, "w", encoding="utf-8", newline="") as f:
            f.write("DO NOT TOUCH")
        meta = {"citekey": "Evil", "title": "E", "htmlPath": outside,
                "itemType": "document", "version": "1", "date": "", "description": "",
                "localFilePath": "", "localFolderPath": "", "pdfLocalPath": "",
                "authors": [], "tags": []}
        with open(os.path.join(self.tmp, "json", "Evil.json"), "w",
                  encoding="utf-8", newline="") as f:
            f.write(json.dumps(meta))
        rc = updcmd._refresh_all_html(self.cfg, False, self._out)
        self.assertEqual(rc, 0)
        with open(outside, encoding="utf-8") as f:
            self.assertEqual(f.read(), "DO NOT TOUCH")    # untouched by the bulk run
        self.assertTrue(any("outside the html folder" in m for m in self.msgs))


class TestUpdateJsonFromCard(unittest.TestCase):
    """`hib update -json <ctk>`: sync a hand-edited card back into its JSON."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_uj_")
        for sub in ("f", "html", "json"):
            os.makedirs(os.path.join(self.tmp, sub))
        self.cfg = _Cfg(os.path.join(self.tmp, "f"),
                        os.path.join(self.tmp, "html"),
                        os.path.join(self.tmp, "json"))
        self.msgs = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _out(self, s):
        self.msgs.append(s)

    def test_card_edits_sync_keeping_citekey_and_paths(self):
        import entry as entry_mod
        import html as html_mod
        import metadata as metadata_mod
        import model

        local = os.path.join(self.tmp, "f", "a1", "x.docx")
        card = os.path.join(self.tmp, "html", "K.html")
        e = entry_mod.Entry(title="Old Title", item_type="document",
                            authors=[("Rigal", "Sylvain")], date="03/06/2026",
                            tags=["a", "b"], description="old desc", version="1",
                            short_title="Old", reference="REF1", citekey="K",
                            local_path=local)
        meta = metadata_mod.Metadata(
            citekey="K", entry=e, local_file_path=local,
            local_folder_path=os.path.join(self.tmp, "f", "a1"),
            html_path=card, pdf_local_path=os.path.join(self.tmp, "f", "a1", "x.pdf"),
            remote_path=None)
        with open(os.path.join(self.tmp, "json", "K.json"), "w",
                  encoding="utf-8", newline="") as f:
            f.write(metadata_mod.render(meta))
        with open(card, "w", encoding="utf-8", newline="") as f:
            f.write(html_mod.render_entry(e))

        # Hand-edit the card: new title (h2), new description, drop a tag.
        with open(card, encoding="utf-8") as f:
            h = f.read()
        h = (h.replace("old desc", "new desc")
              .replace("<h2>Old Title</h2>", "<h2>New Title</h2>")
              .replace('    <span class="tag">b</span>\n', ""))
        with open(card, "w", encoding="utf-8", newline="") as f:
            f.write(h)

        rc = updcmd._update_json_from_card(self.cfg, ["K"], self._out, lambda t: "")
        self.assertEqual(rc, 0)

        with open(os.path.join(self.tmp, "json", "K.json"), encoding="utf-8") as f:
            m2 = model.parse(f.read())
        self.assertEqual(m2.title, "New Title")        # synced from the card
        self.assertEqual(m2.description, "new desc")
        self.assertEqual(m2.tags, ["a"])               # dropped 'b'
        self.assertEqual(m2.citekey, "K")              # kept from JSON
        self.assertEqual(m2.local_file_path, local)    # kept from JSON


class TestRemoteArg(unittest.TestCase):
    """`hib update -remote` argument cleanup."""

    def test_none_when_no_argument(self):
        self.assertIsNone(updcmd._remote_arg([]))
        self.assertIsNone(updcmd._remote_arg([""]))

    def test_quotes_and_remote_marker_are_stripped(self):
        self.assertEqual(updcmd._remote_arg(['"S:\\share\\x.docx"']), "S:\\share\\x.docx")
        self.assertEqual(updcmd._remote_arg(["S:\\share\\x.docx*"]), "S:\\share\\x.docx")

    def test_powershell_split_star_is_reattached(self):
        # PowerShell tokenizes `"path"*` as ['path', '*']; the marker must not
        # end up recorded as part of the path, nor break the argument.
        self.assertEqual(updcmd._remote_arg(["S:\\share\\x.docx", "*"]), "S:\\share\\x.docx")

    def test_dash_means_remove(self):
        self.assertEqual(updcmd._remote_arg(["-"]), "-")


class TestUpdateRemotePath(unittest.TestCase):
    """`hib update -remote <ctk> [<path>]`: only the remote path changes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_rem_")
        for sub in ("f", "html", "json"):
            os.makedirs(os.path.join(self.tmp, sub))
        self.cfg = _Cfg(os.path.join(self.tmp, "f"),
                        os.path.join(self.tmp, "html"),
                        os.path.join(self.tmp, "json"))
        self.msgs = []
        self.card = os.path.join(self.tmp, "html", "K.html")
        self.local = os.path.join(self.tmp, "f", "a1", "x.docx")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _out(self, s):
        self.msgs.append(s)

    def _write_entry(self, remote=None):
        import entry as entry_mod
        import html as html_mod
        import metadata as metadata_mod
        e = entry_mod.Entry(title="T", item_type="report", authors=[("Doe", "Jane")],
                            date="03/06/2026", tags=["a"], description="d", version="1",
                            short_title="S", reference="REF1", citekey="K",
                            local_path=self.local, remote_path=remote)
        meta = metadata_mod.Metadata(
            citekey="K", entry=e, local_file_path=self.local,
            local_folder_path=os.path.join(self.tmp, "f", "a1"),
            html_path=self.card,
            pdf_local_path=os.path.join(self.tmp, "f", "a1", "x.pdf"),
            remote_path=remote)
        with open(os.path.join(self.tmp, "json", "K.json"), "w",
                  encoding="utf-8", newline="") as f:
            f.write(metadata_mod.render(meta))
        with open(self.card, "w", encoding="utf-8", newline="") as f:
            f.write(html_mod.render_entry(e))

    def _run(self, args, answer=None):
        ask = _ask_returning(answer) if answer is not None else _ask_returning("")
        return updcmd._update_remote_path(self.cfg, args, self._out, ask, lambda t: "")

    def _meta(self):
        import model
        with open(os.path.join(self.tmp, "json", "K.json"), encoding="utf-8") as f:
            return model.parse(f.read())

    def _card_html(self):
        with open(self.card, encoding="utf-8") as f:
            return f.read()

    def test_sets_a_remote_path_on_an_entry_that_had_none(self):
        self._write_entry(remote=None)
        self.assertNotIn("Copy Remote Path", self._card_html())
        rc = self._run(["K", "S:\\share\\rapport.docx"])
        self.assertEqual(rc, 0)
        self.assertEqual(self._meta().remote_path, "S:\\share\\rapport.docx")
        self.assertIn("Copy Remote Path", self._card_html())   # card grew the buttons

    def test_replaces_an_existing_remote_path(self):
        self._write_entry(remote="S:\\old\\x.docx")
        self.assertEqual(self._run(["K", "S:\\new\\y.docx"]), 0)
        m = self._meta()
        self.assertEqual(m.remote_path, "S:\\new\\y.docx")
        self.assertIn("S:\\new\\y.docx", self._card_html())
        self.assertNotIn("S:\\old\\x.docx", self._card_html())

    def test_dash_removes_the_remote_path(self):
        self._write_entry(remote="S:\\old\\x.docx")
        self.assertEqual(self._run(["K", "-"]), 0)
        self.assertIsNone(self._meta().remote_path)            # key gone, not ""
        self.assertNotIn("Copy Remote Path", self._card_html())

    def test_nothing_else_changes(self):
        self._write_entry(remote=None)
        before = self._meta()
        self._run(["K", "S:\\share\\x.docx"])
        after = self._meta()
        for field in ("citekey", "title", "short_title", "item_type", "version",
                      "date", "description", "reference", "tags", "authors",
                      "local_file_path", "local_folder_path", "html_path",
                      "pdf_local_path"):
            self.assertEqual(getattr(after, field), getattr(before, field), field)
        self.assertEqual(os.listdir(os.path.join(self.tmp, "html")), ["K.html"])
        self.assertEqual(os.listdir(os.path.join(self.tmp, "json")), ["K.json"])

    def test_prompt_default_keeps_the_stored_value(self):
        self._write_entry(remote="S:\\old\\x.docx")
        # ask() returns its default when the answer is empty -> unchanged.
        rc = self._run(["K"], answer="S:\\old\\x.docx")
        self.assertEqual(rc, 0)
        self.assertEqual(self._meta().remote_path, "S:\\old\\x.docx")
        self.assertTrue(any("Unchanged" in m for m in self.msgs))

    def test_prompt_sets_a_value_when_none_was_recorded(self):
        self._write_entry(remote=None)
        self.assertEqual(self._run(["K"], answer="S:\\share\\x.docx"), 0)
        self.assertEqual(self._meta().remote_path, "S:\\share\\x.docx")

    def test_empty_prompt_on_an_entry_without_remote_is_a_clean_cancel(self):
        self._write_entry(remote=None)
        self.assertEqual(self._run(["K"], answer=""), 0)
        self.assertIsNone(self._meta().remote_path)
        self.assertTrue(any("Cancelled" in m for m in self.msgs))

    def test_selector_flag_form_leaves_the_path_argument(self):
        self._write_entry(remote=None)
        self.assertEqual(self._run(["-citekey", "K", "S:\\share\\x.docx"]), 0)
        self.assertEqual(self._meta().remote_path, "S:\\share\\x.docx")

    def test_unknown_citekey_returns_one(self):
        self._write_entry(remote=None)
        self.assertEqual(self._run(["NOPE", "S:\\x"]), 1)

    def test_note_when_the_path_does_not_exist(self):
        self._write_entry(remote=None)
        self._run(["K", "S:\\offline\\share\\x.docx"])
        self.assertTrue(any("does not exist right now" in m for m in self.msgs))


@unittest.skipUnless(sys.platform == "win32", "update flow is Windows-specific")
class TestUpdateCitekey(unittest.TestCase):
    """`hib update -ctk <ctk|ref> [<new>]`: only the citekey changes. Nothing is
    renamed -- the JSON is named after the reference, which never changes -- but
    the card is re-rendered so it shows the new citekey."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_ctk_")
        for sub in ("f", "html", "json"):
            os.makedirs(os.path.join(self.tmp, sub))
        self.cfg = _Cfg(os.path.join(self.tmp, "f"),
                        os.path.join(self.tmp, "html"),
                        os.path.join(self.tmp, "json"))
        self.msgs = []
        self.card = os.path.join(self.tmp, "html", "S.html")
        self.local = os.path.join(self.tmp, "f", "a1", "x.docx")
        self.remote = os.path.join("S:", "share", "x.docx")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _out(self, s):
        self.msgs.append(s)

    def _said(self, needle):
        return any(needle in m for m in self.msgs)

    def _write_entry(self, citekey="K", reference="REF1", card=None, title="T"):
        import entry as entry_mod
        import html as html_mod
        import metadata as metadata_mod
        card = card or self.card
        e = entry_mod.Entry(title=title, item_type="report",
                            authors=[("Doe", "Jane")], date="03/06/2026",
                            tags=["a", "b"], description="d", version="2",
                            short_title="S", reference=reference, citekey=citekey,
                            local_path=self.local, remote_path=self.remote)
        meta = metadata_mod.Metadata(
            citekey=citekey, entry=e, local_file_path=self.local,
            local_folder_path=os.path.join(self.tmp, "f", "a1"),
            html_path=card,
            pdf_local_path=os.path.join(self.tmp, "f", "a1", "x.pdf"),
            remote_path=self.remote)
        with open(os.path.join(self.tmp, "json", reference + ".json"), "w",
                  encoding="utf-8", newline="") as f:
            f.write(metadata_mod.render(meta))
        with open(card, "w", encoding="utf-8", newline="") as f:
            f.write(html_mod.render_entry(e))

    def _run(self, args, answer=None):
        ask = _ask_returning(answer if answer is not None else "")
        return updcmd._update_citekey(self.cfg, args, self._out, ask, lambda t: "")

    def _json_names(self):
        return sorted(os.listdir(os.path.join(self.tmp, "json")))

    def _meta(self, name):
        import model
        with open(os.path.join(self.tmp, "json", name), encoding="utf-8") as f:
            return model.parse(f.read())

    def _card_html(self, path=None):
        with open(path or self.card, encoding="utf-8") as f:
            return f.read()

    def test_rekeys_in_place_and_rewrites_the_card(self):
        self._write_entry()
        self.assertEqual(self._run(["K", "NewKey2026"]), 0)
        self.assertEqual(self._json_names(), ["REF1.json"])   # named after the reference
        self.assertEqual(self._meta("REF1.json").citekey, "NewKey2026")
        self.assertIn('<span id="citekeyValue">NewKey2026</span>', self._card_html())

    def test_nothing_is_renamed(self):
        # The card is named after the title, the JSON after the reference.
        self._write_entry()
        self.assertEqual(self._run(["K", "NewKey2026"]), 0)
        self.assertEqual(os.listdir(os.path.join(self.tmp, "html")), ["S.html"])
        self.assertEqual(self._json_names(), ["REF1.json"])

    def test_selecting_by_reference_works(self):
        self._write_entry()
        self.assertEqual(self._run(["REF1", "NewKey2026"]), 0)
        self.assertEqual(self._meta("REF1.json").citekey, "NewKey2026")

    def test_restricting_the_selector_still_works(self):
        self._write_entry()
        self.assertEqual(self._run(["-ref", "REF1", "NewKey2026"]), 0)
        self.assertEqual(self._meta("REF1.json").citekey, "NewKey2026")

    def test_everything_else_is_untouched(self):
        self._write_entry()
        self.assertEqual(self._run(["K", "NewKey2026"]), 0)
        m = self._meta("REF1.json")
        self.assertEqual(m.title, "T")
        self.assertEqual(m.reference, "REF1")
        self.assertEqual(m.version, "2")
        self.assertEqual(m.tags, ["a", "b"])
        self.assertEqual(m.local_file_path, self.local)
        self.assertEqual(m.remote_path, self.remote)
        self.assertEqual(m.html_path, self.card)

    def test_prompts_when_no_value_is_given(self):
        self._write_entry()
        self.assertEqual(self._run(["K"], answer="Asked2026"), 0)
        self.assertEqual(self._meta("REF1.json").citekey, "Asked2026")

    def test_same_citekey_is_a_noop(self):
        self._write_entry()
        self.assertEqual(self._run(["K", "K"]), 0)
        self.assertEqual(self._meta("REF1.json").citekey, "K")
        self.assertTrue(self._said("Unchanged"))

    def test_unusable_value_changes_nothing(self):
        self._write_entry()
        self.assertEqual(self._run(["K", "@@@"]), 1)
        self.assertEqual(self._json_names(), ["REF1.json"])
        self.assertEqual(self._meta("REF1.json").citekey, "K")
        self.assertTrue(self._said("no usable citekey"))

    def test_value_is_folded_into_a_safe_identifier(self):
        self._write_entry()
        self.assertEqual(self._run(["K", "rapport final 2026"]), 0)
        self.assertEqual(self._meta("REF1.json").citekey, "Rapportfinal2026")
        self.assertTrue(self._said("adjusted to 'Rapportfinal2026'"))

    def test_clash_with_another_entry_is_reported_not_blocked(self):
        other_card = os.path.join(self.tmp, "html", "other.html")
        self._write_entry(citekey="Taken", reference="REF2", card=other_card,
                          title="The other one")
        self._write_entry()                       # K, the one being re-keyed
        self.assertEqual(self._run(["K", "Taken"]), 0)
        # Both keep their own file: the names come from the references.
        self.assertEqual(self._json_names(), ["REF1.json", "REF2.json"])
        self.assertEqual(self._meta("REF1.json").citekey, "Taken")
        self.assertEqual(self._meta("REF2.json").citekey, "Taken")
        self.assertTrue(self._said("already the citekey of: The other one"))

    def test_missing_selector_is_reported(self):
        self._write_entry()
        self.assertEqual(self._run([]), 1)
        self.assertEqual(self._meta("REF1.json").citekey, "K")

    def test_unknown_entry_is_reported(self):
        self._write_entry()
        self.assertEqual(self._run(["NOPE", "NewKey2026"]), 1)
        self.assertEqual(self._meta("REF1.json").citekey, "K")


class TestUpdateIntegration(unittest.TestCase):
    def test_add_then_update_renames_card_and_changes_field(self):
        tmp = tempfile.mkdtemp(prefix="hibpy_updint_")
        try:
            for sub in ("f", "html", "json"):
                os.makedirs(os.path.join(tmp, sub))
            cfg = os.path.join(tmp, "config.toml")
            with open(cfg, "w", encoding="utf-8", newline="") as f:
                f.write("[storage]\n")
                f.write("file = '%s'\n" % os.path.join(tmp, "f"))
                f.write("html = '%s'\n" % os.path.join(tmp, "html"))
                f.write("json = '%s'\n" % os.path.join(tmp, "json"))
            src = os.path.join(tmp, "src.txt")
            with open(src, "w", newline="") as f:
                f.write("hi\n")
            env = dict(os.environ, HIB_CONFIG=cfg)
            hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")

            add_in = "\n".join(["", "report", "Old Title", "", "1", "Doe:Jane",
                                "03/06/2026", "t1", "", ""]) + "\n"
            p = subprocess.run([sys.executable, hib, "add", src], input=add_in.encode("utf-8"),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
            self.assertEqual(os.listdir(os.path.join(tmp, "html")), ["Old_Title.html"])
            citekey = os.listdir(os.path.join(tmp, "json"))[0][:-5]   # strip .json

            # update: change title (-> card rename), keep short(1)/date(1), rest blank.
            upd_in = "\n".join(["", "New Title", "1", "", "", "1", "", "", ""]) + "\n"
            p = subprocess.run([sys.executable, hib, "update", citekey], input=upd_in.encode("utf-8"),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))

            cards = os.listdir(os.path.join(tmp, "html"))
            self.assertEqual(cards, ["New_Title.html"], "card renamed, old removed")
            with open(os.path.join(tmp, "html", "New_Title.html"), encoding="utf-8") as f:
                card = f.read()
            self.assertIn("<title>New Title</title>", card)
            # json kept its name (citekey unchanged) and now holds the new title.
            metas = os.listdir(os.path.join(tmp, "json"))
            self.assertEqual(metas, [citekey + ".json"])
            with open(os.path.join(tmp, "json", metas[0]), encoding="utf-8") as f:
                self.assertIn('"title": "New Title"', f.read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestUpdateCitekeyDispatch(unittest.TestCase):
    """`-ctk` right after `update` is the re-key mode, NOT the selector shorthand;
    `-citekey` is how you still select by citekey there. Checked through the real
    CLI, since the two meanings are only told apart by run_update's dispatch."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_ctkcli_")
        for sub in ("f", "html", "json"):
            os.makedirs(os.path.join(self.tmp, sub))
        cfg = os.path.join(self.tmp, "config.toml")
        with open(cfg, "w", encoding="utf-8", newline="") as f:
            f.write("[storage]\n")
            f.write("file = '%s'\n" % os.path.join(self.tmp, "f"))
            f.write("html = '%s'\n" % os.path.join(self.tmp, "html"))
            f.write("json = '%s'\n" % os.path.join(self.tmp, "json"))
        self.env = dict(os.environ, HIB_CONFIG=cfg)
        self.hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")
        src = os.path.join(self.tmp, "src.txt")
        with open(src, "w", newline="") as f:
            f.write("hi\n")
        add_in = "\n".join(["", "report", "Old Title", "", "1", "Doe:Jane",
                            "03/06/2026", "t1", "", ""]) + "\n"
        p = self._hib(["add", src], add_in)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        # The JSON is named after the reference; the citekey lives inside it.
        self.json_name = os.listdir(os.path.join(self.tmp, "json"))[0]
        import model
        with open(os.path.join(self.tmp, "json", self.json_name), encoding="utf-8") as f:
            self.citekey = model.parse(f.read()).citekey

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _hib(self, args, stdin=""):
        return subprocess.run([sys.executable, self.hib] + args,
                              input=stdin.encode("utf-8"), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=self.env)

    def _json_bytes(self):
        with open(os.path.join(self.tmp, "json", self.json_name), "rb") as f:
            return f.read()

    def test_dash_ctk_rekeys_the_entry(self):
        p = self._hib(["update", "-ctk", self.citekey, "ReKeyed2026"])
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "json")), [self.json_name])
        self.assertIn(b'"citekey": "ReKeyed2026"', self._json_bytes())

    def test_dash_citekey_still_selects_for_the_interactive_update(self):
        # Long form: the metadata prompts run (all defaults kept), so the entry is
        # edited in place and the citekey is untouched.
        upd_in = "\n".join(["", "", "1", "", "", "1", "", "", ""]) + "\n"
        p = self._hib(["update", "-citekey", self.citekey], upd_in)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "json")), [self.json_name])
        self.assertIn(b"update an entry", p.stdout)

    def test_the_usage_documents_the_mode(self):
        p = self._hib(["--help"])
        self.assertIn(b"hib update -ctk", p.stdout)


class TestRenameAllJson(unittest.TestCase):
    """`hib update -json-names [-n]`: the migration that renames every metadata
    file to '<reference>.json'. hib used to name them after the citekey."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_jsonnames_")
        for sub in ("f", "html", "json"):
            os.makedirs(os.path.join(self.tmp, sub))
        self.cfg = _Cfg(os.path.join(self.tmp, "f"),
                        os.path.join(self.tmp, "html"),
                        os.path.join(self.tmp, "json"))
        self.msgs = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _out(self, s):
        self.msgs.append(s)

    def _said(self, needle):
        return any(needle in m for m in self.msgs)

    def _write(self, file_name, citekey, reference):
        meta = {
            "citekey": citekey, "reference": reference, "title": "T " + citekey,
            "shortTitle": "S", "itemType": "document", "version": "1",
            "date": "03/06/2026", "description": "",
            "localFilePath": os.path.join(self.tmp, "f", "a1", "x.docx"),
            "localFolderPath": os.path.join(self.tmp, "f", "a1"),
            "htmlPath": os.path.join(self.tmp, "html", citekey + ".html"),
            "pdfLocalPath": "", "authors": [], "tags": [],
        }
        full = os.path.join(self.tmp, "json", file_name)
        with open(full, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(meta))
        return full

    def _names(self):
        return sorted(os.listdir(os.path.join(self.tmp, "json")))

    def test_renames_a_citekey_named_file(self):
        self._write("ReportRigal20260603.json", "ReportRigal20260603",
                    "report_Etude_Rig_20260603")
        self.assertEqual(updcmd._rename_all_json(self.cfg, False, self._out), 0)
        self.assertEqual(self._names(), ["report_Etude_Rig_20260603.json"])

    def test_dry_run_touches_nothing(self):
        self._write("ReportRigal20260603.json", "ReportRigal20260603",
                    "report_Etude_Rig_20260603")
        self.assertEqual(updcmd._rename_all_json(self.cfg, True, self._out), 0)
        self.assertEqual(self._names(), ["ReportRigal20260603.json"])
        self.assertTrue(self._said("would rename"))

    def test_content_is_untouched_by_the_rename(self):
        full = self._write("K.json", "K", "ref_one")
        with open(full, encoding="utf-8") as f:
            before = f.read()
        self.assertEqual(updcmd._rename_all_json(self.cfg, False, self._out), 0)
        with open(os.path.join(self.tmp, "json", "ref_one.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), before)

    def test_an_already_correct_name_is_left_alone(self):
        self._write("ref_one.json", "K", "ref_one")
        self.assertEqual(updcmd._rename_all_json(self.cfg, False, self._out), 0)
        self.assertEqual(self._names(), ["ref_one.json"])
        self.assertTrue(self._said("1 already named after their reference"))

    def test_two_entries_sharing_a_reference_are_numbered_not_lost(self):
        self._write("A.json", "A", "same_ref")
        self._write("B.json", "B", "same_ref")
        self.assertEqual(updcmd._rename_all_json(self.cfg, False, self._out), 0)
        self.assertEqual(self._names(), ["same_ref.json", "same_ref_1.json"])

    def test_a_reference_less_entry_falls_back_to_its_citekey(self):
        self._write("weird name.json", "OnlyKey", "")
        self.assertEqual(updcmd._rename_all_json(self.cfg, False, self._out), 0)
        self.assertEqual(self._names(), ["OnlyKey.json"])

    def test_a_foreign_json_is_skipped(self):
        with open(os.path.join(self.tmp, "json", "notes.json"), "w",
                  encoding="utf-8", newline="") as f:
            f.write("[1, 2, 3]")
        self.assertEqual(updcmd._rename_all_json(self.cfg, False, self._out), 0)
        self.assertEqual(self._names(), ["notes.json"])
        self.assertTrue(self._said("unreadable / not hib JSON"))


class TestReferenceIsImmutable(unittest.TestCase):
    """The reference is hib's internal identifier: `update` never re-prompts it,
    and `update -json` never takes it from the card. Checked through the CLI."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_refimm_")
        for sub in ("f", "html", "json"):
            os.makedirs(os.path.join(self.tmp, sub))
        cfg = os.path.join(self.tmp, "config.toml")
        with open(cfg, "w", encoding="utf-8", newline="") as f:
            f.write("[storage]\n")
            f.write("file = '%s'\n" % os.path.join(self.tmp, "f"))
            f.write("html = '%s'\n" % os.path.join(self.tmp, "html"))
            f.write("json = '%s'\n" % os.path.join(self.tmp, "json"))
        self.env = dict(os.environ, HIB_CONFIG=cfg)
        self.hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")
        src = os.path.join(self.tmp, "src.txt")
        with open(src, "w", newline="") as f:
            f.write("hi\n")
        add_in = "\n".join(["", "report", "Old Title", "", "1", "Doe:Jane",
                            "03/06/2026", "t1", "", ""]) + "\n"
        p = self._hib(["add", src], add_in)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.json_name = os.listdir(os.path.join(self.tmp, "json"))[0]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _hib(self, args, stdin=""):
        return subprocess.run([sys.executable, self.hib] + args,
                              input=stdin.encode("utf-8"), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=self.env)

    def _meta(self):
        import model
        with open(os.path.join(self.tmp, "json", os.listdir(
                os.path.join(self.tmp, "json"))[0]), encoding="utf-8") as f:
            return model.parse(f.read())

    def test_add_names_the_json_after_the_reference(self):
        self.assertEqual(self.json_name, "report_Old_Title_Doe_20260603.json")
        self.assertEqual(self._meta().reference, "report_Old_Title_Doe_20260603")

    def test_update_does_not_reprompt_or_change_the_reference(self):
        before = self._meta().reference
        # Change the title (which renames the card); keep every other default.
        upd_in = "\n".join(["", "New Title", "1", "", "", "1", "", "", ""]) + "\n"
        p = self._hib(["update", "-citekey", self._meta().citekey], upd_in)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertNotIn(b"Reference", p.stdout)              # no prompt for it
        self.assertEqual(self._meta().reference, before)      # value kept
        self.assertEqual(self._meta().title, "New Title")     # the edit did land
        self.assertEqual(os.listdir(os.path.join(self.tmp, "json")), [self.json_name])

    def test_update_json_ignores_a_reference_edited_in_the_card(self):
        card = self._meta().html_path
        with open(card, encoding="utf-8") as f:
            html = f.read()
        before = self._meta().reference
        html = html.replace(before, "HAND_EDITED_REF")
        with open(card, "w", encoding="utf-8", newline="") as f:
            f.write(html)
        p = self._hib(["update", "-json", self._meta().citekey])
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertEqual(self._meta().reference, before)      # unchanged
        self.assertEqual(os.listdir(os.path.join(self.tmp, "json")), [self.json_name])


if __name__ == "__main__":
    unittest.main()
