import unittest

import model


class TestModel(unittest.TestCase):
    def test_version_normalization(self):
        # missing / null / bool / array / object -> "1" (legacy metadata files)
        self.assertEqual(model.parse('{"citekey":"k"}').version, "1")
        self.assertEqual(model.parse('{"citekey":"k","version":null}').version, "1")
        self.assertEqual(model.parse('{"citekey":"k","version":true}').version, "1")
        self.assertEqual(model.parse('{"citekey":"k","version":[1,2]}').version, "1")
        # string stays; int/float stringified
        self.assertEqual(model.parse('{"citekey":"k","version":"2.0a"}').version, "2.0a")
        self.assertEqual(model.parse('{"citekey":"k","version":2}').version, "2")
        self.assertEqual(model.parse('{"citekey":"k","version":1.5}').version, "1.5")
        # integral floats collapse to an int ("2.0"->"2", 1e3->"1000")
        self.assertEqual(model.parse('{"citekey":"k","version":2.0}').version, "2")
        self.assertEqual(model.parse('{"citekey":"k","version":1e3}').version, "1000")

    def test_fields_authors_tags_remote(self):
        text = (
            '{"citekey":"K","reference":"r","title":"t","shortTitle":"st",'
            '"itemType":"report","date":"01/01/2025","description":"d",'
            '"authors":[{"lastName":"Rigal","firstName":"Sylvain"}],'
            '"tags":["a","b"],"localFilePath":"f","localFolderPath":"fold",'
            '"htmlPath":"c.html","pdfLocalPath":"f.pdf","remotePath":"R:\\\\x"}'
        )
        e = model.parse(text)
        self.assertEqual(e.citekey, "K")
        self.assertEqual(e.authors, [("Rigal", "Sylvain")])
        self.assertEqual(e.tags, ["a", "b"])
        self.assertEqual(e.remote_path, "R:\\x")
        # remote_path is None (not "") when absent
        self.assertIsNone(model.parse('{"citekey":"k"}').remote_path)

    def test_non_object_rejected(self):
        with self.assertRaises(ValueError):
            model.parse("[1,2,3]")


if __name__ == "__main__":
    unittest.main()
