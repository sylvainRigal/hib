import unittest

import dates
import citekey
import reference
import entry
import naming


class TestDates(unittest.TestCase):
    def test_format_dmy(self):
        self.assertEqual(dates.format_dmy(2026, 6, 3), "03/06/2026")
        self.assertEqual(dates.format_dmy(2026, 12, 25), "25/12/2026")
        self.assertEqual(dates.format_dmy(2000, 1, 1), "01/01/2000")

    def test_compact_dmy(self):
        self.assertEqual(dates.compact_dmy("03/06/2026"), "20260603")
        self.assertEqual(dates.compact_dmy("25/12/2000"), "20001225")
        self.assertEqual(dates.compact_dmy("3/6/2026"), "20260603")
        self.assertEqual(dates.compact_dmy("2026"), "2026")          # not DD/MM/YYYY -> digits

    def test_compact_ymd(self):
        self.assertEqual(dates.compact_ymd(2026, 6, 5), "20260605")
        self.assertEqual(dates.compact_ymd(2000, 1, 1), "20000101")

    def test_short_dmy(self):
        self.assertEqual(dates.short_dmy("04/06/2026"), "040626")
        self.assertEqual(dates.short_dmy("25/12/2000"), "251200")
        self.assertEqual(dates.short_dmy("3/6/2008"), "030608")
        self.assertEqual(dates.short_dmy("2026"), "2026")

    def test_malformed_components_fall_back_to_digits(self):
        # A component that is not a valid u16 (after trimming spaces) -> the whole
        # string keeps only its ASCII digits (digits-only fallback), NOT a modulo-
        # wrapped value. Each case below pins the exact expected output.
        self.assertEqual(dates.compact_dmy("01/01/70000"), "010170000")  # u16 overflow
        self.assertEqual(dates.compact_dmy("-1/01/2026"), "1012026")     # negative sign
        self.assertEqual(dates.compact_dmy("٣/06/2026"), "062026")  # Arabic-Indic 3
        self.assertEqual(dates.compact_dmy("\t3/6/2026"), "362026")      # tab is not " "
        self.assertEqual(dates.short_dmy("01/01/70000"), "010170000")
        self.assertEqual(dates.short_dmy("-1/01/2026"), "1012026")
        # The valid common path is unchanged.
        self.assertEqual(dates.compact_dmy("3/6/2026"), "20260603")


class TestCitekey(unittest.TestCase):
    def test_build(self):
        a = [("Rigal", "Sylvain"), ("Doe", "Jane")]
        self.assertEqual(citekey.build("report", a, "20260603"), "ReportRigalDoe20260603")
        five = [("a", ""), ("b", ""), ("c", ""), ("d", ""), ("e", "")]
        self.assertEqual(citekey.build("script", five, "20260101"), "ScriptABCD20260101")
        self.assertEqual(citekey.build("report", [], "20260101"), "Report20260101")
        self.assertEqual(citekey.build("a/b:c", [], "20260101"), "Abc20260101")
        self.assertEqual(citekey.build("journalArticle", [], "20260101"), "JournalArticle20260101")
        self.assertEqual(citekey.build("repère", [], "20260101"), "Repere20260101")
        self.assertEqual(citekey.build("", [], ""), "entry")
        self.assertEqual(citekey.build("con", [], ""), "Con_")

    def test_clean_folds_a_hand_typed_citekey(self):
        # `hib update -ctk` sends the user's value through here: it becomes the
        # JSON's file name, so it is folded exactly like build's parts.
        self.assertEqual(citekey.clean("ReportRigal20260603"), "ReportRigal20260603")
        self.assertEqual(citekey.clean("rapport final 2026"), "Rapportfinal2026")
        self.assertEqual(citekey.clean("a/b:c"), "Abc")
        self.assertEqual(citekey.clean("repère"), "Repere")
        self.assertEqual(citekey.clean("keep.this_and-that"), "Keep.this_and-that")
        self.assertEqual(citekey.clean("nul"), "Nul_")      # reserved device name
        self.assertEqual(citekey.clean("@@@"), "")          # nothing usable left
        self.assertEqual(citekey.clean(""), "")


class TestReference(unittest.TestCase):
    def test_default(self):
        # <itemType>_<shortTitle>_<author3>_<yyyymmdd>; author3 = first 3 cite-letters
        # of the first author's last name (capitalized, accent-folded).
        self.assertEqual(
            reference.default_reference("report", "Etude_Speciale_v2", [("Rigal", "Sylvain")], "20260604"),
            "report_Etude_Speciale_v2_Rig_20260604")
        self.assertEqual(
            reference.default_reference("DE", "Visit", [("SRi", "")], "20260610"),
            "DE_Visit_SRi_20260610")
        # accents fold to ASCII like the citekey ("Éric" -> "Eric" -> "Eri").
        self.assertEqual(
            reference.default_reference("document", "X", [("Éric", "")], "20260101"),
            "document_X_Eri_20260101")
        # no authors -> empty author slot (two underscores).
        self.assertEqual(
            reference.default_reference("note", "X", [], "20260101"), "note_X__20260101")


class TestEntry(unittest.TestCase):
    def test_parse_authors(self):
        a = entry.parse_author_list(" Rigal:Sylvain , Doe:Jane ,OnlyLast, ")
        self.assertEqual(a, [("Rigal", "Sylvain"), ("Doe", "Jane"), ("OnlyLast", "")])
        self.assertEqual(entry.parse_author_list("   "), [])

    def test_parse_tags(self):
        self.assertEqual(entry.parse_tag_list(" cli , , filemanager ,"), ["cli", "filemanager"])

    def test_round_trip(self):
        a = [("Rigal", "Sylvain"), ("Doe", "")]
        self.assertEqual(entry.authors_to_input(a), "Rigal:Sylvain, Doe")
        self.assertEqual(entry.authors_to_input([]), "")
        self.assertEqual(entry.tags_to_input(["a", "b", "c"]), "a, b, c")


class TestNaming(unittest.TestCase):
    def test_names(self):
        self.assertEqual(naming.card_name("doc"), "doc.html")
        self.assertEqual(naming.numbered_name("doc", 3), "doc_3.html")

    def test_first_free(self):
        self.assertEqual(naming.first_free_numbered_name("rapport", lambda n: False), "rapport_1.html")
        taken = {"doc_1.html", "doc_2.html"}
        self.assertEqual(naming.first_free_numbered_name("doc", lambda n: n in taken), "doc_3.html")

    def test_json_base_is_the_reference(self):
        # The metadata file is named after the reference, hib's fixed identifier.
        self.assertEqual(naming.json_base("report_Etude_Rig_20260603", "ReportRigal20260603"),
                         "report_Etude_Rig_20260603")
        # An author-less default reference has a real '__': it must survive, so the
        # name still reads back as the reference character for character.
        self.assertEqual(naming.json_base("report_Doc__20260603", "K"), "report_Doc__20260603")
        # Only what a file name cannot hold is folded away.
        self.assertEqual(naming.json_base("a/b:c d", "K"), "abc_d")   # dropped, space -> _
        self.assertEqual(naming.json_base("repère_20260603", "K"), "repere_20260603")

    def test_json_base_falls_back_to_the_citekey(self):
        # An entry with no reference at all (hand-edited JSON) keeps hib's old name.
        self.assertEqual(naming.json_base("", "ReportRigal20260603"), "ReportRigal20260603")
        self.assertEqual(naming.json_base("   ", "ReportRigal20260603"), "ReportRigal20260603")
        self.assertEqual(naming.json_base(None, None), "entry")


if __name__ == "__main__":
    unittest.main()
