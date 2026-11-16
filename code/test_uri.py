import unittest

import uri


class TestUri(unittest.TestCase):
    def test_file_uri_byte_percent_encoding(self):
        # space -> %20, '&' -> %26, 'é' (UTF-8 C3 A9) -> %C3%A9; '/' and ':' kept
        self.assertEqual(uri.file_uri("C:\\a b\\R&T\\é.docx"),
                         "file:///C:/a%20b/R%26T/%C3%A9.docx")

    def test_is_office_ext(self):
        for ext in (".docx", ".DOCX", ".xls", ".pptx"):
            self.assertTrue(uri.is_office_ext(ext))
        for ext in (".pdf", ".txt", ""):
            self.assertFalse(uri.is_office_ext(ext))

    def test_open_href(self):
        self.assertEqual(uri.open_href("C:\\x\\y.docx"), "ms-word:ofe|u|file:///C:/x/y.docx")
        self.assertEqual(uri.open_href("C:\\x\\Y.XLSX"), "ms-excel:ofe|u|file:///C:/x/Y.XLSX")
        self.assertEqual(uri.open_href("C:\\x\\y.pdf"), "file:///C:/x/y.pdf")


if __name__ == "__main__":
    unittest.main()
