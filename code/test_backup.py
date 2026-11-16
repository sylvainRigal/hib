import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

import backupcmd
import config as config_mod
import entry as entry_mod
import html as html_mod
import metadata as metadata_mod
import model


def _write(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


class Archive(object):
    """A throw-away archive (f/html/json/trash) plus a backup target."""

    def __init__(self, tmp, f=None, html=None):
        self.tmp = tmp
        self.f = f or os.path.join(tmp, "f")
        self.html = html or os.path.join(tmp, "html")
        self.json = os.path.join(tmp, "json")
        self.target = os.path.join(tmp, "backup")
        for d in (self.f, self.html, self.json):
            os.makedirs(d, exist_ok=True)
        self.config = config_mod.Config(self.f, self.html, self.json)

    def add(self, name, title, tags, folder=None, card=None, extra_files=True):
        folder = folder or ("a20260101%08x" % (abs(hash(name)) & 0xffffffff))
        card = card or (title + ".html")
        fdir = os.path.join(self.f, folder)
        local_file = os.path.join(fdir, title + ".txt")
        _write(local_file, "content of %s\n" % title)
        if extra_files:
            _write(os.path.join(fdir, "sub", "deeper", "note.txt"), "nested\n")
            os.makedirs(os.path.join(fdir, "emptydir"), exist_ok=True)
        card_path = os.path.join(self.html, card)
        e = entry_mod.Entry(title=title, item_type="report", authors=[("Doe", "Jane")],
                            date="01/01/2026", tags=list(tags), description="d",
                            reference=name, citekey="Ck" + title, local_path=local_file)
        _write(card_path, html_mod.render_entry(e))
        meta = metadata_mod.Metadata(citekey="Ck" + title, entry=e,
                                     local_file_path=local_file, local_folder_path=fdir,
                                     html_path=card_path, pdf_local_path="")
        jpath = os.path.join(self.json, name + ".json")
        _write(jpath, metadata_mod.render(meta))
        return jpath, card_path, fdir

    def set_tags(self, jpath, tags):
        m = model.parse(_read(jpath))
        meta = backupcmd._meta_from_parsed(m, tags)
        _write(jpath, metadata_mod.render(meta))

    def run(self, *args, **kw):
        cfg = kw.get("config", self.config)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = backupcmd.run_backup(cfg, list(args))
        return rc, buf.getvalue()

    def t(self, *parts):
        return os.path.join(self.target, *parts)


def _rmtree(path):
    """rmtree that also removes read-only files (Windows)."""
    def onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerror)


def _junction(link, target):
    if sys.platform != "win32":
        return False
    r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode == 0


def _snapshot(root):
    snap = {}
    for r, _, files in os.walk(root):
        for f in files:
            p = os.path.join(r, f)
            with open(p, "rb") as fh:
                snap[p] = (fh.read(), os.stat(p).st_mtime)
    return snap


def _tags_of(jpath):
    return model.parse(_read(jpath)).tags


def _card_tags(path):
    import cardparse
    return cardparse.parse_card(_read(path))["tags"]


class TestTagHelpers(unittest.TestCase):
    def test_has_tag_trim_and_case(self):
        self.assertTrue(backupcmd.has_tag(["x", " NoBackup "], "nobackup"))
        self.assertFalse(backupcmd.has_tag(["nobackups", "no backup"], "nobackup"))

    def test_json_roundtrip_is_lossless_for_hib_json(self):
        e = entry_mod.Entry(title='T "q" \u00e9', item_type="book", authors=[("A", "B"), ("C", "")],
                            date="d", tags=["a", "b"], description="line1\nline2",
                            version="2", reference="r", citekey="c")
        for rp in (None, "", "\\\\srv\\x.pdf"):
            m = metadata_mod.Metadata("c", e, "C:\\f\\a\\x.pdf", "C:\\f\\a", "C:\\h\\T.html", "", rp)
            text = metadata_mod.render(m)
            self.assertEqual(metadata_mod.render(backupcmd._meta_from_parsed(model.parse(text),
                                                                             model.parse(text).tags)), text)
            new = backupcmd.tag_json_text_old(text)
            # Exactly one change: the tag list.
            self.assertEqual(new, text.replace('"tags": ["a", "b"]', '"tags": ["a", "b", "old"]'))
            self.assertIsNone(backupcmd.tag_json_text_old(new))    # idempotent

    def test_json_non_canonical_keeps_every_key(self):
        text = '{"citekey": "c", "custom": {"k": [1, 2]}, "tags": ["x"], "version": 1.5}'
        new = backupcmd.tag_json_text_old(text)
        obj = json.loads(new)
        self.assertEqual(obj["custom"], {"k": [1, 2]})
        self.assertEqual(obj["version"], 1.5)
        self.assertEqual(obj["tags"], ["x", "old"])
        self.assertEqual(list(obj.keys()), ["citekey", "custom", "tags", "version"])
        self.assertIsNone(backupcmd.tag_json_text_old(new))
        # No tags key at all -> one is added.
        self.assertEqual(json.loads(backupcmd.tag_json_text_old('{"a": 1}'))["tags"], ["old"])
        # Already tagged in another case -> untouched.
        self.assertIsNone(backupcmd.tag_json_text_old('{"tags": ["OLD"]}'))

    def test_card_tagging_in_place(self):
        e = entry_mod.Entry(title="T", item_type="r", authors=[], date="", tags=["a"],
                            description="", local_path="C:\\f\\a\\x.docx", pdf_path="C:\\f\\a\\x.pdf")
        card = html_mod.render_entry(e)
        new = backupcmd.tag_card_text_old(card)
        self.assertIn('    <span class="tag">a</span>\n    <span class="tag">old</span>\n  </p>', new)
        self.assertIn('<meta name="keywords" content="a, old">', new)
        # Exactly the two insertions, links / PDF button untouched.
        self.assertEqual(new.replace('    <span class="tag">old</span>\n', "", 1)
                         .replace("a, old", "a", 1), card)
        self.assertIn("pdf-btn", new)
        import cardparse
        self.assertEqual(cardparse.parse_card(new)["tags"], ["a", "old"])
        self.assertIsNone(backupcmd.tag_card_text_old(new))     # idempotent
        # No tags at all.
        e.tags = []
        new = backupcmd.tag_card_text_old(html_mod.render_entry(e))
        self.assertIn('<meta name="keywords" content="old">', new)
        self.assertEqual(cardparse.parse_card(new)["tags"], ["old"])
        with self.assertRaises(ValueError):
            backupcmd.tag_card_text_old("<html>not a card</html>")


class TestBackupHelpers(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "drive roots are Windows paths")
    def test_norm_root_keeps_drive_root(self):
        old = os.getcwd()
        tmp = tempfile.mkdtemp(prefix="hibpy_backup_nr_")
        try:
            os.chdir(tmp)       # the per-drive cwd must never leak in
            drive = os.path.splitdrive(tmp)[0]
            for p in (drive + "\\", drive + "/"):
                self.assertEqual(backupcmd._norm_root(p), drive + "\\")
                self.assertEqual(os.path.join(backupcmd._norm_root(p), "json"), drive + "\\json")
            self.assertEqual(backupcmd._norm_root(tmp + "\\"), tmp)
        finally:
            os.chdir(old)
            shutil.rmtree(tmp, ignore_errors=True)

    def test_safe_base(self):
        self.assertEqual(backupcmd._safe_base("C:\\h\\Card.html"), "Card.html")
        self.assertEqual(backupcmd._safe_base("C:\\f\\a2026\\"), "a2026")
        for bad in ("C:card.html", "card.html:ads", "", "C:\\h\\..", "."):
            self.assertIsNone(backupcmd._safe_base(bad), bad)


class TestBackup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_backup_")
        self.a = Archive(self.tmp)

    def tearDown(self):
        _rmtree(self.tmp)

    def test_missing_target_is_an_error(self):
        rc, o = self.a.run()
        self.assertEqual(rc, 1)
        self.assertIn("no backup target", o)

    def test_bad_args(self):
        self.assertEqual(self.a.run("x", "y")[0], 1)
        self.assertEqual(self.a.run("-z", self.a.target)[0], 1)

    def test_full_copy_with_nested_folders(self):
        j, c, fdir = self.a.add("doc_one", "One", ["t"])
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        leaf = os.path.basename(fdir)
        self.assertEqual(_read(self.a.t("json", "doc_one.json")), _read(j))
        self.assertEqual(_read(self.a.t("html", "One.html")), _read(c))
        self.assertTrue(os.path.isfile(self.a.t("file", leaf, "One.txt")))
        self.assertEqual(_read(self.a.t("file", leaf, "sub", "deeper", "note.txt")), "nested\n")
        self.assertTrue(os.path.isdir(self.a.t("file", leaf, "emptydir")))
        # mtime preserved.
        self.assertAlmostEqual(os.stat(self.a.t("json", "doc_one.json")).st_mtime,
                               os.stat(j).st_mtime, delta=0.01)
        self.assertIn("items backed up       : 1", o)

    def test_config_target_and_cli_override(self):
        self.a.add("doc_one", "One", [])
        self.a.config.backup_target = os.path.join(self.tmp, "fromconfig")
        rc, _ = self.a.run()
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "fromconfig", "json", "doc_one.json")))
        rc, _ = self.a.run(os.path.join(self.tmp, "fromcli"))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "fromcli", "json", "doc_one.json")))

    def test_nobackup_fully_excluded_any_case(self):
        _, _, f1 = self.a.add("doc_a", "A", ["NoBackup"])
        _, _, f2 = self.a.add("doc_b", "B", ["x", "  nobackup "])
        _, _, f3 = self.a.add("doc_c", "C", ["NOBACKUP"])
        self.a.add("doc_d", "D", ["nobackups"])         # not the tag
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertEqual(os.listdir(self.a.t("json")), ["doc_d.json"])
        self.assertEqual(os.listdir(self.a.t("html")), ["D.html"])
        self.assertEqual(len(os.listdir(self.a.t("file"))), 1)
        self.assertIn("items skipped nobackup: 3", o)
        # Their cards/folders are not orphans either.
        self.assertIn("orphans ignored       : 0 card(s), 0 folder(s)", o)

    def test_incremental_second_run_and_modified_file(self):
        _, _, fdir = self.a.add("doc_one", "One", [])
        self.a.run(self.a.target)
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0)
        self.assertIn("files copied          : 0", o)
        self.assertIn("files unchanged       : 4", o)    # json, card, One.txt, note.txt
        nested = os.path.join(fdir, "sub", "deeper", "note.txt")
        _write(nested, "changed, longer\n")
        rc, o = self.a.run(self.a.target)
        self.assertIn("files copied          : 1", o)
        leaf = os.path.basename(fdir)
        self.assertEqual(_read(self.a.t("file", leaf, "sub", "deeper", "note.txt")), "changed, longer\n")
        # Same size, mtime moved by more than 2 s -> recopied too.
        _write(nested, "CHANGED, LONGER\n")
        st = os.stat(nested)
        os.utime(nested, (st.st_atime, st.st_mtime + 10))
        rc, o = self.a.run(self.a.target)
        self.assertIn("files copied          : 1", o)
        self.assertEqual(_read(self.a.t("file", leaf, "sub", "deeper", "note.txt")), "CHANGED, LONGER\n")

    def test_mtime_within_tolerance_is_unchanged(self):
        _, _, fdir = self.a.add("doc_one", "One", [], extra_files=False)
        self.a.run(self.a.target)
        dst = self.a.t("file", os.path.basename(fdir), "One.txt")
        st = os.stat(dst)
        os.utime(dst, (st.st_atime, st.st_mtime + 1.5))    # FAT rounding
        _, o = self.a.run(self.a.target)
        self.assertIn("files copied          : 0", o)

    def test_deleted_item_tagged_old_idempotently(self):
        j, c, fdir = self.a.add("doc_gone", "Gone", ["keep"])
        self.a.add("doc_live", "Live", [])
        self.a.run(self.a.target)
        os.remove(j)
        os.remove(c)
        shutil.rmtree(fdir)
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertEqual(_tags_of(self.a.t("json", "doc_gone.json")), ["keep", "old"])
        self.assertEqual(_card_tags(self.a.t("html", "Gone.html")), ["keep", "old"])
        self.assertTrue(os.path.isdir(self.a.t("file", os.path.basename(fdir))))   # never deleted
        self.assertEqual(_tags_of(self.a.t("json", "doc_live.json")), [])
        self.assertEqual(_card_tags(self.a.t("html", "Live.html")), [])
        self.assertIn("tagged old            : 1 JSON, 1 card(s)", o)
        jtext, ctext = _read(self.a.t("json", "doc_gone.json")), _read(self.a.t("html", "Gone.html"))
        rc, o = self.a.run(self.a.target)
        self.assertIn("tagged old            : 0 JSON, 0 card(s)  (2 already old)", o)
        self.assertEqual(_read(self.a.t("json", "doc_gone.json")), jtext)
        self.assertEqual(_read(self.a.t("html", "Gone.html")), ctext)

    def test_item_turned_nobackup_is_tagged_old(self):
        j, _, _ = self.a.add("doc_x", "X", ["a"])
        self.a.run(self.a.target)
        self.a.set_tags(j, ["a", "nobackup"])
        self.a.run(self.a.target)
        self.assertEqual(_tags_of(self.a.t("json", "doc_x.json")), ["a", "old"])  # old copy, not refreshed
        self.assertEqual(_card_tags(self.a.t("html", "X.html")), ["a", "old"])

    def test_renamed_json_keeps_old_copy_without_touching_live_card(self):
        j, c, _ = self.a.add("doc_oldname", "Same", ["t"])
        self.a.run(self.a.target)
        os.rename(j, os.path.join(self.a.json, "doc_newname.json"))
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertEqual(_tags_of(self.a.t("json", "doc_oldname.json")), ["t", "old"])
        self.assertEqual(_tags_of(self.a.t("json", "doc_newname.json")), ["t"])
        # The card both JSONs name belongs to the live item: untouched.
        self.assertEqual(_read(self.a.t("html", "Same.html")), _read(c))
        self.assertEqual(_card_tags(self.a.t("html", "Same.html")), ["t"])

    def test_renamed_card_old_card_tagged(self):
        j, c, fdir = self.a.add("doc_k", "First", ["t"])
        self.a.run(self.a.target)
        # Card renamed (title change), JSON name unchanged.
        newcard = os.path.join(self.a.html, "Second.html")
        os.rename(c, newcard)
        text = _read(j).replace("First.html", "Second.html")
        _write(j, text)
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertEqual(_card_tags(self.a.t("html", "First.html")), ["t", "old"])
        self.assertEqual(_card_tags(self.a.t("html", "Second.html")), ["t"])
        self.assertEqual(_tags_of(self.a.t("json", "doc_k.json")), ["t"])

    def test_dry_run_reports_what_real_run_tags(self):
        j, c, fdir = self.a.add("doc_k", "First", ["t"])
        self.a.run(self.a.target)
        os.rename(c, os.path.join(self.a.html, "Second.html"))
        _write(j, _read(j).replace("First.html", "Second.html"))
        before = _snapshot(self.a.target)
        rc, dry = self.a.run(self.a.target, "-n")
        self.assertEqual(rc, 0, dry)
        self.assertEqual(_snapshot(self.a.target), before)
        self.assertIn("would tag old  card %s" % self.a.t("html", "First.html"), dry)
        self.assertNotIn("would tag old  json", dry)
        self.assertIn("tagged old            : 0 JSON, 1 card(s)", dry)
        rc, real = self.a.run(self.a.target)
        self.assertEqual(rc, 0, real)
        self.assertIn("tagged old            : 0 JSON, 1 card(s)", real)
        self.assertEqual(_card_tags(self.a.t("html", "First.html")), ["t", "old"])

    def test_restored_item_loses_old_tag(self):
        j, c, fdir = self.a.add("doc_r", "R", ["t"])
        self.a.run(self.a.target)
        saved_j, saved_c = _read(j), _read(c)
        st_j, st_c = os.stat(j), os.stat(c)
        self.a.set_tags(j, ["t", "nobackup"])
        self.a.run(self.a.target)
        self.assertIn("old", _tags_of(self.a.t("json", "doc_r.json")))
        # Restore the exact original archive files, original mtimes included.
        _write(j, saved_j)
        os.utime(j, (st_j.st_atime, st_j.st_mtime))
        # Worst case: the tagged copies carry the archive's mtime.
        for p, st in ((self.a.t("json", "doc_r.json"), st_j), (self.a.t("html", "R.html"), st_c)):
            os.utime(p, (st.st_atime, st.st_mtime))
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertEqual(_read(self.a.t("json", "doc_r.json")), saved_j)
        self.assertEqual(_read(self.a.t("html", "R.html")), saved_c)

    def test_same_size_same_mtime_different_json_is_recopied(self):
        j, _, _ = self.a.add("doc_s", "S", ["aaa"])
        self.a.run(self.a.target)
        dst = self.a.t("json", "doc_s.json")
        _write(dst, _read(j).replace('"aaa"', '"bbb"'))
        st = os.stat(j)
        os.utime(dst, (st.st_atime, st.st_mtime))
        _, o = self.a.run(self.a.target)
        self.assertIn("files copied          : 1", o)
        self.assertEqual(_tags_of(dst), ["aaa"])

    def test_same_size_same_mtime_different_card_is_recopied(self):
        _, c, _ = self.a.add("doc_s", "S", ["aaa"])
        self.a.run(self.a.target)
        dst = self.a.t("html", "S.html")
        _write(dst, _read(c).replace(">aaa<", ">bbb<"))
        self.assertEqual(os.path.getsize(dst), os.path.getsize(c))
        st = os.stat(c)
        os.utime(dst, (st.st_atime, st.st_mtime))
        _, o = self.a.run(self.a.target)
        self.assertIn("files copied          : 1", o)
        self.assertEqual(_read(dst), _read(c))

    def test_string_tags_nobackup_is_honoured(self):
        j, _, _ = self.a.add("doc_s", "S", ["nobackup"])
        _write(j, _read(j).replace('"tags": ["nobackup"]', '"tags": "nobackup"'))
        self.assertIn('"tags": "nobackup"', _read(j))
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertEqual(os.listdir(self.a.t("json")), [])
        self.assertEqual(os.listdir(self.a.t("html")), [])
        self.assertEqual(os.listdir(self.a.t("file")), [])
        self.assertIn("items skipped nobackup: 1", o)

    def test_read_only_copies_can_be_updated_and_tagged(self):
        j, c, fdir = self.a.add("doc_ro", "Ro", ["t"], extra_files=False)
        f = os.path.join(fdir, "Ro.txt")
        os.chmod(f, stat.S_IREAD)
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        dst = self.a.t("file", os.path.basename(fdir), "Ro.txt")
        self.assertFalse(os.stat(dst).st_mode & stat.S_IWRITE)     # mirrored attribute
        os.chmod(f, stat.S_IWRITE | stat.S_IREAD)
        _write(f, "a new, longer content\n")
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertEqual(_read(dst), "a new, longer content\n")
        # Old tagging of read-only backup copies.
        for p in (self.a.t("json", "doc_ro.json"), self.a.t("html", "Ro.html")):
            os.chmod(p, stat.S_IREAD)
        os.remove(j)
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertEqual(_tags_of(self.a.t("json", "doc_ro.json")), ["t", "old"])
        self.assertEqual(_card_tags(self.a.t("html", "Ro.html")), ["t", "old"])
        self.assertFalse(os.stat(self.a.t("json", "doc_ro.json")).st_mode & stat.S_IWRITE)

    def test_old_tagging_is_atomic(self):
        j, c, _ = self.a.add("doc_a", "A", ["t"])
        self.a.run(self.a.target)
        os.remove(j)
        tj, tc = self.a.t("json", "doc_a.json"), self.a.t("html", "A.html")
        saved = (_read(tj), _read(tc))
        # The final rename fails (crash, unplugged drive...): the backup copies
        # must be left whole, not truncated, and no temp file stays behind.
        with mock.patch("os.replace", side_effect=OSError(5, "simulated failure")):
            rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 1, o)
        self.assertIn("FAIL tag old  json", o)
        self.assertEqual((_read(tj), _read(tc)), saved)
        self.assertEqual(sorted(os.listdir(self.a.t("json"))), ["doc_a.json"])
        self.assertEqual(sorted(os.listdir(self.a.t("html"))), ["A.html"])

    def test_file_replacing_a_backed_up_folder_fails_cleanly(self):
        _, _, fdir = self.a.add("doc_n", "N", [], extra_files=False)
        leaf = os.path.basename(fdir)
        os.makedirs(os.path.join(fdir, "notes"))
        _write(os.path.join(fdir, "notes", "x.txt"), "x")
        self.a.run(self.a.target)
        shutil.rmtree(os.path.join(fdir, "notes"))
        _write(os.path.join(fdir, "notes"), "now a file")
        for _ in range(2):
            rc, o = self.a.run(self.a.target)
            self.assertEqual(rc, 1, o)
            self.assertIn("FAIL copy file", o)
            self.assertIn("files copied          : 0", o)
            self.assertEqual(os.listdir(self.a.t("file", leaf, "notes")), ["x.txt"])
        # Dry run reports it too, instead of "would copy".
        rc, o = self.a.run(self.a.target, "-n")
        self.assertEqual(rc, 1, o)
        self.assertNotIn("would copy file", o)

    def test_unstatable_entry_is_a_failure_not_a_link(self):
        _, _, fdir = self.a.add("doc_l", "L", [], extra_files=False)
        _write(os.path.join(fdir, "boom.txt"), "b")
        real = backupcmd._is_link

        def fake(p):
            if os.path.basename(p) == "boom.txt" and p.startswith(self.a.f):
                raise OSError(206, "The filename or extension is too long", p)
            return real(p)
        with mock.patch.object(backupcmd, "_is_link", side_effect=fake):
            rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 1, o)
        self.assertIn("boom.txt  (cannot read", o)
        self.assertNotIn("(link / junction)", o)
        self.assertIn("failures              : 1", o)

    def test_unstatable_card_is_a_failure(self):
        _, c, _ = self.a.add("doc_c", "C", [], extra_files=False)
        real = backupcmd._is_link

        def fake(p):
            if p == c:
                raise PermissionError(13, "Access is denied", p)
            return real(p)
        with mock.patch.object(backupcmd, "_is_link", side_effect=fake):
            rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 1, o)
        self.assertIn("FAIL  card", o)
        self.assertNotIn("is missing", o)

    def test_file_dir_nested_in_html_dir(self):
        tmp2 = os.path.join(self.tmp, "nested")
        hib_dir = os.path.join(tmp2, "hib")
        a = Archive(tmp2, f=os.path.join(hib_dir, "f"), html=hib_dir)
        _, _, fdir = a.add("doc_n", "N", [])
        rc, o = a.run(a.target)
        self.assertEqual(rc, 0, o)
        self.assertNotIn("storage/trash folder", o)
        leaf = os.path.basename(fdir)
        self.assertTrue(os.path.isfile(a.t("file", leaf, "N.txt")))
        self.assertEqual(_read(a.t("file", leaf, "sub", "deeper", "note.txt")), "nested\n")
        # The file dir itself is not taken for an orphan folder of the html dir.
        self.assertIn("orphans ignored       : 0 card(s), 0 folder(s)", o)

    def test_drive_relative_card_in_backup_json_never_escapes(self):
        # A deleted item's backup JSON names a drive-relative card: tagging it
        # must not resolve it against the process cwd.
        _, _, _ = self.a.add("doc_live", "Live", [])
        self.a.run(self.a.target)
        outside = os.path.join(self.tmp, "outside")
        _, ocard, _ = Archive(outside).add("doc_o", "Evil", ["t"])
        evil_text = _read(ocard)
        drive = os.path.splitdrive(self.tmp)[0] or "C:"
        meta = model.parse(_read(self.a.t("json", "doc_live.json")))
        bad = _read(self.a.t("json", "doc_live.json")).replace(
            json.dumps(meta.html_path)[1:-1], drive + "Evil.html")
        _write(self.a.t("json", "doc_gone.json"), bad)
        old = os.getcwd()
        os.chdir(os.path.dirname(ocard))
        try:
            rc, o = self.a.run(self.a.target)
        finally:
            os.chdir(old)
        self.assertEqual(rc, 0, o)
        self.assertEqual(_read(ocard), evil_text)
        self.assertIn("old", _tags_of(self.a.t("json", "doc_gone.json")))
        # And an archive JSON with such a card path is reported, not followed.
        j2, _, _ = self.a.add("doc_dr", "Dr", [], extra_files=False)
        m2 = model.parse(_read(j2))
        _write(j2, _read(j2).replace(json.dumps(m2.html_path)[1:-1], drive + "Evil.html"))
        os.chdir(os.path.dirname(ocard))
        try:
            rc, o = self.a.run(self.a.target)
        finally:
            os.chdir(old)
        self.assertIn("card path %sEvil.html is not usable" % drive, o)
        self.assertFalse(os.path.exists(self.a.t("html", "Evil.html")))

    @unittest.skipUnless(sys.platform == "win32", "drive roots are Windows paths")
    def test_drive_root_target_is_the_drive_root(self):
        # The archive lives on that drive, so its root CONTAINS the storage dirs:
        # refused, and the message names the drive root (not the cwd on it).
        self.a.add("doc_one", "One", [])
        drive = os.path.splitdrive(self.tmp)[0]
        old = os.getcwd()
        os.chdir(self.tmp)
        try:
            for t in (drive + "\\", drive + "/"):
                rc, o = self.a.run(t)
                self.assertEqual(rc, 1, o)
                self.assertIn("refusing to back up into '%s\\'" % drive, o)
        finally:
            os.chdir(old)

    @unittest.skipUnless(sys.platform == "win32", "junctions are Windows-only")
    def test_target_junction_into_archive_refused(self):
        j, c, _ = self.a.add("doc_x", "X", ["nobackup"])
        before = _snapshot(self.tmp)
        jn_arch = os.path.join(self.tmp, "jn_arch")     # -> the whole archive
        jn_json = os.path.join(self.tmp, "jn_json")     # -> the json dir
        if not (_junction(jn_arch, self.tmp) and _junction(jn_json, self.a.json)):
            self.skipTest("cannot create a junction here")
        try:
            for t in (jn_arch, os.path.join(jn_arch, "json"), jn_json,
                      os.path.join(jn_json, "bk")):
                rc, o = self.a.run(t)
                self.assertEqual(rc, 1, o)
                self.assertIn("refusing", o)
            self.assertEqual(_snapshot(self.a.json), {k: v for k, v in before.items()
                                                       if k.startswith(self.a.json)})
            self.assertEqual(_tags_of(j), ["nobackup"])
            self.assertEqual(_card_tags(c), ["nobackup"])
        finally:
            for l in (jn_arch, jn_json):
                if os.path.lexists(l):
                    os.rmdir(l)

    @unittest.skipUnless(sys.platform == "win32", "junctions are Windows-only")
    def test_target_subdir_junction_refused(self):
        j, c, _ = self.a.add("doc_x", "X", ["nobackup"])
        jtext = _read(j)
        os.makedirs(self.a.target)
        link = self.a.t("json")
        if not _junction(link, self.a.json):
            self.skipTest("cannot create a junction here")
        try:
            rc, o = self.a.run(self.a.target)
            self.assertEqual(rc, 1, o)
            self.assertIn("link / junction", o)
            self.assertEqual(_read(j), jtext)
        finally:
            os.rmdir(link)
        # A junction deeper in the backup (an item folder) is not written through.
        _, _, fdir = self.a.add("doc_y", "Y", [], extra_files=False)
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        os.makedirs(self.a.t("file"))
        link = self.a.t("file", os.path.basename(fdir))
        if not _junction(link, elsewhere):
            self.skipTest("cannot create a junction here")
        try:
            rc, o = self.a.run(self.a.target)
            self.assertEqual(rc, 1, o)
            self.assertIn("link / junction in the backup", o)
            self.assertEqual(os.listdir(elsewhere), [])
        finally:
            os.rmdir(link)

    def test_dry_run_changes_nothing(self):
        j, c, fdir = self.a.add("doc_one", "One", [])
        rc, o = self.a.run(self.a.target, "-n")
        self.assertEqual(rc, 0, o)
        self.assertFalse(os.path.exists(self.a.target))
        self.assertIn("would copy", o)
        # Now with a backup that would get old tags.
        self.a.run(self.a.target)
        os.remove(j)
        before = {}
        for root, _, files in os.walk(self.a.target):
            for f in files:
                p = os.path.join(root, f)
                before[p] = (_read(p) if p.endswith((".json", ".html")) else None, os.stat(p).st_mtime)
        rc, o = self.a.run("--dry-run", self.a.target)
        self.assertIn("would tag old  json", o)
        self.assertIn("would tag old  card", o)
        after = {}
        for root, _, files in os.walk(self.a.target):
            for f in files:
                p = os.path.join(root, f)
                after[p] = (_read(p) if p.endswith((".json", ".html")) else None, os.stat(p).st_mtime)
        self.assertEqual(before, after)

    def test_target_overlapping_storage_refused(self):
        self.a.add("doc_one", "One", [])
        for bad in (os.path.join(self.a.f, "bk"), self.a.html, os.path.join(self.a.json, "x"),
                    self.tmp):  # tmp contains the storage dirs
            rc, o = self.a.run(bad)
            self.assertEqual(rc, 1, bad)
            self.assertIn("refusing", o)
        self.assertFalse(os.path.exists(os.path.join(self.a.f, "bk")))

    def test_unreadable_json_reported_rest_backed_up(self):
        self.a.add("doc_ok", "Ok", [])
        _write(os.path.join(self.a.json, "broken.json"), "{not json")
        os.makedirs(os.path.join(self.a.json, "dir.json"))      # ignored, not an error
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 1)
        self.assertIn("broken.json", o)
        self.assertIn("failures              : 1", o)
        self.assertTrue(os.path.isfile(self.a.t("json", "doc_ok.json")))
        self.assertFalse(os.path.exists(self.a.t("json", "broken.json")))

    def test_unreadable_json_old_backup_left_alone(self):
        j, c, _ = self.a.add("doc_b", "B", ["t"])
        self.a.run(self.a.target)
        _write(j, "{broken")
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 1)
        self.assertEqual(_tags_of(self.a.t("json", "doc_b.json")), ["t"])
        self.assertEqual(_card_tags(self.a.t("html", "B.html")), ["t"])

    def test_orphans_not_copied(self):
        self.a.add("doc_one", "One", [])
        _write(os.path.join(self.a.html, "Zombie.html"), "<html>z</html>")
        _write(os.path.join(self.a.f, "zombiefolder", "x.txt"), "z")
        os.makedirs(os.path.join(self.a.f, "trash", "something"))
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertNotIn("Zombie.html", os.listdir(self.a.t("html")))
        self.assertNotIn("zombiefolder", os.listdir(self.a.t("file")))
        self.assertIn("orphans ignored       : 1 card(s), 1 folder(s)", o)

    def test_storage_folder_outside_root_uses_basename(self):
        # A JSON written under another prefix (archive moved) still finds its card
        # and folder by basename inside the configured roots.
        j, _, fdir = self.a.add("doc_m", "M", [])
        text = _read(j).replace(self.tmp.replace("\\", "\\\\"), "D:\\\\elsewhere")
        _write(j, text)
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertTrue(os.path.isfile(self.a.t("html", "M.html")))
        self.assertTrue(os.path.isfile(self.a.t("file", os.path.basename(fdir), "M.txt")))

    def test_nested_trash_inside_item_folder_is_not_descended(self):
        # trash configured INSIDE an item's folder: never copied.
        _, _, fdir = self.a.add("doc_t", "T", [], extra_files=False)
        cfg = config_mod.Config(self.a.f, self.a.html, self.a.json,
                                trash_path=os.path.join(fdir, "trash"))
        _write(os.path.join(fdir, "trash", "junk.txt"), "j")
        rc, o = self.a.run(self.a.target, config=cfg)
        self.assertEqual(rc, 0, o)
        leaf = os.path.basename(fdir)
        self.assertTrue(os.path.isfile(self.a.t("file", leaf, "T.txt")))
        self.assertFalse(os.path.exists(self.a.t("file", leaf, "trash")))

    @unittest.skipUnless(sys.platform == "win32", "junctions are Windows-only")
    def test_junction_inside_folder_skipped(self):
        _, _, fdir = self.a.add("doc_j", "J", [], extra_files=False)
        tgt = os.path.join(self.tmp, "elsewhere")
        _write(os.path.join(tgt, "secret.txt"), "s")
        link = os.path.join(fdir, "link")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, tgt],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode != 0:
            self.skipTest("cannot create a junction here")
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertFalse(os.path.exists(self.a.t("file", os.path.basename(fdir), "link")))
        os.rmdir(link)


class TestPurgeOld(unittest.TestCase):
    """hib backup --purge old: delete from the backup what is tagged old."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_bkpurge_")
        self.a = Archive(self.tmp)

    def tearDown(self):
        _rmtree(self.tmp)

    def purge(self, *args, **kw):
        """Run `--purge old` with `answer` piped on stdin (EOF when None)."""
        cfg = kw.get("config", self.a.config)
        answer = kw.get("answer")
        buf = io.StringIO()
        stdin = io.StringIO("" if answer is None else answer + "\n")
        with redirect_stdout(buf), mock.patch.object(sys, "stdin", stdin):
            rc = backupcmd.run_backup(cfg, ["--purge", "old"] + list(args))
        return rc, buf.getvalue()

    def deleted_item(self):
        """A backed-up item deleted from the archive, tagged old by a 2nd run,
        next to a live one. Returns (gone folder leaf, live folder leaf)."""
        j, c, fdir = self.a.add("doc_gone", "Gone", ["keep"])
        _, _, live_dir = self.a.add("doc_live", "Live", [])
        self.a.run(self.a.target)
        os.remove(j)
        os.remove(c)
        shutil.rmtree(fdir)
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        return os.path.basename(fdir), os.path.basename(live_dir)

    def test_bad_args_are_usage_errors(self):
        self.deleted_item()
        before = _snapshot(self.a.target)
        for args in (["--purge"], ["--purge", "new"], ["--purge", "nobackup"],
                     ["--purge", "old", "--purge", "old"], ["--purge", "old", "a", "b"],
                     ["--purge", "old", "-z"], ["--purge=old", self.a.target],
                     [self.a.target, "--purge"]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = backupcmd.run_backup(self.a.config, args)
            self.assertEqual(rc, 1, args)
            self.assertIn("hib backup --purge old [<target-dir>] [-n]", buf.getvalue(), args)
        self.assertEqual(_snapshot(self.a.target), before)

    def test_parse_purge_args(self):
        p = backupcmd._parse_purge_args
        self.assertEqual(p(["--purge", "old"]), (False, None))
        self.assertEqual(p(["--purge", " OLD ", "-n", "E:\\bk"]), (True, "E:\\bk"))
        self.assertEqual(p(["E:\\bk", "--dry-run", "--purge", "old"]), (True, "E:\\bk"))
        self.assertIsNone(p(["--purge", "-n"]))

    def test_no_target_is_an_error(self):
        rc, o = self.purge()
        self.assertEqual(rc, 1)
        self.assertIn("no backup target", o)
        rc, o = self.purge(os.path.join(self.tmp, "nowhere"), answer="y")
        self.assertEqual(rc, 1)
        self.assertIn("does not exist", o)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "nowhere")))

    def test_purge_does_not_run_a_backup(self):
        self.a.add("doc_one", "One", [])
        os.makedirs(self.a.target)
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertIn("Nothing to purge", o)
        self.assertEqual(os.listdir(self.a.target), [])

    def test_dry_run_lists_and_deletes_nothing(self):
        gone, live = self.deleted_item()
        before = _snapshot(self.a.target)
        dirs_before = sorted(os.listdir(self.a.t("file")))
        rc, o = self.purge(self.a.target, "-n", answer="y")
        self.assertEqual(rc, 0, o)
        self.assertIn("  [json]   %s" % self.a.t("json", "doc_gone.json"), o)
        self.assertIn("  [card]   %s" % self.a.t("html", "Gone.html"), o)
        self.assertIn("  [folder] %s" % self.a.t("file", gone), o)
        self.assertNotIn("doc_live", o)
        self.assertIn("to delete    : 1 JSON, 1 card(s), 1 folder(s)", o)
        self.assertIn("(dry run: nothing was deleted.)", o)
        self.assertNotIn("(y/N)", o)
        self.assertEqual(_snapshot(self.a.target), before)
        self.assertEqual(sorted(os.listdir(self.a.t("file"))), dirs_before)

    def test_default_answer_is_no(self):
        self.deleted_item()
        before = _snapshot(self.a.target)
        for answer in (None, "", "n", "no", "x"):
            rc, o = self.purge(self.a.target, answer=answer)
            self.assertEqual(rc, 0, o)
            self.assertIn("Delete these old entries from the backup permanently? (y/N)", o)
            self.assertIn("Aborted - nothing was deleted.", o)
            self.assertEqual(_snapshot(self.a.target), before)

    def test_yes_deletes_old_entry_and_keeps_live_and_archive(self):
        gone, live = self.deleted_item()
        archive_before = _snapshot(self.a.json)
        archive_before.update(_snapshot(self.a.html))
        archive_before.update(_snapshot(self.a.f))
        live_before = _snapshot(self.a.t("file", live))
        rc, o = self.purge(self.a.target, answer="Y")
        self.assertEqual(rc, 0, o)
        self.assertFalse(os.path.exists(self.a.t("json", "doc_gone.json")))
        self.assertFalse(os.path.exists(self.a.t("html", "Gone.html")))
        self.assertFalse(os.path.exists(self.a.t("file", gone)))
        self.assertTrue(os.path.isfile(self.a.t("json", "doc_live.json")))
        self.assertTrue(os.path.isfile(self.a.t("html", "Live.html")))
        self.assertEqual(_snapshot(self.a.t("file", live)), live_before)
        after = _snapshot(self.a.json)
        after.update(_snapshot(self.a.html))
        after.update(_snapshot(self.a.f))
        self.assertEqual(after, archive_before)
        self.assertIn("deleted      : 1 JSON, 1 card(s), 1 folder(s)", o)
        self.assertIn("failures     : 0", o)
        # Nothing left: a second purge has nothing to do; the next backup is clean.
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertIn("Nothing to purge", o)
        rc, o = self.a.run(self.a.target)
        self.assertEqual(rc, 0, o)
        self.assertIn("tagged old            : 0 JSON, 0 card(s)", o)

    def test_old_tag_any_case_and_string_tags(self):
        self.a.add("doc_a", "A", [], extra_files=False)
        self.a.add("doc_b", "B", [], extra_files=False)
        self.a.run(self.a.target)
        ja, jb = self.a.t("json", "doc_a.json"), self.a.t("json", "doc_b.json")
        self.a.set_tags(ja, [" OLD "])
        _write(jb, _read(jb).replace('"tags": []', '"tags": "old"'))
        self.assertIn('"tags": "old"', _read(jb))
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertEqual(os.listdir(self.a.t("json")), [])
        self.assertEqual(os.listdir(self.a.t("html")), [])
        self.assertEqual(os.listdir(self.a.t("file")), [])

    def test_renamed_json_shared_card_and_folder_are_kept(self):
        j, c, fdir = self.a.add("doc_oldname", "Same", ["t"])
        self.a.run(self.a.target)
        os.rename(j, os.path.join(self.a.json, "doc_newname.json"))
        self.a.run(self.a.target)
        self.assertEqual(_tags_of(self.a.t("json", "doc_oldname.json")), ["t", "old"])
        leaf = os.path.basename(fdir)
        folder_before = _snapshot(self.a.t("file", leaf))
        rc, o = self.purge(self.a.target, "-n")
        self.assertEqual(rc, 0, o)
        self.assertIn("Kept, shared with an item not tagged old (2):", o)
        self.assertIn("  [card] %s  (also named by doc_newname.json)"
                      % self.a.t("html", "Same.html"), o)
        self.assertIn("  [folder] %s  (also named by doc_newname.json)"
                      % self.a.t("file", leaf), o)
        self.assertNotIn("  [card]   ", o)
        self.assertNotIn("  [folder]   ", o)
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertFalse(os.path.exists(self.a.t("json", "doc_oldname.json")))
        self.assertTrue(os.path.isfile(self.a.t("json", "doc_newname.json")))
        self.assertEqual(_card_tags(self.a.t("html", "Same.html")), ["t"])
        self.assertEqual(_snapshot(self.a.t("file", leaf)), folder_before)
        self.assertIn("deleted      : 1 JSON, 0 card(s), 0 folder(s)", o)

    def test_renamed_card_old_card_deleted(self):
        j, c, fdir = self.a.add("doc_k", "First", ["t"])
        self.a.run(self.a.target)
        os.rename(c, os.path.join(self.a.html, "Second.html"))
        _write(j, _read(j).replace("First.html", "Second.html"))
        self.a.run(self.a.target)
        self.assertEqual(_card_tags(self.a.t("html", "First.html")), ["t", "old"])
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertFalse(os.path.exists(self.a.t("html", "First.html")))
        self.assertTrue(os.path.isfile(self.a.t("html", "Second.html")))
        self.assertTrue(os.path.isfile(self.a.t("json", "doc_k.json")))
        self.assertTrue(os.path.isdir(self.a.t("file", os.path.basename(fdir))))
        self.assertIn("deleted      : 0 JSON, 1 card(s), 0 folder(s)", o)

    def test_old_card_named_by_live_json_is_kept(self):
        self.a.add("doc_live", "Live", [])
        self.a.run(self.a.target)
        card = self.a.t("html", "Live.html")
        _write(card, backupcmd.tag_card_text_old(_read(card)))
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertIn("also named by doc_live.json", o)
        self.assertIn("Nothing to purge", o)
        self.assertTrue(os.path.isfile(card))

    def test_untagged_card_and_orphans_left_alone(self):
        gone, _ = self.deleted_item()
        stray = self.a.t("html", "Stray.html")
        _write(stray, "<html>no tags block</html>")
        orphan = self.a.t("file", "orphan_folder")
        _write(os.path.join(orphan, "x.txt"), "x")
        _write(self.a.t("json", "notes.txt"), "not a json")
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertTrue(os.path.isfile(stray))
        self.assertTrue(os.path.isfile(os.path.join(orphan, "x.txt")))
        self.assertTrue(os.path.isfile(self.a.t("json", "notes.txt")))
        self.assertFalse(os.path.exists(self.a.t("file", gone)))

    def test_unreadable_backup_json_aborts_everything(self):
        gone, _ = self.deleted_item()
        _write(self.a.t("json", "broken.json"), "{not json")
        os.makedirs(self.a.t("json", "dir.json"))           # a folder: ignored
        before = _snapshot(self.a.target)
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 1, o)
        self.assertIn("purge aborted", o)
        self.assertIn(self.a.t("json", "broken.json"), o)
        self.assertNotIn("(y/N)", o)
        self.assertEqual(_snapshot(self.a.target), before)
        self.assertTrue(os.path.isdir(self.a.t("file", gone)))

    def test_read_only_files_are_deleted(self):
        gone, _ = self.deleted_item()
        for root, _, files in os.walk(self.a.t("file", gone)):
            for f in files:
                os.chmod(os.path.join(root, f), stat.S_IREAD)
        for p in (self.a.t("json", "doc_gone.json"), self.a.t("html", "Gone.html")):
            os.chmod(p, stat.S_IREAD)
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertFalse(os.path.exists(self.a.t("file", gone)))
        self.assertFalse(os.path.exists(self.a.t("json", "doc_gone.json")))
        self.assertFalse(os.path.exists(self.a.t("html", "Gone.html")))

    def test_unsafe_recorded_paths_never_escape(self):
        self.a.add("doc_live", "Live", [], extra_files=False)
        self.a.run(self.a.target)
        # A hand-made old JSON whose folder/card paths end in '..' / a drive.
        jtext = _read(self.a.t("json", "doc_live.json"))
        m = model.parse(jtext)
        bad = jtext.replace(json.dumps(m.local_folder_path)[1:-1],
                            json.dumps(os.path.join(self.a.t("file"), ".."))[1:-1])
        bad = bad.replace(json.dumps(m.html_path)[1:-1], "C:Live.html")
        _write(self.a.t("json", "doc_bad.json"), bad)
        self.a.set_tags(self.a.t("json", "doc_bad.json"), ["old"])
        mb = model.parse(_read(self.a.t("json", "doc_bad.json")))
        self.assertEqual(mb.html_path, "C:Live.html")
        self.assertTrue(mb.local_folder_path.endswith(".."))
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertFalse(os.path.exists(self.a.t("json", "doc_bad.json")))
        self.assertTrue(os.path.isfile(self.a.t("json", "doc_live.json")))
        self.assertTrue(os.path.isfile(self.a.t("html", "Live.html")))
        self.assertEqual(len(os.listdir(self.a.t("file"))), 1)
        self.assertNotIn("also named by", o)
        self.assertIn("deleted      : 1 JSON, 0 card(s), 0 folder(s)", o)

    def test_failed_folder_delete_keeps_its_json(self):
        gone, _ = self.deleted_item()

        def failing(path, errors):
            errors.append((path, OSError("simulated")))
        with mock.patch.object(backupcmd, "_remove_tree", failing):
            rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 1, o)
        self.assertIn("FAIL delete folder", o)
        self.assertIn("kept json", o)
        self.assertTrue(os.path.isfile(self.a.t("json", "doc_gone.json")))
        self.assertTrue(os.path.isdir(self.a.t("file", gone)))
        self.assertIn("failures     : 1", o)
        # A re-run finishes the job.
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertFalse(os.path.exists(self.a.t("json", "doc_gone.json")))
        self.assertFalse(os.path.exists(self.a.t("file", gone)))

    def _old_copy_of(self, src_name, dst_name, folder=None, card=None):
        """Write <target>\\json\\<dst_name>: a copy of the backup JSON
        <src_name> with localFolderPath / htmlPath replaced, tagged old."""
        src = self.a.t("json", src_name)
        obj = json.loads(_read(src))
        if folder is not None:
            obj["localFolderPath"] = folder
        if card is not None:
            obj["htmlPath"] = card
        dst = self.a.t("json", dst_name)
        _write(dst, json.dumps(obj, indent=2))
        self.a.set_tags(dst, ["old"])
        return dst

    def test_purge_base_strips_trailing_dots_and_spaces(self):
        b = backupcmd._purge_base
        self.assertEqual(b("C:\\x\\Live.html."), "Live.html")
        self.assertEqual(b("C:\\x\\a2026 . "), "a2026")
        self.assertEqual(b("C:\\x\\Live.html"), "Live.html")
        self.assertIsNone(b("C:\\x\\..."))
        self.assertIsNone(b("C:\\x\\ . "))
        self.assertIsNone(b("C:Live.html."))

    def test_trailing_dot_names_never_reach_the_live_item(self):
        _, live = self.deleted_item()
        live_folder = self.a.t("file", live)
        live_card = self.a.t("html", "Live.html")
        live_before = _snapshot(live_folder)
        m = model.parse(_read(self.a.t("json", "doc_live.json")))
        dst = self._old_copy_of("doc_live.json", "doc_x.json",
                                folder=m.local_folder_path + ".",
                                card=m.html_path + ". ")
        self.assertIn("old", _tags_of(dst))
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertIn("  [folder] %s  (also named by doc_live.json)" % live_folder, o)
        self.assertIn("  [card] %s  (also named by doc_live.json)" % live_card, o)
        self.assertNotIn("%s." % live_folder, o)
        self.assertEqual(_snapshot(live_folder), live_before)
        self.assertTrue(os.path.isfile(live_card))
        self.assertFalse(os.path.exists(dst))
        self.assertTrue(os.path.isfile(self.a.t("json", "doc_live.json")))

    def test_upper_case_json_extension_protects_shared_entries(self):
        j, c, fdir = self.a.add("doc_oldname", "Same", ["t"])
        self.a.run(self.a.target)
        os.rename(j, os.path.join(self.a.json, "doc_newname.json"))
        self.a.run(self.a.target)
        os.rename(self.a.t("json", "doc_newname.json"), self.a.t("json", "doc_newname.JSON"))
        leaf = os.path.basename(fdir)
        folder_before = _snapshot(self.a.t("file", leaf))
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertIn("also named by doc_newname.JSON", o)
        self.assertIn("kept (shared): 2", o)
        self.assertEqual(_snapshot(self.a.t("file", leaf)), folder_before)
        self.assertTrue(os.path.isfile(self.a.t("html", "Same.html")))
        self.assertFalse(os.path.exists(self.a.t("json", "doc_oldname.json")))
        # An old JSON with an upper-case extension is purged too.
        gone, _ = self.deleted_item()
        os.rename(self.a.t("json", "doc_gone.json"), self.a.t("json", "doc_gone.Json"))
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertFalse(os.path.exists(self.a.t("json", "doc_gone.Json")))
        self.assertFalse(os.path.exists(self.a.t("file", gone)))

    def test_unstatable_folder_of_old_json_keeps_the_json(self):
        gone, _ = self.deleted_item()
        gone_dir = self.a.t("file", gone)
        real = backupcmd._path_state

        def fake(p):
            if os.path.normcase(p) == os.path.normcase(gone_dir):
                return PermissionError(13, "simulated access denied")
            return real(p)
        with mock.patch.object(backupcmd, "_path_state", fake):
            rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 1, o)
        self.assertIn("FAIL  folder %s cannot be checked" % gone_dir, o)
        self.assertIn("kept json", o)
        self.assertIn("failures     : 1", o)
        self.assertTrue(os.path.isfile(self.a.t("json", "doc_gone.json")))
        self.assertTrue(os.path.isdir(gone_dir))
        self.assertFalse(os.path.exists(self.a.t("html", "Gone.html")))
        # A re-run (the folder readable again) finishes the job.
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertFalse(os.path.exists(self.a.t("json", "doc_gone.json")))
        self.assertFalse(os.path.exists(gone_dir))

    def test_unstatable_entries_only_nothing_deleted(self):
        gone, _ = self.deleted_item()
        gone_dir = self.a.t("file", gone)
        gone_card = self.a.t("html", "Gone.html")
        real = backupcmd._path_state

        def fake(p):
            if os.path.normcase(p) in (os.path.normcase(gone_dir), os.path.normcase(gone_card)):
                return OSError(36, "simulated path too long")
            return real(p)
        before = _snapshot(self.a.target)
        with mock.patch.object(backupcmd, "_path_state", fake):
            rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 1, o)
        self.assertIn("Nothing can be deleted", o)
        self.assertNotIn("(y/N)", o)
        self.assertEqual(_snapshot(self.a.target), before)

    def test_folder_of_wrong_type_keeps_the_json(self):
        gone, _ = self.deleted_item()
        gone_dir = self.a.t("file", gone)
        _rmtree(gone_dir)
        _write(gone_dir, "a file where the folder should be")
        rc, o = self.purge(self.a.target, "-n")
        self.assertEqual(rc, 1, o)
        self.assertIn("FAIL  folder %s is not a folder" % gone_dir, o)
        self.assertIn("to delete    : 0 JSON, 1 card(s), 0 folder(s)", o)
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 1, o)
        self.assertTrue(os.path.isfile(gone_dir))
        self.assertTrue(os.path.isfile(self.a.t("json", "doc_gone.json")))

    def test_kept_lists_only_entries_that_exist(self):
        j, c, fdir = self.a.add("doc_oldname", "Same", ["t"])
        self.a.run(self.a.target)
        os.rename(j, os.path.join(self.a.json, "doc_newname.json"))
        self.a.run(self.a.target)
        leaf = os.path.basename(fdir)
        _rmtree(self.a.t("file", leaf))
        rc, o = self.purge(self.a.target, "-n")
        self.assertEqual(rc, 0, o)
        self.assertIn("Kept, shared with an item not tagged old (1):", o)
        self.assertIn("  [card] %s" % self.a.t("html", "Same.html"), o)
        self.assertNotIn(self.a.t("file", leaf), o)
        self.assertIn("kept (shared): 1", o)

    @unittest.skipUnless(sys.platform == "win32", "junctions are Windows-only")
    def test_target_junction_into_storage_subdir_refused_without_realpath(self):
        # Python < 3.8: os.path.realpath does not resolve junctions on Windows.
        inner = os.path.join(self.a.f, "x")
        _write(os.path.join(inner, "json", "keep.json"), '{"tags": ["old"]}')
        _write(os.path.join(inner, "file", "keep", "a.txt"), "a")
        bk = os.path.join(self.tmp, "bk")
        if not _junction(bk, inner):
            self.skipTest("cannot create a junction here")
        try:
            before = _snapshot(inner)
            with mock.patch("os.path.realpath", os.path.abspath):
                self.assertTrue(backupcmd._overlaps(bk, self.a.f))
                self.assertTrue(backupcmd._overlaps(os.path.join(bk, "new"), self.a.f))
                rc, o = self.purge(bk, answer="y")
                self.assertEqual(rc, 1, o)
                self.assertIn("refusing to purge", o)
                rc, o = self.a.run(bk)
                self.assertEqual(rc, 1, o)
                self.assertIn("refusing to back up", o)
            self.assertEqual(_snapshot(inner), before)
        finally:
            if os.path.lexists(bk):
                os.rmdir(bk)

    def test_target_overlapping_storage_refused(self):
        self.a.add("doc_x", "X", ["old"])
        before = _snapshot(self.tmp)
        for t in (self.tmp, self.a.json, os.path.join(self.a.f, "bk")):
            rc, o = self.purge(t, answer="y")
            self.assertEqual(rc, 1, o)
            self.assertIn("refusing to purge", o)
        self.assertEqual(_snapshot(self.tmp), before)

    @unittest.skipUnless(sys.platform == "win32", "junctions are Windows-only")
    def test_target_subdir_junction_refused(self):
        self.a.add("doc_x", "X", ["old"])
        os.makedirs(self.a.target)
        link = self.a.t("json")
        if not _junction(link, self.a.json):
            self.skipTest("cannot create a junction here")
        try:
            rc, o = self.purge(self.a.target, answer="y")
            self.assertEqual(rc, 1, o)
            self.assertIn("refusing to purge: '%s' is a link / junction" % link, o)
            self.assertTrue(os.path.isfile(os.path.join(self.a.json, "doc_x.json")))
        finally:
            os.rmdir(link)

    @unittest.skipUnless(sys.platform == "win32", "junctions are Windows-only")
    def test_junctions_are_removed_as_links_never_followed(self):
        gone, _ = self.deleted_item()
        elsewhere = os.path.join(self.tmp, "elsewhere")
        _write(os.path.join(elsewhere, "precious.txt"), "keep me")
        _write(os.path.join(elsewhere, "deep", "x.txt"), "keep me too")
        inner = self.a.t("file", gone, "sub", "jn")
        if not _junction(inner, elsewhere):
            self.skipTest("cannot create a junction here")
        # An old item whose whole backup folder is a junction.
        self.a.add("doc_j", "Jx", [], extra_files=False)
        self.a.run(self.a.target)
        jleaf = os.path.basename(model.parse(_read(self.a.t("json", "doc_j.json"))).local_folder_path)
        _rmtree(self.a.t("file", jleaf))
        self.assertTrue(_junction(self.a.t("file", jleaf), elsewhere))
        self.a.set_tags(self.a.t("json", "doc_j.json"), ["old"])
        before = _snapshot(elsewhere)
        rc, o = self.purge(self.a.target, "-n")
        self.assertIn("(link / junction: only the link is removed)", o)
        rc, o = self.purge(self.a.target, answer="y")
        self.assertEqual(rc, 0, o)
        self.assertFalse(os.path.lexists(self.a.t("file", gone)))
        self.assertFalse(os.path.lexists(self.a.t("file", jleaf)))
        self.assertEqual(_snapshot(elsewhere), before)
        self.assertIn("deleted      : 2 JSON, 2 card(s), 2 folder(s)", o)

    def test_remove_tree_symlink_to_file_outside(self):
        target = os.path.join(self.tmp, "outside.txt")
        _write(target, "keep")
        tree = os.path.join(self.tmp, "tree")
        _write(os.path.join(tree, "a.txt"), "a")
        try:
            os.symlink(target, os.path.join(tree, "lnk.txt"))
        except (OSError, NotImplementedError):
            self.skipTest("cannot create a symlink here")
        errors = []
        backupcmd._remove_tree(tree, errors)
        self.assertEqual(errors, [])
        self.assertFalse(os.path.lexists(tree))
        self.assertEqual(_read(target), "keep")

    def test_config_target_and_cli(self):
        gone, _ = self.deleted_item()
        cfg = os.path.join(self.tmp, "config.toml")
        _write(cfg, "[storage]\nfile = '%s'\nhtml = '%s'\njson = '%s'\n[backup]\ntarget = '%s'\n"
               % (self.a.f, self.a.html, self.a.json, self.a.target))
        env = dict(os.environ, HIB_CONFIG=cfg)
        hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")
        p = subprocess.run([sys.executable, hib, "backup", "--purge", "old", "-n"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                           input=b"y\n")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(os.path.isdir(self.a.t("file", gone)))
        p = subprocess.run([sys.executable, hib, "backup", "--purge", "old"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                           input=b"y\n")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertFalse(os.path.exists(self.a.t("file", gone)))
        self.assertFalse(os.path.exists(self.a.t("json", "doc_gone.json")))
        self.assertTrue(os.path.isfile(self.a.t("json", "doc_live.json")))


class TestBackupConfig(unittest.TestCase):
    def test_cli_dispatch_and_config_target(self):
        tmp = tempfile.mkdtemp(prefix="hibpy_backupcli_")
        try:
            a = Archive(tmp)
            a.add("doc_one", "One", [])
            cfg = os.path.join(tmp, "config.toml")
            target = os.path.join(tmp, "cfgtarget")
            _write(cfg, "[storage]\nfile = '%s'\nhtml = '%s'\njson = '%s'\n[backup]\ntarget = '%s'\n"
                   % (a.f, a.html, a.json, target))
            env = dict(os.environ, HIB_CONFIG=cfg)
            hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")
            p = subprocess.run([sys.executable, hib, "backup"], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertTrue(os.path.isfile(os.path.join(target, "json", "doc_one.json")))
            other = os.path.join(tmp, "clitarget")
            p = subprocess.run([sys.executable, hib, "backup", other, "-n"], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env)
            self.assertEqual(p.returncode, 0)
            self.assertIn(other, p.stdout.decode("utf-8", "replace"))
            self.assertFalse(os.path.exists(other))
            p = subprocess.run([sys.executable, hib, "config"], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env)
            self.assertIn("backup target: %s" % target, p.stdout.decode("utf-8", "replace"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
