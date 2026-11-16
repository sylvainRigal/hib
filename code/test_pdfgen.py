"""Quick unit tests for pdfgen.generate_pdf.

Stage 1 (Python: docx2pdf -> Word) and stage 2 (the fallback external converter
declared by the operator). The exhaustive stage-1 suite -- real child process,
fake docx2pdf injected, optional Word integration run -- lives in
test_docx2pdf_convercion.py. These are the fast branch checks that run on every
`unittest discover`.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import pdfgen
from config import Config


CONVERTER_PRESENT = object()   # any non-None: "docx2pdf is importable"


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hibpy_pdfgen_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.msgs = []
        # No fallback converter unless a test declares one: point both the
        # pointer file and the built-in default at paths that cannot exist, so
        # the machine's real %LOCALAPPDATA%\hib\config.toml never leaks in.
        self._no_fallback()

    def _no_fallback(self):
        self._set_local_config(os.path.join(self.tmp, "nope", "config.toml"))
        p = mock.patch.object(pdfgen, "_DEFAULT_FALLBACK_CONFIG",
                              os.path.join(self.tmp, "nope", "fallback.toml"))
        p.start()
        self.addCleanup(p.stop)

    def _set_local_config(self, path):
        p = mock.patch.object(pdfgen, "_LOCAL_CONFIG", path)
        p.start()
        self.addCleanup(p.stop)

    def _write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def call(self, copy_name="x.docx"):
        ext = copy_name[copy_name.rfind("."):]
        self.input_path = os.path.join(self.tmp, "x" + ext)
        self.output_path = os.path.join(self.tmp, "x.pdf")
        return pdfgen.generate_pdf(Config(r"C:\f", r"C:\h", r"C:\j"), copy_name,
                                   self.input_path, self.tmp, self.output_path,
                                   self.msgs.append)


class TestGatingBeforeAnyConversion(_Base):
    """Decided on the extension alone -- no converter, no child process."""

    def test_pdf_source_is_already_pdf(self):
        self.assertEqual(self.call("x.pdf"), "already_pdf")
        self.assertEqual(self.call("X.PDF"), "already_pdf")
        self.assertEqual(self.msgs, [])

    def test_non_office_unsupported(self):
        self.assertEqual(self.call("x.txt"), "unsupported")
        self.assertEqual(self.msgs, [])

    def test_no_converter_when_nothing_is_available(self):
        with mock.patch.object(pdfgen, "_docx2pdf", None):
            self.assertEqual(self.call("x.docx"), "no_converter")
        self.assertEqual(self.msgs, [])


class TestWordStage(_Base):
    """docx2pdf considered present; its child process is simulated."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(pdfgen, "_docx2pdf", CONVERTER_PRESENT)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(pdfgen.subprocess, "Popen")
        self.popen = p.start()
        self.addCleanup(p.stop)

    def _child(self, returncode=0, writes_pdf=True, stderr=b"", communicate=None):
        proc = mock.MagicMock(name="proc")
        proc.returncode = returncode
        if communicate is None:
            proc.communicate.return_value = (b"", stderr)
        else:
            proc.communicate.side_effect = communicate

        def side_effect(argv, **kwargs):
            if writes_pdf:
                with open(argv[-1], "wb") as f:
                    f.write(b"%PDF-1.4 mock")
            return proc

        self.popen.side_effect = side_effect
        return proc

    def test_generated(self):
        proc = self._child()
        self.assertEqual(self.call(), "generated")
        self.assertTrue(os.path.exists(self.output_path))
        self.assertEqual(self.msgs, ["Generating PDF..."])
        proc.communicate.assert_called_once_with(timeout=60)

    def test_child_runs_docx2pdf_in_python(self):
        self._child()
        self.call()
        argv = self.popen.call_args[0][0]
        self.assertIn("docx2pdf.convert(sys.argv[1], sys.argv[2])", argv[argv.index("-c") + 1])
        self.assertEqual(argv[-2:], [self.input_path, self.output_path])

    def test_failure_reports_the_child_stderr_reason(self):
        self._child(returncode=1, writes_pdf=False,
                    stderr=b"Traceback...\nModuleNotFoundError: No module named 'win32com'\n")
        self.assertEqual(self.call(), "failed")
        self.assertIn("exited abnormally (code 1)", self.msgs[-1])
        self.assertIn("No module named 'win32com'", self.msgs[-1])
        self.assertIn("continuing without a PDF", self.msgs[-1])

    def test_failure_without_stderr_still_reports_the_code(self):
        self._child(returncode=1, writes_pdf=False)
        self.assertEqual(self.call(), "failed")
        self.assertIn("exited abnormally (code 1)", self.msgs[-1])

    def test_success_without_output_file(self):
        self._child(returncode=0, writes_pdf=False)
        self.assertEqual(self.call(), "failed")
        self.assertIn("produced no PDF", self.msgs[-1])

    def test_timeout_is_not_fatal(self):
        proc = self._child(returncode=None, writes_pdf=False,
                           communicate=[subprocess.TimeoutExpired(cmd="docx2pdf", timeout=60),
                                        (b"", b"")])
        self.assertEqual(self.call(), "failed")
        proc.kill.assert_called_once_with()
        self.assertIn("timed out", self.msgs[-1])

    def test_launch_error_is_not_fatal(self):
        # OSError / ValueError ("embedded null character") must never abort the add
        # and orphan the storage folder -- the "never raises" guarantee.
        for exc in (OSError(2, "No such file or directory"), ValueError("embedded null character")):
            with self.subTest(exc=exc):
                self.msgs = []
                self.popen.side_effect = exc
                self.assertEqual(self.call(), "failed")
                self.assertIn("failed to run", self.msgs[-1])


class TestFrozenBuild(_Base):
    """In a PyInstaller build sys.executable IS hib.exe, so the conversion child
    is the exe itself re-invoked with the private flag -- never `python -c`, which
    hib.exe would parse as a file to add."""

    def test_source_checkout_spawns_python_dash_c(self):
        argv = pdfgen._word_child_argv("in.docx", "out.pdf")
        self.assertEqual(argv[0], sys.executable)
        self.assertIn("-c", argv)
        self.assertNotIn(pdfgen.CHILD_FLAG, argv)

    def test_frozen_build_reinvokes_itself(self):
        with mock.patch.object(pdfgen, "_FROZEN", True):
            argv = pdfgen._word_child_argv("in.docx", "out.pdf")
        self.assertEqual(argv, [sys.executable, pdfgen.CHILD_FLAG, "in.docx", "out.pdf"])

    def test_generate_pdf_uses_the_frozen_child(self):
        with mock.patch.object(pdfgen, "_docx2pdf", CONVERTER_PRESENT), \
             mock.patch.object(pdfgen, "_FROZEN", True), \
             mock.patch.object(pdfgen.subprocess, "Popen") as popen:
            proc = mock.MagicMock(returncode=0)
            proc.communicate.return_value = (b"", b"")

            def side_effect(argv, **kwargs):
                with open(argv[-1], "wb") as f:
                    f.write(b"%PDF-1.4 mock")
                return proc

            popen.side_effect = side_effect
            self.assertEqual(self.call(), "generated")
        self.assertEqual(popen.call_args[0][0][1], pdfgen.CHILD_FLAG)

    def test_convert_child_rejects_a_bad_arity(self):
        self.assertEqual(pdfgen.convert_child([]), 2)
        self.assertEqual(pdfgen.convert_child(["only-one"]), 2)


class TestFallbackDeclaration(_Base):
    """Where the fallback converter is declared, and how its argv is built."""

    def _declare(self, pdf_section):
        """Write both files of the chain: the hard-coded pointer, and the file it
        points at."""
        fallback = self._write("fallback.toml", "[pdf]\n" + pdf_section)
        self._set_local_config(
            self._write("local.toml", "[pdf]\nfallback_config = '%s'\n" % fallback))
        return fallback

    def _argv(self, pdf_section):
        self._declare(pdf_section)
        return pdfgen.fallback_argv(r"C:\f\a1\x.docx", r"C:\f\a1", r"C:\f\a1\x.pdf")

    def test_pointer_is_read_from_the_hard_coded_config(self):
        fallback = self._declare("converter = 'pandoc.exe'\n")
        self.assertEqual(pdfgen.fallback_config_path(), fallback)

    def test_pointer_expands_environment_variables(self):
        self._set_local_config(
            self._write("local.toml", "[pdf]\nfallback_config = '%LOCALAPPDATA%\\hib\\c.toml'\n"))
        self.assertEqual(pdfgen.fallback_config_path(),
                         os.path.join(os.environ["LOCALAPPDATA"], "hib", "c.toml"))

    def test_default_pointer_when_the_key_is_absent(self):
        self._set_local_config(self._write("local.toml", "[storage]\nfile = 'C:\\f'\n"))
        with mock.patch.object(pdfgen, "_DEFAULT_FALLBACK_CONFIG", r"%LOCALAPPDATA%\hib\config.toml"):
            self.assertEqual(pdfgen.fallback_config_path(),
                             os.path.join(os.environ["LOCALAPPDATA"], "hib", "config.toml"))

    def test_args_inferred_for_pandoc(self):
        argv, exe = self._argv(r"converter = 'C:\tools\pandoc.exe'" + "\n")
        self.assertEqual(exe, r"C:\tools\pandoc.exe")
        self.assertEqual(argv, [r"C:\tools\pandoc.exe", r"C:\f\a1\x.docx", "-o", r"C:\f\a1\x.pdf"])

    def test_args_inferred_for_soffice(self):
        argv, _ = self._argv(r"converter = 'C:\tools\soffice.exe'" + "\n")
        self.assertEqual(argv[1:], ["--headless", "--convert-to", "pdf",
                                    "--outdir", r"C:\f\a1", r"C:\f\a1\x.docx"])

    def test_explicit_args_win(self):
        argv, _ = self._argv("converter = 'conv.exe'\nargs = '--to pdf {input} {output}'\n")
        self.assertEqual(argv, ["conv.exe", "--to", "pdf", r"C:\f\a1\x.docx", r"C:\f\a1\x.pdf"])

    def test_unknown_tool_gets_input_output(self):
        argv, _ = self._argv("converter = 'mystery.exe'\n")
        self.assertEqual(argv[1:], [r"C:\f\a1\x.docx", r"C:\f\a1\x.pdf"])

    def test_cmd_template_keeps_a_quoted_path_in_one_token(self):
        argv, exe = self._argv(
            'cmd = \'"C:\\Program Files\\soffice.exe" --outdir {outdir} {input}\'\n')
        self.assertEqual(exe, r"C:\Program Files\soffice.exe")
        self.assertEqual(argv, [r"C:\Program Files\soffice.exe", "--outdir",
                                r"C:\f\a1", r"C:\f\a1\x.docx"])

    def test_no_declaration_means_no_fallback(self):
        self.assertIsNone(self._argv("powershell = ''\ncmd = ''\n"))

    def test_missing_fallback_file_means_no_fallback(self):
        self._set_local_config(
            self._write("local.toml", "[pdf]\nfallback_config = 'Z:\\nope\\x.toml'\n"))
        self.assertIsNone(pdfgen.fallback_argv("i.docx", ".", "o.pdf"))

    def test_malformed_command_is_not_fatal(self):
        # An unterminated quote must yield "no fallback", never an exception.
        self.assertIsNone(self._argv('cmd = \'conv.exe "oops {input}\'\n'))


class TestFallbackConversion(_Base):
    """The fallback really runs: a small Python script stands in for pandoc."""

    def setUp(self):
        super().setUp()
        self.converter = self._write("fakeconv.py", CONVERTER_SCRIPT)

    def _declare(self, args="{input} {output}"):
        fallback = self._write(
            "fallback.toml",
            "[pdf]\nconverter = '%s'\nargs = '\"%s\" %s'\n"
            % (sys.executable, self.converter, args))
        self._set_local_config(
            self._write("local.toml", "[pdf]\nfallback_config = '%s'\n" % fallback))

    def _input(self, name="x.docx"):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(b"fake docx")
        return path

    def test_fallback_rescues_a_failed_word_conversion(self):
        self._declare()
        self._input()
        with mock.patch.object(pdfgen, "_docx2pdf", CONVERTER_PRESENT), \
             mock.patch.object(pdfgen, "_convert_with_word",
                               return_value=(False, "hib: PDF converter exited abnormally (code 1)")):
            self.assertEqual(self.call(), "generated")
        with open(self.output_path, "rb") as f:
            self.assertTrue(f.read().startswith(b"%PDF"))
        self.assertIn("trying the fallback converter", self.msgs[-1])

    def test_fallback_used_when_docx2pdf_is_not_installed(self):
        self._declare()
        self._input()
        with mock.patch.object(pdfgen, "_docx2pdf", None):
            self.assertEqual(self.call(), "generated")
        self.assertTrue(os.path.exists(self.output_path))

    def test_fallback_output_named_after_the_input_is_moved(self):
        # soffice & co. write <input stem>.pdf into --outdir; hib may want another
        # name. HIB_FAKE_OUTDIR makes the stand-in behave that way.
        self._declare(args="--outdir {outdir} {input}")
        self._input("source.docx")
        with mock.patch.object(pdfgen, "_docx2pdf", None):
            res = pdfgen.generate_pdf(None, "source.docx",
                                      os.path.join(self.tmp, "source.docx"), self.tmp,
                                      os.path.join(self.tmp, "renamed.pdf"), self.msgs.append)
        self.assertEqual(res, "generated")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "renamed.pdf")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "source.pdf")))

    def test_failing_fallback_reports_and_never_raises(self):
        self._declare(args="--fail {input} {output}")
        self._input()
        with mock.patch.object(pdfgen, "_docx2pdf", None):
            self.assertEqual(self.call(), "failed")
        self.assertIn("fallback converter exited abnormally", self.msgs[-1])
        self.assertIn("boom", self.msgs[-1])

    def test_missing_fallback_executable_is_not_fatal(self):
        fallback = self._write("fallback.toml", "[pdf]\nconverter = 'Z:\\nope\\pandoc.exe'\n")
        self._set_local_config(
            self._write("local.toml", "[pdf]\nfallback_config = '%s'\n" % fallback))
        self._input()
        with mock.patch.object(pdfgen, "_docx2pdf", None):
            self.assertEqual(self.call(), "failed")
        self.assertIn("fallback converter failed to run", self.msgs[-1])


# Stand-in for pandoc/soffice: writes a PDF where it is told, or fails on demand.
CONVERTER_SCRIPT = '''\
import os
import sys

args = sys.argv[1:]
if args and args[0] == "--fail":
    sys.stderr.write("boom\\n")
    sys.exit(3)
if args and args[0] == "--outdir":          # soffice style: name it after the input
    outdir, source = args[1], args[2]
    target = os.path.join(outdir, os.path.splitext(os.path.basename(source))[0] + ".pdf")
else:
    target = args[1]
with open(target, "wb") as f:
    f.write(b"%PDF-1.4 fallback")
'''


if __name__ == "__main__":
    unittest.main()
