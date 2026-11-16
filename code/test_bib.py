import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import bib


class TestBibParse(unittest.TestCase):
    def test_type_key_fields_case_insensitive(self):
        text = (
            "@Article{rigal2026,\n"
            "  title = {" + chr(0x00C9) + "tude},\n"   # E-acute, to exercise non-ASCII
            "  author = {Rigal, Sylvain and Doe, Jane},\n"
            "  year = {2026},\n"
            "  keywords = {pile, essai},\n"
            "}\n"
        )
        es = bib.parse(text)
        self.assertEqual(len(es), 1)
        self.assertEqual(es[0].entry_type, "article")
        self.assertEqual(es[0].key, "rigal2026")
        self.assertEqual(es[0].get("TITLE"), chr(0x00C9) + "tude")   # case-insensitive
        self.assertEqual(es[0].get("year"), "2026")
        self.assertEqual(es[0].get("keywords"), "pile, essai")
        self.assertIsNone(es[0].get("missing"))

    def test_quoted_bare_multiline_inner_braces(self):
        text = (
            '@techreport{k,\n'
            '  title = "A {NASA} Report",\n'
            '  number = 42,\n'
            '  note = {first line\n'
            '          second   line},\n'
            '}\n'
        )
        e = bib.parse(text)[0]
        self.assertEqual(e.entry_type, "techreport")
        self.assertEqual(e.get("title"), "A NASA Report")        # quotes + inner braces gone
        self.assertEqual(e.get("number"), "42")                  # bare number
        self.assertEqual(e.get("note"), "first line second line")  # whitespace collapsed

    def test_several_entries_skip_comment_string(self):
        text = (
            "@string{pub = {ACME}}\n"
            "@comment{ this is ignored }\n"
            "@book{a, title = {First}}\n"
            "@misc{b, title = {Second}}\n"
        )
        es = bib.parse(text)
        self.assertEqual(len(es), 2)
        self.assertEqual(es[0].key, "a")
        self.assertEqual(es[0].get("title"), "First")
        self.assertEqual(es[1].key, "b")
        self.assertEqual(es[1].get("title"), "Second")

    def test_empty_and_garbage(self):
        self.assertEqual(bib.parse(""), [])
        self.assertEqual(bib.parse("not a bib file at all"), [])


class TestBibAuthors(unittest.TestCase):
    def test_authors_to_hib(self):
        self.assertEqual(bib.authors_to_hib("Doe, Jane and Smith, John"), "Doe:Jane, Smith:John")
        self.assertEqual(bib.authors_to_hib("Jane Doe and John Smith"), "Doe:Jane, Smith:John")
        self.assertEqual(bib.authors_to_hib("von Neumann, John"), "von Neumann:John")
        self.assertEqual(bib.authors_to_hib("Einstein"), "Einstein")


class TestBibDate(unittest.TestCase):
    def _e(self, **fields):
        return bib.BibEntry("misc", "k", [(k, v) for k, v in fields.items()])

    def test_to_hib_date(self):
        self.assertEqual(bib.to_hib_date(self._e(date="2026-06-04")), "04/06/2026")
        self.assertEqual(bib.to_hib_date(self._e(year="2026")), "01/01/2026")
        self.assertEqual(bib.to_hib_date(self._e(year="2025", month="mar", day="9")), "09/03/2025")
        self.assertIsNone(bib.to_hib_date(self._e()))
        # an out-of-range month name/number and day clamp to 01.
        self.assertEqual(bib.to_hib_date(self._e(date="2026-13-40")), "01/01/2026")
        # a year that overflows u16 -> no year -> None.
        self.assertIsNone(bib.to_hib_date(self._e(year="70000")))

    def test_parseint_sign_and_underscore(self):
        # Integer parsing accepts a leading '+' and INTERIOR '_' separators
        # (even doubled), but rejects leading/trailing '_' and '-'.
        self.assertEqual(bib.to_hib_date(self._e(date="+2026-06-04")), "04/06/2026")
        self.assertEqual(bib.to_hib_date(self._e(year="2_026")), "01/01/2026")
        self.assertEqual(bib.to_hib_date(self._e(year="2026", month="1_2")), "01/12/2026")
        self.assertEqual(bib.to_hib_date(self._e(year="2026", day="1__2")), "12/01/2026")
        # rejects: leading/trailing '_' and a minus -> no value parsed.
        self.assertIsNone(bib.to_hib_date(self._e(year="_2026")))
        self.assertIsNone(bib.to_hib_date(self._e(year="2026_")))
        self.assertIsNone(bib.to_hib_date(self._e(year="-3")))
        self.assertEqual(bib.to_hib_date(self._e(year="2026", month="+1_")), "01/01/2026")  # month rejected


class TestLoadBibDefaults(unittest.TestCase):
    def _defaults_for(self, bib_text):
        import addcmd
        d = tempfile.mkdtemp(prefix="hibpy_bibd_")
        try:
            p = os.path.join(d, "x.bib")
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bib_text)
            asked = [p]
            return addcmd._load_bib_defaults(lambda label, default: asked.pop(0) if asked else default,
                                             lambda s: None)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_empty_abstract_does_not_fall_through_to_note(self):
        # A present-but-empty abstract wins over note (present beats absent), so the
        # Description default is empty -- NOT the note text.
        self.assertIsNone(self._defaults_for("@article{k, abstract = {}, note = {NOTE}}\n")["description"])

    def test_absent_abstract_uses_note(self):
        self.assertEqual(self._defaults_for("@article{k, note = {NOTE}}\n")["description"], "NOTE")

    def test_abstract_present_wins(self):
        self.assertEqual(self._defaults_for("@article{k, abstract = {ABS}, note = {NOTE}}\n")["description"], "ABS")


BIB = """\
@techreport{key2026,
  title = {Quantum Report},
  shorttitle = {Quantum_Rep},
  author = {Rigal, Sylvain and Doe, Jane},
  date = {2026-06-03},
  keywords = {physics; quantum},
  abstract = {A study of quantum things},
  version = {2},
}
"""


@unittest.skipUnless(sys.platform == "win32", "add flow is Windows-specific")
class TestBibImportIntegration(unittest.TestCase):
    def test_add_prefills_from_bib(self):
        tmp = tempfile.mkdtemp(prefix="hibpy_bib_")
        try:
            for sub in ("f", "html", "json"):
                os.makedirs(os.path.join(tmp, sub))
            cfg = os.path.join(tmp, "config.toml")
            with open(cfg, "w", encoding="utf-8", newline="") as f:
                f.write("[storage]\n")
                for k in ("file", "html", "json"):
                    f.write("%s = '%s'\n" % (k, os.path.join(tmp, k if k != "file" else "f")))
            bib_path = os.path.join(tmp, "meta.bib")
            with open(bib_path, "w", encoding="utf-8", newline="") as f:
                f.write(BIB)
            src = os.path.join(tmp, "src.txt")
            with open(src, "w", newline="") as f:
                f.write("hi\n")
            env = dict(os.environ, HIB_CONFIG=cfg)
            hib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hib.py")

            # .bib path, then accept every pre-filled default (9 blank lines).
            stdin = (bib_path + "\n" + "\n" * 9).encode("utf-8")
            p = subprocess.run([sys.executable, hib, "add", src], input=stdin,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))

            self.assertEqual(os.listdir(os.path.join(tmp, "html")), ["Quantum_Report.html"])
            metas = os.listdir(os.path.join(tmp, "json"))
            # Named after the REFERENCE (<type>_<shortTitle>_<author3>_<date>),
            # itself built from the .bib fields; the citekey is inside the file.
            self.assertEqual(metas, ["techreport_Quantum_Rep_Rig_20260603.json"])
            with open(os.path.join(tmp, "json", metas[0]), encoding="utf-8") as f:
                m = json.load(f)
            self.assertEqual(m["title"], "Quantum Report")
            self.assertEqual(m["shortTitle"], "Quantum_Rep")
            self.assertEqual(m["itemType"], "techreport")
            self.assertEqual(m["version"], 2)
            self.assertEqual(m["date"], "03/06/2026")
            self.assertEqual(m["description"], "A study of quantum things")
            self.assertEqual([(a["lastName"], a["firstName"]) for a in m["authors"]],
                             [("Rigal", "Sylvain"), ("Doe", "Jane")])
            self.assertEqual(m["tags"], ["physics", "quantum"])   # keywords ';' -> ',' -> list
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
