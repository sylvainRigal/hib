import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import trash as trash_mod
from config import Config


class TestTrashHelpers(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hibpy_trash_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_trash_root_explicit_vs_default(self):
        c = Config("C:\\f\\", "C:\\h", "C:\\j", trash_path="C:\\t\\")
        self.assertEqual(trash_mod.trash_root(c), "C:\\t")             # trimmed
        c2 = Config("C:\\f\\", "C:\\h", "C:\\j", trash_path=None)
        self.assertEqual(trash_mod.trash_root(c2), os.path.join("C:\\f", "trash"))
        # A path that trims to empty (only separators) -> default
        # (only \\/ are trimmed -- whitespace would be kept verbatim).
        c3 = Config("C:\\f", "C:\\h", "C:\\j", trash_path="\\")
        self.assertEqual(trash_mod.trash_root(c3), os.path.join("C:\\f", "trash"))

    def test_free_trash_dest_numbers_on_collision(self):
        self.assertEqual(trash_mod.free_trash_dest(self.d, "a1"), os.path.join(self.d, "a1"))
        os.makedirs(os.path.join(self.d, "a1"))
        self.assertEqual(trash_mod.free_trash_dest(self.d, "a1"), os.path.join(self.d, "a1_1"))

    def test_free_name_in_dir_keeps_extension(self):
        self.assertEqual(trash_mod.free_name_in_dir(self.d, "R.html"), os.path.join(self.d, "R.html"))
        open(os.path.join(self.d, "R.html"), "w").close()
        self.assertEqual(trash_mod.free_name_in_dir(self.d, "R.html"), os.path.join(self.d, "R_1.html"))
        # No extension -> '_N' appended with no dot.
        open(os.path.join(self.d, "NOEXT"), "w").close()
        self.assertEqual(trash_mod.free_name_in_dir(self.d, "NOEXT"), os.path.join(self.d, "NOEXT_1"))

    def test_move_dir_to_refuses_existing_dest(self):
        # An existing dest must NOT nest the source inside it (the rename must fail);
        # warn + return False + leave the source in place.
        src = os.path.join(self.d, "src")
        os.makedirs(src)
        open(os.path.join(src, "f.txt"), "w").close()
        dest = os.path.join(self.d, "dest")
        os.makedirs(dest)
        msgs = []
        self.assertFalse(trash_mod.move_dir_to(src, dest, msgs.append))
        self.assertTrue(os.path.exists(src))                              # left in place
        self.assertFalse(os.path.exists(os.path.join(dest, "src")))       # NOT nested
        self.assertTrue(any("could not move folder" in m for m in msgs))

    def test_move_dir_to_nul_path_is_not_fatal(self):
        msgs = []
        self.assertFalse(trash_mod.move_dir_to("a\x00b", os.path.join(self.d, "x"), msgs.append))
        self.assertTrue(any("could not move folder" in m for m in msgs))

    def test_move_file_into_nul_path_is_not_fatal(self):
        msgs = []
        trash_mod.move_file_into("a\x00b.txt", self.d, "card", msgs.append)   # must not raise
        self.assertTrue(any("could not move" in m for m in msgs))


@unittest.skipUnless(sys.platform == "win32", "delete flow is Windows-specific")
class TestDeleteIntegration(unittest.TestCase):
    def test_add_then_delete_moves_everything_to_trash(self):
        tmp = tempfile.mkdtemp(prefix="hibpy_delint_")
        try:
            for sub in ("f", "html", "json", "trash"):
                os.makedirs(os.path.join(tmp, sub))
            cfg = os.path.join(tmp, "config.toml")
            with open(cfg, "w", encoding="utf-8", newline="") as f:
                f.write("[storage]\n")
                for k in ("file", "html", "json", "trash"):
                    sub = {"file": "f", "html": "html", "json": "json", "trash": "trash"}[k]
                    f.write("%s = '%s'\n" % (k, os.path.join(tmp, sub)))
            src = os.path.join(tmp, "src.txt")
            with open(src, "w", newline="") as f:
                f.write("hi\n")
            env = dict(os.environ, HIB_CONFIG=cfg)
            hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")

            add_in = "\n".join(["", "report", "Doc", "", "1", "Doe:Jane",
                                "03/06/2026", "t1", "", ""]) + "\n"
            p = subprocess.run([sys.executable, hib, "add", src], input=add_in.encode("utf-8"),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
            citekey = os.listdir(os.path.join(tmp, "json"))[0][:-5]

            p = subprocess.run([sys.executable, hib, "delete", citekey], input=b"y\n",
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))

            # Source dirs emptied; everything moved under one trash subfolder.
            self.assertEqual(os.listdir(os.path.join(tmp, "html")), [])
            self.assertEqual(os.listdir(os.path.join(tmp, "json")), [])
            self.assertEqual(os.listdir(os.path.join(tmp, "f")), [])
            subs = os.listdir(os.path.join(tmp, "trash"))
            self.assertEqual(len(subs), 1)
            moved = sorted(os.listdir(os.path.join(tmp, "trash", subs[0])))
            self.assertEqual(moved, sorted(["Doc.html", citekey + ".json", "src.txt"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_delete_abort_keeps_everything(self):
        tmp = tempfile.mkdtemp(prefix="hibpy_delabort_")
        try:
            for sub in ("f", "html", "json", "trash"):
                os.makedirs(os.path.join(tmp, sub))
            cfg = os.path.join(tmp, "config.toml")
            with open(cfg, "w", encoding="utf-8", newline="") as f:
                f.write("[storage]\n")
                for k in ("file", "html", "json", "trash"):
                    sub = {"file": "f", "html": "html", "json": "json", "trash": "trash"}[k]
                    f.write("%s = '%s'\n" % (k, os.path.join(tmp, sub)))
            src = os.path.join(tmp, "src.txt")
            with open(src, "w", newline="") as f:
                f.write("hi\n")
            env = dict(os.environ, HIB_CONFIG=cfg)
            hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")
            add_in = "\n".join(["", "report", "Doc", "", "1", "", "03/06/2026", "", "", ""]) + "\n"
            subprocess.run([sys.executable, hib, "add", src], input=add_in.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            citekey = os.listdir(os.path.join(tmp, "json"))[0][:-5]
            # Default-NO confirmation: an empty answer (EOF) must abort, nothing moved.
            p = subprocess.run([sys.executable, hib, "delete", citekey], input=b"\n",
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            self.assertEqual(p.returncode, 0)
            self.assertEqual(os.listdir(os.path.join(tmp, "html")), ["Doc.html"])
            self.assertEqual(os.listdir(os.path.join(tmp, "json")), [citekey + ".json"])
            self.assertEqual(os.listdir(os.path.join(tmp, "trash")), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
