import json
import os
import tempfile
import unittest

import config
import selector


def _write_entry(d, citekey, **extra):
    obj = {"citekey": citekey, "title": citekey, "reference": "ref_" + citekey,
           "htmlPath": "C:\\html\\%s.html" % citekey,
           "localFolderPath": "C:\\f\\%s" % citekey}
    obj.update(extra)
    with open(os.path.join(d, citekey + ".json"), "w", encoding="utf-8") as f:
        json.dump(obj, f)


class TestSelector(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = config.Config("C:\\f", "C:\\html", self.tmp)

    def tearDown(self):
        for n in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, n))
        os.rmdir(self.tmp)

    def test_exact_then_partial_precedence(self):
        _write_entry(self.tmp, "Report1")
        _write_entry(self.tmp, "Report10")     # contains "Report1" as a substring
        # exact "Report1" wins -> only Report1 (Report10 NOT included)
        m = selector.find_entries(self.cfg, "citekey", "Report1")
        self.assertEqual([f.meta.citekey for f in m], ["Report1"])
        # a partial that is no exact match lists both
        m2 = selector.find_entries(self.cfg, "citekey", "Report")
        self.assertEqual(sorted(f.meta.citekey for f in m2), ["Report1", "Report10"])

    def test_bare_selector_accepts_a_citekey_or_a_reference(self):
        # "any" is what a bare `hib <cmd> <value>` produces: citekey and reference
        # are interchangeable, no flag needed.
        _write_entry(self.tmp, "Report1")               # reference is "ref_Report1"
        _write_entry(self.tmp, "Report10")
        by_key = selector.find_entries(self.cfg, "any", "Report1")
        self.assertEqual([f.meta.citekey for f in by_key], ["Report1"])
        by_ref = selector.find_entries(self.cfg, "any", "ref_Report1")
        self.assertEqual([f.meta.citekey for f in by_ref], ["Report1"])
        self.assertEqual([f.meta.citekey for f in
                          selector.find_entries(self.cfg, "any", "REF_REPORT1")],
                         ["Report1"])                    # case-insensitive

    def test_bare_selector_exact_beats_partial_across_both_fields(self):
        _write_entry(self.tmp, "Report1")
        _write_entry(self.tmp, "Report10")
        # "ref_Report1" is exact for Report1 and a substring of Report10's
        # reference ("ref_Report10"): the exact match wins alone.
        m = selector.find_entries(self.cfg, "any", "ref_Report1")
        self.assertEqual([f.meta.citekey for f in m], ["Report1"])
        # A value that is exact for neither lists both (pick list).
        m2 = selector.find_entries(self.cfg, "any", "ref_Report")
        self.assertEqual(sorted(f.meta.citekey for f in m2), ["Report1", "Report10"])

    def test_bare_selector_lists_an_entry_once_when_both_fields_match(self):
        _write_entry(self.tmp, "K1", reference="K1")     # citekey == reference
        m = selector.find_entries(self.cfg, "any", "K1")
        self.assertEqual([f.meta.citekey for f in m], ["K1"])

    def test_explicit_flags_stay_strict(self):
        _write_entry(self.tmp, "Report1")
        # -citekey does not look at references, -ref does not look at citekeys.
        self.assertEqual(selector.find_entries(self.cfg, "citekey", "ref_Report1"), [])
        self.assertEqual(selector.find_entries(self.cfg, "reference", "Report1"), [])

    def test_resolve_single_none_pick_and_nonascii(self):
        _write_entry(self.tmp, "ReportRigal20250101")
        _write_entry(self.tmp, "ReportDoe20240202")
        msgs = []

        # exact unique -> returns it directly
        r = selector.resolve_entry(self.cfg, "citekey", "ReportDoe20240202",
                                   lambda t: "", msgs.append)
        self.assertEqual(r.meta.citekey, "ReportDoe20240202")

        # partial 'Report' -> multiple -> pick "1"
        picked = selector.resolve_entry(self.cfg, "citekey", "Report",
                                        lambda t: "1\n", msgs.append)
        self.assertIsNotNone(picked)

        # a non-ASCII "digit" must NOT crash -> clean cancel
        cancelled = selector.resolve_entry(self.cfg, "citekey", "Report",
                                           lambda t: "²\n", msgs.append)   # superscript two
        self.assertIsNone(cancelled)

        # blank -> cancel
        blank = selector.resolve_entry(self.cfg, "citekey", "Report",
                                       lambda t: "\n", msgs.append)
        self.assertIsNone(blank)

        # no match
        none = selector.resolve_entry(self.cfg, "citekey", "zzz",
                                      lambda t: "", msgs.append)
        self.assertIsNone(none)
        self.assertTrue(any("no entry found" in m for m in msgs))

    def test_case_sensitive_json_extension(self):
        # an uppercase .JSON file must be skipped (case-sensitive suffix match)
        with open(os.path.join(self.tmp, "Up.JSON"), "w", encoding="utf-8") as f:
            f.write('{"citekey":"upcase"}')
        self.assertEqual(selector.find_entries(self.cfg, "citekey", "upcase"), [])


if __name__ == "__main__":
    unittest.main()
