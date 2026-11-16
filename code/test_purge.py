import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import purgecmd


class TestPurgeHelpers(unittest.TestCase):
    def test_contains_name_fold_ascii(self):
        self.assertTrue(purgecmd._contains_name_fold(["Foo.html", "Bar.html"], "foo.html"))
        self.assertTrue(purgecmd._contains_name_fold(["a20260609ABCD0000"], "a20260609abcd0000"))
        self.assertFalse(purgecmd._contains_name_fold(["Foo.html"], "Baz.html"))
        self.assertFalse(purgecmd._contains_name_fold([], "x"))

    def test_touches_dir(self):
        self.assertTrue(purgecmd._touches_dir("C:\\f\\trash", "C:\\f\\trash"))   # equal
        self.assertTrue(purgecmd._touches_dir("C:\\f\\sub", "C:\\f"))            # candidate under target
        self.assertTrue(purgecmd._touches_dir("C:\\f", "C:\\f\\sub"))            # target under candidate
        self.assertFalse(purgecmd._touches_dir("C:\\f\\a", "C:\\f\\b"))          # siblings

    def test_is_reparse_plain_entries(self):
        d = tempfile.mkdtemp(prefix="hibpy_rep_")
        try:
            f = os.path.join(d, "f.txt")
            open(f, "w").close()
            sub = os.path.join(d, "sub")
            os.makedirs(sub)
            self.assertFalse(purgecmd._is_reparse(f))            # regular file
            self.assertFalse(purgecmd._is_reparse(sub))          # plain dir
            self.assertTrue(purgecmd._is_reparse(os.path.join(d, "missing")))   # unstattable -> skip
        finally:
            shutil.rmtree(d, ignore_errors=True)


def _write_cfg(tmp):
    cfg = os.path.join(tmp, "config.toml")
    with open(cfg, "w", encoding="utf-8", newline="") as f:
        f.write("[storage]\n")
        for k in ("file", "html", "json", "trash"):
            sub = {"file": "f", "html": "html", "json": "json", "trash": "trash"}[k]
            f.write("%s = '%s'\n" % (k, os.path.join(tmp, sub)))
    return cfg


@unittest.skipUnless(sys.platform == "win32", "purge flow is Windows-specific")
class TestPurgeIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_purge_")
        for sub in ("f", "html", "json", "trash"):
            os.makedirs(os.path.join(self.tmp, sub))
        self.cfg = _write_cfg(self.tmp)
        self.env = dict(os.environ, HIB_CONFIG=self.cfg)
        self.hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")
        src = os.path.join(self.tmp, "src.txt")
        with open(src, "w", newline="") as f:
            f.write("hi\n")
        # Two live entries with distinct citekeys/cards.
        self._add("Alpha", "Doe:Jane", "03/06/2026", src)
        self._add("Beta", "Smith:Bob", "04/06/2026", src)
        # An orphan card and an orphan storage folder.
        with open(os.path.join(self.tmp, "html", "Zombie.html"), "w", newline="") as f:
            f.write("<html>z</html>\n")
        os.makedirs(os.path.join(self.tmp, "f", "zombiefolder"))
        with open(os.path.join(self.tmp, "f", "zombiefolder", "x.txt"), "w", newline="") as f:
            f.write("o\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add(self, title, author, date, src):
        add_in = "\n".join(["", "report", title, "", "1", author, date, "", "", ""]) + "\n"
        p = subprocess.run([sys.executable, self.hib, "add", src], input=add_in.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))

    def _purge(self, stdin=b""):
        return subprocess.run([sys.executable, self.hib, "purge"] + (["-n"] if stdin is None else []),
                              input=(b"" if stdin is None else stdin),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)

    def test_dry_run_lists_orphans_and_moves_nothing(self):
        p = self._purge(stdin=None)   # -n
        self.assertEqual(p.returncode, 0)
        o = p.stdout.decode("utf-8", "replace")
        self.assertIn("Zombie.html", o)
        self.assertIn("zombiefolder", o)
        self.assertIn("dry run", o)
        self.assertEqual(os.listdir(os.path.join(self.tmp, "trash")), [])   # nothing moved
        self.assertIn("Zombie.html", os.listdir(os.path.join(self.tmp, "html")))

    def test_confirm_moves_orphans_keeps_live(self):
        p = self._purge(stdin=b"y\n")
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        # Live entries remain; orphans gone from the source dirs.
        self.assertEqual(sorted(os.listdir(os.path.join(self.tmp, "html"))), ["Alpha.html", "Beta.html"])
        self.assertNotIn("zombiefolder", os.listdir(os.path.join(self.tmp, "f")))
        # Orphans moved into a single purge_<date> session folder.
        sessions = os.listdir(os.path.join(self.tmp, "trash"))
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0].startswith("purge_"))
        moved = sorted(os.listdir(os.path.join(self.tmp, "trash", sessions[0])))
        self.assertEqual(moved, ["Zombie.html", "zombiefolder"])

    def test_json_subdir_does_not_abort(self):
        # A directory named *.json in the json dir must be SKIPPED (gated on the
        # entry kind), not read as an unreadable file that aborts the whole purge.
        os.makedirs(os.path.join(self.tmp, "json", "weird.json"))
        p = self._purge(stdin=None)   # -n
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        o = p.stdout.decode("utf-8", "replace")
        self.assertNotIn("could not be read/parsed", o)
        self.assertIn("Zombie.html", o)        # the real orphan is still detected

    def test_orphan_junction_is_skipped(self):
        # A junction (reparse point) in the file dir is classified as a symlink
        # and skipped; it must NOT be treated as an orphan folder and moved.
        target = os.path.join(self.tmp, "linktarget")
        os.makedirs(target)
        link = os.path.join(self.tmp, "f", "linkdir")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode != 0:
            self.skipTest("could not create a junction")
        p = self._purge(stdin=None)   # -n
        self.assertEqual(p.returncode, 0)
        self.assertNotIn("linkdir", p.stdout.decode("utf-8", "replace"))

    def test_unreadable_json_aborts(self):
        with open(os.path.join(self.tmp, "json", "bad.json"), "w", newline="") as f:
            f.write("this is not json{")
        p = self._purge(stdin=b"y\n")
        self.assertEqual(p.returncode, 1)
        self.assertIn("could not be read/parsed", p.stdout.decode("utf-8", "replace"))
        # Aborted before any move: orphan still present, trash empty.
        self.assertIn("Zombie.html", os.listdir(os.path.join(self.tmp, "html")))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "trash")), [])


if __name__ == "__main__":
    unittest.main()
