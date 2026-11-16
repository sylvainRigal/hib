import unittest

import locate


class TestLocate(unittest.TestCase):
    def test_contains_fold(self):
        self.assertTrue(locate.contains_fold("ReportRigal20250101", "rigal"))
        self.assertTrue(locate.contains_fold("ReportRigal20250101", "20250101"))
        self.assertFalse(locate.contains_fold("ReportRigal20250101", "doe"))
        self.assertFalse(locate.contains_fold("abc", ""))

    def test_clean_source_path(self):
        self.assertEqual(locate.clean_source_path('"C:\\h\\Foo.html"'), "C:\\h\\Foo.html")
        self.assertEqual(locate.clean_source_path("C:\\h\\Foo.html*"), "C:\\h\\Foo.html")
        self.assertEqual(locate.clean_source_path('"C:\\h\\Foo.html"*'), "C:\\h\\Foo.html")
        self.assertEqual(locate.clean_source_path('"C:\\h\\Foo.html*"'), "C:\\h\\Foo.html")
        self.assertEqual(locate.clean_source_path("C:\\h\\Foo.html"), "C:\\h\\Foo.html")

    def test_html_match_quoted_and_starred(self):
        stored = "C:\\Rigal\\html\\Foo.html"
        # quoted and trailing-star args must both match as 'full' (match kind)
        self.assertEqual(locate.html_match(stored, '"C:\\Rigal\\html\\Foo.html"'), "full")
        self.assertEqual(locate.html_match(stored, "C:\\Rigal\\html\\Foo.html*"), "full")
        self.assertEqual(locate.html_match(stored, "C:\\Rigal\\html\\Foo.html"), "full")
        # basename-only match
        self.assertEqual(locate.html_match(stored, "Foo.html"), "base")
        self.assertEqual(locate.html_match(stored, '"Foo.html"'), "base")
        self.assertEqual(locate.html_match(stored, "Other.html"), "none")

    def test_is_within(self):
        self.assertTrue(locate.is_within("C:\\store\\f", "C:\\store\\f\\ab12"))
        self.assertFalse(locate.is_within("C:\\store\\f", "C:\\store\\f"))
        self.assertFalse(locate.is_within("C:\\store\\f", "C:\\store\\f\\..\\..\\Windows"))

    def test_normalize_path_ascii_fold_only(self):
        # ASCII uppercase folds; non-ASCII is left as-is (ASCII-only
        # lowercasing). Python's Unicode str.lower() would fold these.
        e_upper = chr(0x00C9)   # E-acute (uppercase)
        e_lower = chr(0x00E9)   # e-acute (lowercase)
        kelvin = chr(0x212A)    # KELVIN SIGN (str.lower() -> 'k')
        self.assertEqual(locate.normalize_path("C:\\ABC\\x"), "c:/abc/x")
        self.assertEqual(locate.normalize_path("A" + e_upper), "a" + e_upper)   # not folded
        self.assertEqual(locate.normalize_path(kelvin), kelvin)                  # not -> 'k'
        # upper vs lower E-acute stay distinct (no Unicode fold).
        self.assertNotEqual(locate.normalize_path("caf" + e_upper),
                            locate.normalize_path("caf" + e_lower))


if __name__ == "__main__":
    unittest.main()
