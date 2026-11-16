import json
import unittest

import metadata
import model
from entry import Entry


class TestMetadata(unittest.TestCase):
    def _m(self, **over):
        e = Entry(
            title=over.pop("title", 'Etude "x" & y'),
            item_type=over.pop("item_type", "report"),
            authors=over.pop("authors", [("Rigal", "Sylvain")]),
            date=over.pop("date", "03/06/2026"),
            tags=over.pop("tags", ["a", "b"]),
            description=over.pop("description", "d"),
            version=over.pop("version", "2"),
            short_title=over.pop("short_title", "Etude_x_y"),
            reference=over.pop("reference", "RE_Etude_x_y_030626_v2"),
        )
        return metadata.Metadata(
            citekey=over.pop("citekey", "ReportRigal20260603"),
            entry=e,
            local_file_path=over.pop("local_file_path", "C:\\f\\a1\\Etude.docx"),
            local_folder_path=over.pop("local_folder_path", "C:\\f\\a1"),
            html_path=over.pop("html_path", "C:\\html\\Etude.html"),
            pdf_local_path=over.pop("pdf_local_path", "C:\\f\\a1\\Etude.pdf"),
            remote_path=over.pop("remote_path", None),
        )

    def test_escaping_and_fields(self):
        j = metadata.render(self._m())
        self.assertIn('"localFilePath": "C:\\\\f\\\\a1\\\\Etude.docx"', j)
        self.assertIn('\\"x\\"', j)
        self.assertIn('"citekey": "ReportRigal20260603"', j)
        self.assertIn('"authors": [{"lastName": "Rigal", "firstName": "Sylvain"}]', j)
        self.assertIn('"reference": "RE_Etude_x_y_030626_v2"', j)
        self.assertIn('"shortTitle": "Etude_x_y"', j)
        self.assertIn('"version": 2', j)
        self.assertNotIn("remotePath", j)
        json.loads(j)  # must be well-formed

    def test_remote_path_present(self):
        j = metadata.render(self._m(remote_path="T:\\orig\\x.pdf"))
        self.assertIn('"remotePath": "T:\\\\orig\\\\x.pdf"', j)
        json.loads(j)

    def test_non_integer_version_quoted(self):
        j = metadata.render(self._m(version="1.2"))
        self.assertIn('"version": "1.2"', j)
        json.loads(j)

    def test_round_trip_through_model(self):
        # render -> model.parse must reproduce every field (writer/reader parity).
        m = self._m(remote_path="T:\\orig\\x.pdf", tags=["cli", "qa"],
                    authors=[("Rigal", "Sylvain"), ("Doe", "")])
        e2 = model.parse(metadata.render(m))
        self.assertEqual(e2.citekey, "ReportRigal20260603")
        self.assertEqual(e2.reference, "RE_Etude_x_y_030626_v2")
        self.assertEqual(e2.title, 'Etude "x" & y')
        self.assertEqual(e2.short_title, "Etude_x_y")
        self.assertEqual(e2.item_type, "report")
        self.assertEqual(e2.version, "2")
        self.assertEqual(e2.date, "03/06/2026")
        self.assertEqual(e2.tags, ["cli", "qa"])
        self.assertEqual(e2.authors, [("Rigal", "Sylvain"), ("Doe", "")])
        self.assertEqual(e2.local_file_path, "C:\\f\\a1\\Etude.docx")
        self.assertEqual(e2.remote_path, "T:\\orig\\x.pdf")


if __name__ == "__main__":
    unittest.main()
