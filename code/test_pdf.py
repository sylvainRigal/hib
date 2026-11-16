import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import locate


class TestStoredPathIsSafe(unittest.TestCase):
    def test_safe_and_unsafe_paths(self):
        root = "C:\\f"
        self.assertTrue(locate.stored_path_is_safe(root, "C:\\f\\a2026abcd\\etude.docx"))
        self.assertTrue(locate.stored_path_is_safe(root, "C:/f/a1/x.pdf"))           # mixed seps
        self.assertFalse(locate.stored_path_is_safe(root, "C:\\other\\x"))            # outside root
        self.assertFalse(locate.stored_path_is_safe(root, "C:\\foo\\x"))             # sibling prefix, not descendant
        self.assertFalse(locate.stored_path_is_safe(root, "C:\\f"))                  # equal to root
        self.assertFalse(locate.stored_path_is_safe(root, "C:\\f\\a&b\\x"))          # shell metachar
        self.assertFalse(locate.stored_path_is_safe(root, "C:\\f\\a b\\x"))          # space
        self.assertFalse(locate.stored_path_is_safe("", "C:\\f\\x"))                 # empty root
        # str.lower() would fold U+212A KELVIN SIGN -> 'k' and pass; ASCII-fold rejects.
        self.assertFalse(locate.stored_path_is_safe(root, "C:\\f\\a1\\" + chr(0x212A) + ".pdf"))


@unittest.skipUnless(sys.platform == "win32", "pdf flow is Windows-specific")
class TestPdfIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_pdf_")
        for sub in ("f", "html", "json"):
            os.makedirs(os.path.join(self.tmp, sub))
        cfg = os.path.join(self.tmp, "config.toml")
        with open(cfg, "w", encoding="utf-8", newline="") as f:
            f.write("[storage]\n")
            for k in ("file", "html", "json"):
                f.write("%s = '%s'\n" % (k, os.path.join(self.tmp, k if k != "file" else "f")))
        # LOCALAPPDATA -> tmp so the fallback converter chain
        # (code/config/config.toml -> %LOCALAPPDATA%\hib\config.toml) finds
        # nothing: this test asserts that `add` produced NO PDF.
        self.env = dict(os.environ, HIB_CONFIG=cfg, LOCALAPPDATA=self.tmp)
        self.hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")
        src = os.path.join(self.tmp, "src.docx")
        with open(src, "w", newline="") as f:
            f.write("fake docx\n")
        add_in = "\n".join(["", "report", "Doc", "", "1", "Doe:Jane", "03/06/2026", "", "", ""]) + "\n"
        p = subprocess.run([sys.executable, self.hib, "add", src], input=add_in.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.citekey = os.listdir(os.path.join(self.tmp, "json"))[0][:-5]
        self.json_path = os.path.join(self.tmp, "json", self.citekey + ".json")
        self.card_path = os.path.join(self.tmp, "html", "Doc.html")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _meta(self):
        with open(self.json_path, encoding="utf-8") as f:
            return json.load(f)

    def _card(self):
        with open(self.card_path, encoding="utf-8") as f:
            return f.read()

    def _run_pdf(self):
        return subprocess.run([sys.executable, self.hib, "pdf", self.citekey], input=b"\n",
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)

    def test_pdf_refreshes_card_when_pdf_present(self):
        # No converter, so add produced no PDF button. Drop the PDF, then `pdf`
        # refreshes the card so the button appears.
        with open(self.card_path, encoding="utf-8") as f:
            self.assertNotIn('class="pdf-btn" href', f.read())
        pdf_path = self._meta()["pdfLocalPath"]
        with open(pdf_path, "w", newline="") as f:
            f.write("%PDF-1.4\n")
        p = self._run_pdf()
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        with open(self.card_path, encoding="utf-8") as f:
            self.assertIn('class="pdf-btn" href', f.read())

    def test_pdf_refuses_tampered_path(self):
        # A localFolderPath outside the storage root must be refused (converter guard).
        meta = self._meta()
        meta["localFolderPath"] = "C:\\Windows\\System32"
        with open(self.json_path, "w", encoding="utf-8", newline="") as f:
            json.dump(meta, f)
        before = self._card()
        p = self._run_pdf()
        self.assertEqual(p.returncode, 1)
        self.assertIn("refusing to run the converter", p.stdout.decode("utf-8", "replace"))
        self.assertEqual(self._card(), before)   # card untouched

    def test_pdf_missing_stored_copy(self):
        # Remove the stored copy -> clean error, no crash.
        os.remove(self._meta()["localFilePath"])
        p = self._run_pdf()
        self.assertEqual(p.returncode, 1)
        self.assertIn("stored copy not found", p.stdout.decode("utf-8", "replace"))


@unittest.skipUnless(sys.platform == "win32", "pdf flow is Windows-specific")
class TestAttachExistingPdf(unittest.TestCase):
    """`hib pdf <ctk> <file.pdf>`: attach a PDF that already exists. It is COPIED
    into the entry's storage folder under the name hib reserves for it, the JSON
    gets a pdfLocalPath if it had none, and the card gains its Local PDF button.
    The source file is left where it is."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_attach_")
        for sub in ("f", "html", "json"):
            os.makedirs(os.path.join(self.tmp, sub))
        cfg = os.path.join(self.tmp, "config.toml")
        with open(cfg, "w", encoding="utf-8", newline="") as f:
            f.write("[storage]\n")
            for k in ("file", "html", "json"):
                f.write("%s = '%s'\n" % (k, os.path.join(self.tmp, k if k != "file" else "f")))
        # LOCALAPPDATA -> tmp so no fallback converter is found: `add` produces no
        # PDF, which is exactly the situation this command exists for.
        self.env = dict(os.environ, HIB_CONFIG=cfg, LOCALAPPDATA=self.tmp)
        self.hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")
        src = os.path.join(self.tmp, "src.docx")
        with open(src, "w", newline="") as f:
            f.write("fake docx\n")
        add_in = "\n".join(["", "report", "Doc", "", "1", "Doe:Jane", "03/06/2026", "", "", ""]) + "\n"
        p = subprocess.run([sys.executable, self.hib, "add", src], input=add_in.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.json_name = os.listdir(os.path.join(self.tmp, "json"))[0]
        self.json_path = os.path.join(self.tmp, "json", self.json_name)
        self.selector = self.json_name[:-5]          # the reference names the file
        self.card_path = os.path.join(self.tmp, "html", "Doc.html")
        self.scan = os.path.join(self.tmp, "scan.pdf")
        self._write(self.scan, "%PDF-1.4 scanned\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path, text):
        with open(path, "w", newline="") as f:
            f.write(text)

    def _read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _meta(self):
        with open(self.json_path, encoding="utf-8") as f:
            return json.load(f)

    def _attach(self, source, stdin=b"\n"):
        return subprocess.run([sys.executable, self.hib, "pdf", self.selector, source],
                              input=stdin, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=self.env)

    def test_attaches_copies_and_adds_the_button(self):
        self.assertNotIn('class="pdf-btn" href', self._read(self.card_path))
        p = self._attach(self.scan)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        dest = self._meta()["pdfLocalPath"]
        self.assertEqual(self._read(dest), "%PDF-1.4 scanned\n")     # copied
        self.assertTrue(os.path.isfile(self.scan))                  # source kept
        self.assertIn('class="pdf-btn" href', self._read(self.card_path))

    def test_the_copy_lands_on_the_name_add_reserved(self):
        before = self._meta()["pdfLocalPath"]
        p = self._attach(self.scan)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertEqual(self._meta()["pdfLocalPath"], before)   # JSON untouched
        self.assertTrue(os.path.isfile(before))
        self.assertEqual(os.path.dirname(before), self._meta()["localFolderPath"])

    def test_a_json_without_a_pdf_path_gets_one_recorded(self):
        meta = self._meta()
        meta["pdfLocalPath"] = ""
        with open(self.json_path, "w", encoding="utf-8", newline="") as f:
            json.dump(meta, f)
        p = self._attach(self.scan)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        # Derived from the stored copy's stem, in the entry's own folder.
        expected = os.path.join(meta["localFolderPath"], "src.pdf")
        self.assertEqual(self._meta()["pdfLocalPath"], expected)
        self.assertTrue(os.path.isfile(expected))
        self.assertIn("pdfLocalPath recorded", p.stdout.decode("utf-8", "replace"))

    def test_replacing_an_attached_pdf_asks_first(self):
        self.assertEqual(self._attach(self.scan).returncode, 0)
        dest = self._meta()["pdfLocalPath"]
        self._write(self.scan, "%PDF-1.4 second\n")
        p = self._attach(self.scan, b"n\n")                      # declined
        self.assertEqual(p.returncode, 0)
        self.assertIn("Replace it?", p.stdout.decode("utf-8", "replace"))
        self.assertEqual(self._read(dest), "%PDF-1.4 scanned\n")
        p = self._attach(self.scan, b"y\n")                      # accepted
        self.assertEqual(p.returncode, 0)
        self.assertEqual(self._read(dest), "%PDF-1.4 second\n")

    def test_refuses_a_source_that_is_not_a_pdf(self):
        other = os.path.join(self.tmp, "notes.txt")
        self._write(other, "hi\n")
        p = self._attach(other)
        self.assertEqual(p.returncode, 1)
        self.assertIn("is not a .pdf", p.stdout.decode("utf-8", "replace"))
        self.assertNotIn('class="pdf-btn" href', self._read(self.card_path))

    def test_refuses_a_missing_source(self):
        p = self._attach(os.path.join(self.tmp, "nope.pdf"))
        self.assertEqual(p.returncode, 1)
        self.assertIn("no such file", p.stdout.decode("utf-8", "replace"))

    def test_refuses_a_tampered_folder_path(self):
        meta = self._meta()
        meta["localFolderPath"] = "C:\\Windows\\System32"
        meta["pdfLocalPath"] = "C:\\Windows\\System32\\hib.pdf"
        with open(self.json_path, "w", encoding="utf-8", newline="") as f:
            json.dump(meta, f)
        p = self._attach(self.scan)
        self.assertEqual(p.returncode, 1)
        self.assertIn("refusing to write a PDF there", p.stdout.decode("utf-8", "replace"))
        self.assertFalse(os.path.exists("C:\\Windows\\System32\\hib.pdf"))

    def test_attaching_the_entrys_own_pdf_is_a_no_op_refresh(self):
        dest = self._meta()["pdfLocalPath"]
        self._write(dest, "%PDF-1.4 already there\n")
        p = self._attach(dest)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertIn("already IS the entry's PDF", p.stdout.decode("utf-8", "replace"))
        self.assertEqual(self._read(dest), "%PDF-1.4 already there\n")
        self.assertIn('class="pdf-btn" href', self._read(self.card_path))

    def test_a_quoted_path_is_accepted(self):
        p = self._attach('"%s"' % self.scan)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertTrue(os.path.isfile(self._meta()["pdfLocalPath"]))

    def test_the_selector_flag_form_still_takes_a_path(self):
        citekey = self._meta()["citekey"]
        p = subprocess.run([sys.executable, self.hib, "pdf", "-citekey", citekey, self.scan],
                           input=b"\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertTrue(os.path.isfile(self._meta()["pdfLocalPath"]))
        self.assertIn('class="pdf-btn" href', self._read(self.card_path))


if __name__ == "__main__":
    unittest.main()
