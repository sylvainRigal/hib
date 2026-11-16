"""End-to-end `add` integration test: spawn hib.py as a subprocess, pipe raw
UTF-8 answers (with accents) on stdin, and assert the written card + JSON contain
the accent as UTF-8 (C3 A9), NOT the cp1252 mojibake (C3 83 C2 A9). Guards the
stdin/stdout UTF-8 fix. Skipped on non-Windows (os.startfile/paths are Windows)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HIB = os.path.join(HERE, "hib.py")


@unittest.skipUnless(sys.platform == "win32", "add flow is Windows-specific")
class TestAddFlowUtf8(unittest.TestCase):
    def test_piped_utf8_answers_are_not_mangled(self):
        tmp = tempfile.mkdtemp(prefix="hibpy_add_")
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
            with open(src, "w", encoding="utf-8", newline="") as f:
                f.write("hello\n")

            # Python add prompt order (no .bib): type, title, short(blank), version,
            # authors, date, tags, description, reference(blank). Title + author +
            # tag carry accents to exercise UTF-8 stdin decoding.
            answers = "\n".join([
                "",                     # .bib path -> skip the import
                "report",
                "Café Résumé",          # title with é
                "",                                     # short -> default slug
                "1",
                "Muñoz:José",                # author with ñ / é
                "03/06/2026",
                "physique, énergie",              # tag with é
                "",                                     # description
                "",                                     # reference -> default
            ]) + "\n"

            env = dict(os.environ, HIB_CONFIG=cfg)
            proc = subprocess.run(
                [sys.executable, HIB, "add", src],
                input=answers.encode("utf-8"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))

            cards = os.listdir(os.path.join(tmp, "html"))
            metas = os.listdir(os.path.join(tmp, "json"))
            self.assertEqual(len(cards), 1, "exactly one card written")
            self.assertEqual(len(metas), 1, "exactly one json written")

            for sub, names in (("html", cards), ("json", metas)):
                with open(os.path.join(tmp, sub, names[0]), "rb") as f:
                    data = f.read()
                # é present as UTF-8, and NOT as the cp1252 double-encoding mojibake.
                self.assertIn(b"\xc3\xa9", data, "%s missing UTF-8 é" % sub)
                self.assertNotIn(b"\xc3\x83\xc2\xa9", data, "%s has cp1252 mojibake" % sub)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
