import unittest

import html
from entry import Entry


class TestRenderEntry(unittest.TestCase):
    def test_includes_and_escapes_every_field(self):
        e = Entry(
            title="Quantum <Report>",
            item_type="report",
            authors=[("Rigal", "Sylvain"), ("Doe", "Jane")],
            date="03/06/2026",
            tags=["physics", "quantum"],
            description='He said "hi" & left',
            version="2",
            short_title="Quantum_Report",
            reference="RE_Quantum_Report_030626_v2",
            citekey="ReportRigal20260603",
        )
        h = html.render_entry(e)
        self.assertIn("<title>Quantum &lt;Report&gt;</title>", h)
        self.assertIn("<strong>Type:</strong> report", h)
        self.assertIn('<span id="referenceValue">RE_Quantum_Report_030626_v2</span>', h)
        self.assertIn('<span id="citekeyValue">ReportRigal20260603</span>', h)
        self.assertIn("<strong>Version:</strong> 2", h)
        self.assertIn("<strong>Short Title:</strong> Quantum_Report", h)
        self.assertIn("Sylvain Rigal", h)
        self.assertIn("Jane Doe", h)
        self.assertIn('<span class="tag">physics</span>', h)
        self.assertIn('<span class="tag">quantum</span>', h)
        self.assertIn("03/06/2026", h)
        self.assertIn('content="He said &quot;hi&quot; &amp; left"', h)

    def test_single_part_author_names(self):
        e = Entry(title="T", item_type="document",
                  authors=[("Rigal", ""), ("", "Sylvain")],
                  date="03/06/2026", tags=[], description="")
        h = html.render_entry(e)
        self.assertIn('<meta name="author" content="Rigal, Sylvain">', h)
        self.assertIn("<strong>Authors:</strong> Rigal, Sylvain</p>", h)

    def test_empty_tag_and_author_lists(self):
        e = Entry(title="Empty", item_type="document", authors=[],
                  date="03/06/2026", tags=[], description="")
        h = html.render_entry(e)
        self.assertIn('<meta name="keywords" content="">', h)
        self.assertIn('<meta name="author" content="">', h)
        self.assertNotIn('<span class="tag">', h)

    def test_local_path_block(self):
        e = Entry(title="T", item_type="document", authors=[],
                  date="03/06/2026", tags=[], description="",
                  local_path="C:\\f\\a1b2\\Etude_Speciale_v2.docx")
        h = html.render_entry(e)
        self.assertIn('id="localPath">C:\\f\\a1b2\\Etude_Speciale_v2.docx</div>', h)
        self.assertIn('href="ms-word:ofe|u|file:///C:/f/a1b2/Etude_Speciale_v2.docx"', h)
        self.assertIn('<a class="folder-btn" href="file:///C:/f/a1b2/">&#128193; Open File Location</a>', h)
        self.assertIn("function copyPath(", h)
        self.assertIn("function copyFolderPath(", h)

    def test_local_path_omitted_when_null(self):
        e = Entry(title="T", item_type="document", authors=[],
                  date="03/06/2026", tags=[], description="")
        h = html.render_entry(e)
        self.assertNotIn("Local Path:", h)
        self.assertNotIn("copyFolderPath(", h)
        self.assertIn("function copyPath(", h)      # the citekey/reference buttons need it

    def test_remote_section_and_pdf(self):
        e = Entry(title="T", item_type="document", authors=[],
                  date="03/06/2026", tags=[], description="",
                  local_path="C:\\f\\a1\\copy.docx",
                  remote_path="T:\\orig\\source.docx",
                  pdf_path="C:\\f\\a1\\copy.pdf")
        h = html.render_entry(e)
        self.assertIn('<div class="remote-section">', h)
        self.assertIn('id="remotePath">T:\\orig\\source.docx</div>', h)
        self.assertIn("ms-word:ofe|u|file:///T:/orig/source.docx", h)
        self.assertIn('<a class="folder-btn" href="file:///T:/orig/">&#128193; Open Remote Location</a>', h)
        self.assertIn("onclick=\"copyPath('remotePath', this, 'Copy Remote Path')\"", h)
        self.assertIn("function copyFolderPath(", h)
        self.assertIn('<a class="pdf-btn" href="file:///C:/f/a1/copy.pdf">', h)

    def test_empty_string_paths_still_render(self):
        # The card blocks are gated on their optionals being non-null, so an
        # empty-string path (only reachable via a hand-edited JSON read back by
        # update) still renders its block: gate on `is not None`, not truthiness.
        e = Entry(title="T", item_type="document", authors=[],
                  date="03/06/2026", tags=[], description="",
                  local_path="", remote_path="")
        h = html.render_entry(e)
        self.assertIn('id="localPath"></div>', h)            # empty local block present
        self.assertIn('<div class="remote-section">', h)     # remote section present
        self.assertIn("function copyPath(", h)               # script present
        self.assertIn("function copyFolderPath(", h)

    def test_none_paths_omit_blocks(self):
        # None (the absent case) still omits everything, unchanged.
        e = Entry(title="T", item_type="document", authors=[],
                  date="03/06/2026", tags=[], description="")
        h = html.render_entry(e)
        self.assertNotIn("Local Path:", h)
        self.assertNotIn('<div class="remote-section">', h)
        self.assertNotIn("copyFolderPath(", h)

    def test_remote_and_pdf_omitted_when_unset(self):
        e = Entry(title="T", item_type="document", authors=[],
                  date="03/06/2026", tags=[], description="",
                  local_path="C:\\f\\a1\\copy.docx")
        h = html.render_entry(e)
        self.assertNotIn('<div class="remote-section">', h)
        self.assertNotIn('class="pdf-btn"', h)
        self.assertNotIn("copyRemotePath", h)
        self.assertIn("function copyPath(", h)


class TestCopyCitekeyAndReference(unittest.TestCase):
    """The Reference and Citekey lines each carry a copy button. The value lives
    in an id'd span the JS reads, so nothing has to be escaped into onclick."""

    def _card(self, **kw):
        base = dict(title="T", item_type="document", authors=[],
                    date="03/06/2026", tags=[], description="")
        base.update(kw)
        return html.render_entry(Entry(**base))

    def test_both_buttons_are_rendered(self):
        h = self._card(reference="doc_note__20260903", citekey="Document20260903")
        self.assertIn(
            """<button class="copy-inline" onclick="copyPath('referenceValue', this,"""
            """ 'Copy Reference')">&#128203; Copy Reference</button>""", h)
        self.assertIn(
            """<button class="copy-inline" onclick="copyPath('citekeyValue', this,"""
            """ 'Copy Citekey')">&#128203; Copy Citekey</button>""", h)

    def test_values_stay_inside_their_labelled_paragraph(self):
        h = self._card(reference="R1", citekey="C1")
        self.assertIn('<p><strong>Reference:</strong> <span id="referenceValue">R1</span>', h)
        self.assertIn('<p><strong>Citekey:</strong> <span id="citekeyValue">C1</span>', h)

    def test_values_are_escaped_not_interpolated_into_js(self):
        # A reference with a quote/ampersand would break an onclick argument; it
        # is escaped in the span instead, and the onclick never carries the value.
        h = self._card(reference='A"B&C', citekey="C1")
        self.assertIn('<span id="referenceValue">A&quot;B&amp;C</span>', h)
        self.assertNotIn('A"B&C', h)

    def test_script_is_emitted_even_with_no_paths(self):
        h = self._card(reference="R1", citekey="C1")
        self.assertIn("function copyPath(", h)
        self.assertNotIn("function copyFolderPath(", h)

    def test_style_defines_the_inline_button(self):
        h = self._card()
        self.assertIn(".copy-inline    {", h)
        self.assertIn(".copy-inline.copied  {", h)


if __name__ == "__main__":
    unittest.main()
