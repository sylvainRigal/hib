import unittest

import html as html_mod
import cardparse
from entry import Entry


class TestCardParse(unittest.TestCase):
    def test_roundtrip_from_a_rendered_card(self):
        e = Entry(title="Quantum <Report> & Co", item_type="DE",
                  authors=[("Rigal", "Sylvain"), ("Doe", "Jane")],
                  date="03/06/2026", tags=["physics", "a & b"],
                  description='He said "hi" & left\nsecond line',
                  version="2", short_title="Quantum_Report",
                  reference="DE_Quantum_Rig_20260603", citekey="DERigal20260603",
                  local_path="C:\\f\\a1\\x.docx", remote_path="T:\\src\\x.docx")
        f = cardparse.parse_card(html_mod.render_entry(e))
        self.assertEqual(f["title"], "Quantum <Report> & Co")          # h2, unescaped
        self.assertEqual(f["item_type"], "DE")
        self.assertEqual(f["reference"], "DE_Quantum_Rig_20260603")
        self.assertEqual(f["version"], "2")
        self.assertEqual(f["short_title"], "Quantum_Report")
        self.assertEqual(f["date"], "03/06/2026")
        self.assertEqual(f["description"], 'He said "hi" & left\nsecond line')
        self.assertEqual(f["tags"], ["physics", "a & b"])
        self.assertEqual(f["authors"], [("Rigal", "Sylvain"), ("Doe", "Jane")])
        self.assertEqual(f["remote_path"], "T:\\src\\x.docx")

    def test_authors_reverse_last_word_is_last_name(self):
        self.assertEqual(cardparse.parse_authors_display("SRi"), [("SRi", "")])
        self.assertEqual(cardparse.parse_authors_display("Sylvain Rigal, Jane Doe"),
                         [("Rigal", "Sylvain"), ("Doe", "Jane")])
        self.assertEqual(cardparse.parse_authors_display(""), [])

    def test_unescape_order(self):
        # text that contained '&lt;' renders as '&amp;lt;' and must come back whole.
        self.assertEqual(cardparse._unescape("&amp;lt;"), "&lt;")
        self.assertEqual(cardparse._unescape("a &amp; b &lt;x&gt; &quot;q&quot;"),
                         'a & b <x> "q"')

    def test_missing_markup_is_absent_not_wiped(self):
        f = cardparse.parse_card("<html><body>not a hib card</body></html>")
        self.assertNotIn("title", f)
        self.assertNotIn("reference", f)
        self.assertNotIn("description", f)
        # tags / remote are the two 'now none' states (always present).
        self.assertEqual(f["tags"], [])
        self.assertIsNone(f["remote_path"])

    def test_no_remote_block_yields_none(self):
        e = Entry(title="T", item_type="document", authors=[], date="03/06/2026",
                  tags=[], description="", local_path="C:\\f\\a1\\x.docx")  # no remote
        f = cardparse.parse_card(html_mod.render_entry(e))
        self.assertIsNone(f["remote_path"])


class TestReferenceMarkupBothForms(unittest.TestCase):
    """The Copy Reference button put the reference inside a span, so the plain
    "<strong>Reference:</strong> ... </p>" pattern would now swallow the button
    markup. Both card shapes must still yield the bare reference."""

    def test_card_without_the_button_still_parses(self):
        # A card written by an older hib, before the button existed.
        old = ("<h2>T</h2>\n"
               "  <p><strong>Reference:</strong> DE_Old_Card_20260603</p>\n")
        f = cardparse.parse_card(old)
        self.assertEqual(f["reference"], "DE_Old_Card_20260603")

    def test_button_markup_is_never_read_as_the_value(self):
        e = Entry(title="T", item_type="document", authors=[], date="03/06/2026",
                  tags=[], description="", reference="DE_New_Card_20260603")
        f = cardparse.parse_card(html_mod.render_entry(e))
        self.assertEqual(f["reference"], "DE_New_Card_20260603")

    def test_escaped_reference_round_trips_through_the_span(self):
        e = Entry(title="T", item_type="document", authors=[], date="03/06/2026",
                  tags=[], description="", reference='A"B&C<D>')
        f = cardparse.parse_card(html_mod.render_entry(e))
        self.assertEqual(f["reference"], 'A"B&C<D>')


if __name__ == "__main__":
    unittest.main()
