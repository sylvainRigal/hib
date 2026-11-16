import unittest

import hibtoml


class TestTomlParse(unittest.TestCase):
    def test_sections_literal_basic_comments(self):
        text = (
            "# a comment\n"
            "root_key = 'before any section'\n"
            "\n"
            "[storage]\n"
            "file  = 'C:\\Users\\me\\hib\\f'   # trailing comment ignored\n"
            'html  = "C:\\\\Users\\\\me\\\\hib\\\\html"\n'
            "trash = ''\n"
            "\n"
            "[pdf]\n"
            "cmd = '\"C:\\Program Files\\x\\soffice\" --outdir {outdir} {input}'\n"
        )
        t = hibtoml.parse(text)
        self.assertEqual(t.get_value("", "root_key"), "before any section")
        self.assertEqual(t.get_value("storage", "file"), "C:\\Users\\me\\hib\\f")
        # basic string: \\ -> \  (matches the literal-string form)
        self.assertEqual(t.get_value("storage", "html"), "C:\\Users\\me\\hib\\html")
        self.assertEqual(t.get_value("storage", "trash"), "")
        self.assertEqual(
            t.get_value("pdf", "cmd"),
            '"C:\\Program Files\\x\\soffice" --outdir {outdir} {input}',
        )
        self.assertIsNone(t.get_value("storage", "absent"))
        self.assertIsNone(t.get_value("nosuch", "file"))

    def test_basic_escapes_and_errors(self):
        t = hibtoml.parse('a = "line1\\nline2\\ttab\\"q"\n')
        self.assertEqual(t.get_value("", "a"), 'line1\nline2\ttab"q')
        with self.assertRaises(hibtoml.TomlError):
            hibtoml.parse("a = 'oops\n")
        with self.assertRaises(hibtoml.TomlError):
            hibtoml.parse('a = "oops\n')
        with self.assertRaises(hibtoml.TomlError):
            hibtoml.parse("novalue\n")

    def test_hash_in_string_vs_bare(self):
        t = hibtoml.parse("a = 'has # hash'\nb = bare value # comment\n")
        self.assertEqual(t.get_value("", "a"), "has # hash")
        self.assertEqual(t.get_value("", "b"), "bare value")

    def test_render_round_trips(self):
        storage = {
            "file": "C:\\hib\\f",
            "html": "C:\\hib\\html",
            "json": "C:\\hib\\json",
            "trash": "C:\\hib\\trash",
        }
        pdf = {"powershell": "", "cmd": '"C:\\x\\soffice" --outdir {outdir} {input}'}
        text = hibtoml.render(storage, pdf)
        back = hibtoml.parse(text)
        for k, v in storage.items():
            self.assertEqual(back.get_value("storage", k), v)
        self.assertEqual(back.get_value("pdf", "powershell"), "")
        self.assertEqual(back.get_value("pdf", "cmd"), pdf["cmd"])


if __name__ == "__main__":
    unittest.main()
