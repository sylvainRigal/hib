import unittest

import sanitize as s


class TestSanitize(unittest.TestCase):
    def test_sanitize_base(self):
        self.assertEqual(s.sanitize_base("R&T (final)"), "RT_final")
        self.assertEqual(s.sanitize_base("Ingénieurs d'Essai — Programme (v2)"),
                         "Ingenieurs_dEssai_Programme_v2")
        self.assertEqual(s.sanitize_base("DE2026-016 - Vieillissement"),
                         "DE2026-016_-_Vieillissement")
        self.assertEqual(s.sanitize_base("   &&&   "), "file")

    def test_basename_stripext_ext(self):
        self.assertEqual(s.base_name("T:\\a b\\c\\remotefile.docx"), "remotefile.docx")
        self.assertEqual(s.strip_extension("remotefile.docx"), "remotefile")
        self.assertEqual(s.strip_extension("noext"), "noext")
        self.assertEqual(s.extension("a.b.docx"), ".docx")
        self.assertEqual(s.extension("noext"), "")

    def test_sanitize_filename(self):
        self.assertEqual(s.sanitize_filename("T:\\x y\\Étude Spéciale (v2).docx"),
                         "Etude_Speciale_v2.docx")
        self.assertEqual(s.sanitize_filename("plain"), "plain")

    def test_parse_source_path(self):
        cases = [
            ("T:\\a\\b.docx", "T:\\a\\b.docx", False),
            ("  T:\\a\\b.docx*  ", "T:\\a\\b.docx", True),
            ('"T:\\a b\\c.docx"', "T:\\a b\\c.docx", False),
            ('"T:\\a b\\c.docx"*', "T:\\a b\\c.docx", True),
            ('"T:\\a b\\c.docx*"', "T:\\a b\\c.docx", True),
            ('"T:\\a b\\c.docx" *', "T:\\a b\\c.docx", True),
        ]
        for raw, path, keep in cases:
            self.assertEqual(s.parse_source_path(raw), (path, keep), raw)

    def test_parse_short_title(self):
        cases = [
            ("Mon Nom", "Mon Nom", False),
            ("Mon Nom*", "Mon Nom", True),
            ("Mon Nom *", "Mon Nom", True),
            ("  Spécial & co*  ", "Spécial & co", True),
            ("A*B", "A*B", False),
            ("*", "", True),
            ("", "", False),
        ]
        for raw, value, flag in cases:
            self.assertEqual(s.parse_short_title(raw), (value, flag), raw)

    def test_cite_word(self):
        self.assertEqual(s.cite_word("rigal"), "Rigal")
        self.assertEqual(s.cite_word("Doe"), "Doe")
        self.assertEqual(s.cite_word("von Neumann"), "VonNeumann")
        self.assertEqual(s.cite_word("O'Brien"), "OBrien")
        self.assertEqual(s.cite_word("étude"), "Etude")
        self.assertEqual(s.cite_word("  &  "), "")


if __name__ == "__main__":
    unittest.main()
