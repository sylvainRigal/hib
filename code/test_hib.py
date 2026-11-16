import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import hib
import selector as sel


class TestHib(unittest.TestCase):
    def test_parent_dir(self):
        self.assertEqual(hib.parent_dir("C:\\a\\b"), "C:\\a")
        self.assertEqual(hib.parent_dir("C:\\a\\b\\"), "C:\\a")   # one trailing sep
        self.assertEqual(hib.parent_dir("C:\\a\\\\"), "C:\\a")     # TWO trailing seps -> one stripped
        self.assertEqual(hib.parent_dir("C:\\file.txt"), "C:\\")   # drive root
        self.assertEqual(hib.parent_dir("file"), "")               # no separator
        self.assertEqual(hib.parent_dir("/srv/a//"), "/srv/a")

    def test_take_dry_run(self):
        self.assertEqual(hib.take_dry_run(["a", "-n", "b"]), (True, ["a", "b"]))
        self.assertEqual(hib.take_dry_run(["a"]), (False, ["a"]))
        self.assertEqual(hib.take_dry_run(["--dry-run", "x"]), (True, ["x"]))

    def test_add_source_reattaches_split_star(self):
        # PowerShell splits `"path"*` into ['path', '*']; the lone trailing '*' is
        # re-attached so the remote marker survives.
        self.assertEqual(hib._add_source("C:\\x\\f.docx", ["*"]), "C:\\x\\f.docx*")
        self.assertEqual(hib._add_source("C:\\x\\f.docx", []), "C:\\x\\f.docx")          # no extra
        self.assertEqual(hib._add_source("C:\\x\\f.docx*", []), "C:\\x\\f.docx*")        # star already in
        self.assertEqual(hib._add_source("C:\\x\\f.docx", ["other"]), "C:\\x\\f.docx")    # extra not '*'
        self.assertEqual(hib._add_source("*", []), "*")                                   # lone star, untouched

    def test_foreign_env(self):
        # A foreign PYTHONHOME/PYTHONPATH (either one) means the stdlib path may
        # need repair; unset/empty means nothing to do.
        self.assertTrue(hib._foreign_env("C:\\anaconda", None))
        self.assertTrue(hib._foreign_env(None, "C:\\x"))
        self.assertFalse(hib._foreign_env(None, None))
        self.assertFalse(hib._foreign_env("", ""))

    def test_repair_stdlib_path_inserts_real_lib(self):
        # With a foreign PYTHONPATH set, the running interpreter's own Lib is put at
        # index 1 (right after our own dir at index 0).
        saved_path, saved_pp = list(sys.path), os.environ.get("PYTHONPATH")
        try:
            os.environ["PYTHONPATH"] = "C:\\some\\foreign\\lib"
            hib._repair_stdlib_path()
            real_lib = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "Lib")
            if os.path.isdir(real_lib):                 # always true on a normal install
                self.assertEqual(sys.path[1], real_lib)
        finally:
            sys.path[:] = saved_path
            if saved_pp is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = saved_pp

    def test_repair_stdlib_path_noop_when_clean(self):
        # No foreign env -> sys.path is left untouched.
        saved_path, saved_pp, saved_ph = list(sys.path), os.environ.pop("PYTHONPATH", None), os.environ.pop("PYTHONHOME", None)
        try:
            hib._repair_stdlib_path()
            self.assertEqual(sys.path, saved_path)
        finally:
            sys.path[:] = saved_path
            if saved_pp is not None:
                os.environ["PYTHONPATH"] = saved_pp
            if saved_ph is not None:
                os.environ["PYTHONHOME"] = saved_ph

    def test_path_with_status(self):
        # An existing dir is printed bare; a missing one is flagged.
        here = os.path.dirname(os.path.abspath(__file__))
        self.assertEqual(hib._path_with_status(here), here)
        missing = os.path.join(here, "no_such_dir_xyz")
        self.assertTrue(hib._path_with_status(missing).endswith("[MISSING]"))
        self.assertEqual(hib._path_with_status(""), "(not set)")
        self.assertEqual(hib._path_with_status(None), "(not set)")

    def test_parse_selector(self):
        out = lambda m: None
        # A bare value matches a citekey OR a reference -> kind "any".
        self.assertEqual(sel.parse_selector(["ReportX"], out), ("any", "ReportX"))
        self.assertEqual(sel.parse_selector(["-html", "foo"], out), ("html", "foo"))
        self.assertEqual(sel.parse_selector(["-ref", "r"], out), ("reference", "r"))
        self.assertEqual(sel.parse_selector(["-citekey", "k"], out), ("citekey", "k"))
        self.assertEqual(sel.parse_selector(["-ctk", "k"], out), ("citekey", "k"))   # short form
        self.assertIsNone(sel.parse_selector(["-ctk"], out))                         # needs a value
        self.assertIsNone(sel.parse_selector([], out))
        self.assertIsNone(sel.parse_selector(["-bad", "x"], out))
        self.assertIsNone(sel.parse_selector(["-html"], out))   # flag without value


class TestOpenFolderDispatch(unittest.TestCase):
    """`hib openfolder <citekey>` -- the spelled-out alias of `hib oe`."""

    def test_aliases_map_to_the_explorer_commands(self):
        self.assertEqual(hib.OPEN_CMDS["openfolder"], hib.OPEN_CMDS["oe"])
        self.assertEqual(hib.OPEN_CMDS["openremotefolder"], hib.OPEN_CMDS["oer"])
        self.assertEqual(hib.OPEN_CMDS["openfolder"], "local_folder")

    def _dispatch(self, argv):
        with mock.patch.object(hib.config_mod, "load", return_value=(object(), "cfgdir")), \
             mock.patch.object(hib, "cmd_open", return_value=0) as opened, \
             mock.patch.object(hib.addcmd, "run_add", return_value=0) as added:
            code = hib.main(argv)
        return code, opened, added

    def test_openfolder_opens_the_local_folder(self):
        code, opened, added = self._dispatch(["openfolder", "ReportX"])
        self.assertEqual(code, 0)
        opened.assert_called_once_with(mock.ANY, ["ReportX"], "local_folder")
        added.assert_not_called()          # NOT taken for a source file to add

    def test_openremotefolder_opens_the_remote_folder(self):
        _, opened, added = self._dispatch(["openremotefolder", "ReportX", "-n"])
        opened.assert_called_once_with(mock.ANY, ["ReportX", "-n"], "remote_folder")
        added.assert_not_called()

    def test_an_unknown_command_still_falls_through_to_add(self):
        _, opened, added = self._dispatch(["openfolders", "ReportX"])   # typo
        opened.assert_not_called()
        added.assert_called_once()


class TestFrozenConversionChild(unittest.TestCase):
    """hib.exe re-invokes itself to convert; that flag must be handled before the
    config is loaded and before the "unknown command -> add this file" fallthrough."""

    def test_child_flag_is_dispatched_first(self):
        import pdfgen
        with mock.patch.object(pdfgen, "convert_child", return_value=0) as child, \
             mock.patch.object(hib.config_mod, "load") as load, \
             mock.patch.object(hib.addcmd, "run_add") as added:
            code = hib.main([pdfgen.CHILD_FLAG, "in.docx", "out.pdf"])
        self.assertEqual(code, 0)
        child.assert_called_once_with(["in.docx", "out.pdf"])
        load.assert_not_called()           # no config needed to convert
        added.assert_not_called()          # never mistaken for a source file


@unittest.skipUnless(sys.platform == "win32", "the open commands are Windows-specific")
class TestOpenFolderIntegration(unittest.TestCase):
    """Real CLI run against a real archive, in dry-run so nothing is launched."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_openfolder_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for sub in ("f", "html", "json"):
            os.makedirs(os.path.join(self.tmp, sub))
        cfg = os.path.join(self.tmp, "config.toml")
        with open(cfg, "w", encoding="utf-8", newline="") as f:
            f.write("[storage]\n")
            for key, sub in (("file", "f"), ("html", "html"), ("json", "json")):
                f.write("%s = '%s'\n" % (key, os.path.join(self.tmp, sub)))
        self.env = dict(os.environ, HIB_CONFIG=cfg)
        self.hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")
        src = os.path.join(self.tmp, "src.txt")
        with open(src, "w", newline="") as f:
            f.write("hi\n")
        answers = ["", "report", "Doc", "", "1", "Doe:Jane", "03/06/2026", "", "", ""]
        p = self._run(["add", src], "\n".join(answers) + "\n")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.citekey = os.listdir(os.path.join(self.tmp, "json"))[0][:-5]

    def _run(self, args, stdin=""):
        p = subprocess.run([sys.executable, self.hib] + args, input=stdin.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env)
        p.stdout = p.stdout.decode("utf-8", "replace")
        return p

    def test_openfolder_targets_the_entrys_storage_folder(self):
        p = self._run(["openfolder", self.citekey, "-n"])
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("would open: " + os.path.join(self.tmp, "f"), p.stdout)

    def test_openfolder_is_the_same_target_as_oe(self):
        self.assertEqual(self._run(["openfolder", self.citekey, "-n"]).stdout,
                         self._run(["oe", self.citekey, "-n"]).stdout)

    def test_openfolder_reports_an_unknown_citekey(self):
        p = self._run(["openfolder", "NoSuchKeyXYZ"])
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("would open", p.stdout)


if __name__ == "__main__":
    unittest.main()
