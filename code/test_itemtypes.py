import os
import shutil
import tempfile
import unittest

import item_types as it


class TestParse(unittest.TestCase):
    def test_trims_skips_blanks_comments(self):
        t = it.parse("# header\n\nartwork\n  report  \r\nbook\n# trailing\n")
        self.assertEqual(t.types, ["artwork", "report", "book"])

    def test_dedup_case_insensitive_first_wins(self):
        t = it.parse("report\nReport\nREPORT\nbook\n")
        self.assertEqual(t.types, ["report", "book"])

    def test_empty_whitespace_comments(self):
        self.assertEqual(it.parse("").types, [])
        self.assertEqual(it.parse("   \n\t\n").types, [])
        self.assertEqual(it.parse("# only a comment\n").types, [])


class TestDefault(unittest.TestCase):
    def test_default_parses_to_40(self):
        t = it.parse(it.DEFAULT_ITEM_TYPES_TEXT)
        self.assertEqual(len(t.types), 40)
        self.assertEqual(t.types[0], "artwork")
        self.assertEqual(t.types[-1], "DE")
        for name in ("computerProgram", "report", "script", "journalArticle", "DE"):
            self.assertIsNotNone(t.find_exact(name))
        for name in ("software", "attachment", "note"):   # display/child types excluded
            self.assertIsNone(t.find_exact(name))


class TestFindResolve(unittest.TestCase):
    def setUp(self):
        self.t = it.parse("report\njournalArticle\n")

    def test_find_exact_fold(self):
        self.assertEqual(self.t.find_exact("report"), "report")
        self.assertIsNone(self.t.find_exact("Report"))
        self.assertEqual(self.t.find_fold("REPORT"), "report")
        self.assertEqual(self.t.find_fold("journalarticle"), "journalArticle")
        self.assertIsNone(self.t.find_fold("widget"))

    def test_resolve(self):
        self.assertEqual(it.resolve(self.t, "report"), ("exact", "report"))
        self.assertEqual(it.resolve(self.t, "Report"), ("case_fold", "report"))
        self.assertEqual(it.resolve(self.t, "widget"), ("unknown", "widget"))


class TestChooseItemType(unittest.TestCase):
    def _ask(self, answers):
        seq = list(answers)

        def ask(label, default):
            v = seq.pop(0)
            return default if v is None else v   # None = accept the offered default
        return ask

    _silent = staticmethod(lambda s: None)

    def test_accept_default_is_verbatim(self):
        # Even a default that is NOT in the table is returned untouched (rule 0),
        # so a .bib-supplied type survives.
        t = it.parse("report\n")
        self.assertEqual(it.choose_item_type(t, self._ask([None]), self._silent, "techreport"),
                         "techreport")

    def test_exact_match_silent(self):
        t = it.parse("report\nbook\n")
        self.assertEqual(it.choose_item_type(t, self._ask(["book"]), self._silent, "document"), "book")

    def test_number_selects_by_index(self):
        t = it.parse("report\nbook\n")
        self.assertEqual(it.choose_item_type(t, self._ask(["2"]), self._silent, "document"), "book")

    def test_case_fold_confirmed_canonicalizes(self):
        t = it.parse("report\n")
        self.assertEqual(it.choose_item_type(t, self._ask(["Report", "y"]), self._silent, "document"),
                         "report")

    def test_unknown_confirmed_kept_verbatim(self):
        t = it.parse("report\n")
        self.assertEqual(it.choose_item_type(t, self._ask(["widget", "y"]), self._silent, "document"),
                         "widget")

    def test_declined_reprompts(self):
        t = it.parse("report\n")
        # widget -> decline -> report (exact)
        self.assertEqual(it.choose_item_type(t, self._ask(["widget", "n", "report"]),
                                             self._silent, "document"), "report")

    def test_question_lists_then_pick(self):
        t = it.parse("report\nbook\n")
        out = []
        self.assertEqual(it.choose_item_type(t, self._ask(["?", "1"]), out.append, "document"), "report")
        self.assertTrue(any("Known item types" in m for m in out))


class TestLoadItemTypes(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hibpy_it_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_bootstrap_when_missing(self):
        t = it.load_item_types(self.d, lambda s: None)
        self.assertEqual(len(t.types), 40)
        with open(os.path.join(self.d, "itemTypes.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), it.DEFAULT_ITEM_TYPES_TEXT)   # exact bootstrap content

    def test_reads_existing(self):
        with open(os.path.join(self.d, "itemTypes.txt"), "w", encoding="utf-8", newline="") as f:
            f.write("report\nbook\n")
        self.assertEqual(it.load_item_types(self.d, lambda s: None).types, ["report", "book"])

    def test_empty_file_falls_back_to_default(self):
        with open(os.path.join(self.d, "itemTypes.txt"), "w", encoding="utf-8", newline="") as f:
            f.write("# only comments\n")
        self.assertEqual(len(it.load_item_types(self.d, lambda s: None).types), 40)


if __name__ == "__main__":
    unittest.main()
