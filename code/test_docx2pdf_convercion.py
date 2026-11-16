#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests de generate_pdf() -- conversion .docx -> .pdf déléguée à docx2pdf.

Trois niveaux, du plus isolé au plus réel :

  1. Tests unitaires (Popen simulé) : aucun process n'est lancé, toutes les
     branches sont couvertes, y compris le timeout et les erreurs de lancement.
  2. Tests "process enfant réel" : un FAUX module docx2pdf est injecté (via
     PYTHONPATH et via le répertoire courant) et le vrai enfant `python -c ...`
     est exécuté. Vérifie le contrat argv / code retour / fichier produit, sans
     avoir besoin de Word. Un contrôle préalable (setUpClass) s'assure que
     l'enfant démarre et trouve le faux module ; sinon la classe entière échoue
     en affichant le stderr de l'enfant, que generate_pdf() jette.
  3. Test d'intégration (Word requis) : vraie conversion d'un .docx minimal.
     Désactivé par défaut, activer avec HIB_PDF_INTEGRATION=1.

Lancement, depuis le dossier du projet (pour que `sanitize` et `uri` s'importent) :

    python test_generate_pdf.py
    python -m unittest -v test_generate_pdf

`-E -s` sont acceptés. Ne PAS lancer avec `-I` : si generate_pdf() répercute
cette option sur l'enfant, celui-ci ne verrait plus le faux docx2pdf.

Si generate_pdf() n'est pas dans pdfgen.py, indiquer le module importable :

    PowerShell : $env:HIB_PDF_MODULE = "hib.pdfgen"
    cmd        : set HIB_PDF_MODULE=hib.pdfgen
"""
import importlib
import os
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from unittest import mock

MODULE_NAME = os.environ.get("HIB_PDF_MODULE", "pdfgen")   # <- adapter si besoin
mod = importlib.import_module(MODULE_NAME)
generate_pdf = mod.generate_pdf

# N'importe quel objet non-None : simule "docx2pdf importable" sans l'installer.
CONVERTER_PRESENT = object()

# Faux docx2pdf importé par le process enfant à la place du vrai. Comportement
# piloté par la variable d'environnement HIB_FAKE_DOCX2PDF (héritée par l'enfant).
FAKE_DOCX2PDF_SRC = '''\
"""Faux docx2pdf pour les tests (pas de Word). Modes : ok | raise | exit | silent."""
import os
import sys


def convert(input_path, output_path=None, keep_active=False):
    mode = os.environ.get("HIB_FAKE_DOCX2PDF", "ok")
    if mode == "raise":
        raise RuntimeError("erreur de conversion simulee")
    if mode == "exit":            # ce que fait docx2pdf sur macOS en cas d'echec
        sys.exit(1)
    if mode == "silent":          # succes annonce, mais aucun fichier ecrit
        return
    if not os.path.exists(input_path):
        raise FileNotFoundError(input_path)
    with open(output_path, "wb") as f:
        f.write(b"%PDF-1.4 fake")
'''

# .docx minimal valide (une ligne de texte), sans dépendre de python-docx.
_DOCX_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>')
_DOCX_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '</Relationships>')
_DOCX_DOCUMENT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:body><w:p><w:r><w:t>Test de conversion hib</w:t></w:r></w:p></w:body>'
    '</w:document>')


def write_minimal_docx(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        z.writestr("_rels/.rels", _DOCX_RELS)
        z.writestr("word/document.xml", _DOCX_DOCUMENT)


def fake_proc(returncode=0, communicate=None):
    """Imite l'objet Popen : returncode fixe, communicate() paramétrable."""
    proc = mock.MagicMock(name="proc")
    proc.returncode = returncode
    if communicate is None:
        proc.communicate.return_value = (b"", b"")
    else:
        proc.communicate.side_effect = communicate   # liste : un élément par appel
    return proc


def child_diag(argv):
    """Relance la commande enfant en capturant stderr (generate_pdf() le jette)."""
    r = subprocess.run(argv, capture_output=True, text=True, errors="replace")
    return "$ %s\n[exit %s]\n%s" % (subprocess.list2cmdline(argv),
                                     r.returncode, r.stderr.strip())


class _Base(unittest.TestCase):
    """Dossier temporaire, faux .docx en entrée, collecte des lignes de `out`."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.input_path = os.path.join(self.tmp, "rapport.docx")
        with open(self.input_path, "wb") as f:
            f.write(b"faux docx")
        self.output_path = os.path.join(self.tmp, "rapport.pdf")
        self.messages = []
        # Ces tests decrivent l'etage Python (docx2pdf) seul : on neutralise le
        # convertisseur externe de repli, sinon un poste ou pandoc/soffice est
        # declare le verrait rattraper les echecs attendus ici.
        p = mock.patch.object(mod, "fallback_argv", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)

    def out(self, line):
        self.messages.append(line)

    def call(self, copy_name="rapport.docx", input_path=None, output_path=None):
        return generate_pdf(
            None,                               # config : inutilisé
            copy_name,
            input_path or self.input_path,
            self.tmp,                           # out_dir : inutilisé
            output_path or self.output_path,
            self.out)


# ---------------------------------------------------------------------------
# 1. Tests unitaires
# ---------------------------------------------------------------------------

class PreChecksTests(_Base):
    """Branches qui sortent AVANT tout lancement de process."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(mod.subprocess, "Popen")
        self.popen = p.start()
        self.addCleanup(p.stop)

    def test_pdf_copy_is_already_pdf(self):
        self.assertEqual(self.call("scan.pdf"), "already_pdf")
        self.popen.assert_not_called()
        self.assertEqual(self.messages, [])

    def test_pdf_check_is_case_insensitive(self):
        self.assertEqual(self.call("SCAN.PDF"), "already_pdf")

    def test_already_pdf_wins_even_without_converter(self):
        with mock.patch.object(mod, "_docx2pdf", None):
            self.assertEqual(self.call("scan.pdf"), "already_pdf")

    def test_non_office_extension_is_unsupported(self):
        for name in ("notes.txt", "photo.jpg", "archive.zip"):
            with self.subTest(name=name):
                self.assertEqual(self.call(name), "unsupported")
        self.popen.assert_not_called()
        self.assertEqual(self.messages, [])

    def test_missing_converter(self):
        with mock.patch.object(mod, "_docx2pdf", None):
            for name in ("rapport.docx", "ancien.doc"):
                with self.subTest(name=name):
                    self.assertEqual(self.call(name), "no_converter")
        self.popen.assert_not_called()
        self.assertEqual(self.messages, [])


class MockedConverterTests(_Base):
    """docx2pdf est considéré présent ; subprocess.Popen est simulé."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(mod, "_docx2pdf", CONVERTER_PRESENT)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(mod.subprocess, "Popen")
        self.popen = p.start()
        self.addCleanup(p.stop)
        self.proc = None

    def _simulate_child(self, returncode=0, writes_pdf=True, communicate=None):
        """Popen renvoie un faux process ; écrit (ou non) le PDF attendu."""
        self.proc = fake_proc(returncode, communicate)

        def side_effect(argv, **kwargs):
            if writes_pdf:
                with open(argv[-1], "wb") as f:
                    f.write(b"%PDF-1.4 mock")
            return self.proc

        self.popen.side_effect = side_effect

    def _child_argv(self):
        return self.popen.call_args[0][0]

    def test_generated(self):
        self._simulate_child()
        self.assertEqual(self.call(), "generated")
        self.assertTrue(os.path.exists(self.output_path))
        self.assertEqual(self.messages, ["Generating PDF..."])
        self.proc.communicate.assert_called_once_with(timeout=60)
        self.proc.kill.assert_not_called()

    def test_child_invocation(self):
        self._simulate_child()
        self.call()
        (argv,), kwargs = self.popen.call_args
        c = argv.index("-c")
        self.assertEqual(argv[0], sys.executable)
        # Entre l'exécutable et -c : au plus des options d'isolation.
        self.assertTrue(set(argv[1:c]) <= {"-I", "-E", "-s"}, argv)
        self.assertIn("docx2pdf.convert(sys.argv[1], sys.argv[2])", argv[c + 1])
        self.assertEqual(argv[c + 2:], [self.input_path, self.output_path])
        self.assertEqual(kwargs, {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "creationflags": mod._NO_WINDOW,
        })

    def test_child_inherits_isolation_flags(self):
        """L'enfant doit recevoir les options -I, ou -E / -s, de ce process :
        s'il a fallu `python -E` pour démarrer ici (PYTHONHOME / PYTHONPATH
        pollués), l'enfant en a besoin aussi. Échoue tant que le correctif
        _child_python_flags() n'est pas appliqué dans generate_pdf()."""
        cases = [
            (dict(isolated=0, ignore_environment=0, no_user_site=0), []),
            (dict(isolated=0, ignore_environment=1, no_user_site=0), ["-E"]),
            (dict(isolated=0, ignore_environment=1, no_user_site=1), ["-E", "-s"]),
            (dict(isolated=1, ignore_environment=1, no_user_site=1), ["-I"]),
        ]
        for flags, expected in cases:
            with self.subTest(expected=expected):
                self._simulate_child()
                with mock.patch.object(sys, "flags", types.SimpleNamespace(**flags)):
                    self.call()
                argv = self._child_argv()
                self.assertEqual(argv[1:argv.index("-c")], expected)

    def test_nonzero_exit_code(self):
        self._simulate_child(returncode=1, writes_pdf=False)
        self.assertEqual(self.call(), "failed")
        self.assertFalse(os.path.exists(self.output_path))
        self.assertEqual(self.messages[0], "Generating PDF...")
        self.assertIn("exited abnormally (code 1)", self.messages[-1])

    def test_nonzero_exit_code_wins_over_partial_pdf(self):
        # Un PDF partiel peut exister ; le code retour prime.
        self._simulate_child(returncode=1, writes_pdf=True)
        self.assertEqual(self.call(), "failed")

    def test_child_killed_by_signal(self):
        # Sous POSIX, un enfant tué a un returncode négatif.
        self._simulate_child(returncode=-9, writes_pdf=False)
        self.assertEqual(self.call(), "failed")
        self.assertIn("code -9", self.messages[-1])

    def test_success_without_output_file(self):
        self._simulate_child(returncode=0, writes_pdf=False)
        self.assertEqual(self.call(), "failed")
        self.assertIn("produced no PDF", self.messages[-1])

    def test_timeout_kills_child(self):
        self._simulate_child(
            returncode=None, writes_pdf=False,
            communicate=[subprocess.TimeoutExpired(cmd="docx2pdf", timeout=60),
                         (b"", b"")])
        self.assertEqual(self.call(), "failed")
        self.proc.kill.assert_called_once_with()
        self.assertEqual(self.proc.communicate.call_count, 2)   # timeout, puis reap
        self.assertIn("timed out", self.messages[-1])

    def test_popen_oserror(self):
        self.popen.side_effect = OSError(2, "No such file or directory")
        self.assertEqual(self.call(), "failed")
        self.assertIn("failed to run", self.messages[-1])
        self.assertIn("continuing without a PDF", self.messages[-1])

    def test_popen_valueerror(self):
        self.popen.side_effect = ValueError("embedded null character")
        self.assertEqual(self.call(), "failed")
        self.assertIn("failed to run", self.messages[-1])


# ---------------------------------------------------------------------------
# 2. Vrai process enfant, faux docx2pdf injecté
# ---------------------------------------------------------------------------

class RealChildProcessTests(_Base):
    """Exécute réellement `python -c ...` ; docx2pdf est remplacé par un faux."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        fake_dir = os.path.join(tmp.name, "fake_site")
        os.mkdir(fake_dir)
        with open(os.path.join(fake_dir, "docx2pdf.py"), "w", encoding="utf-8") as f:
            f.write(FAKE_DOCX2PDF_SRC)
        # Double injection : PYTHONPATH (ignoré si l'enfant tourne avec -E) et
        # répertoire courant (sys.path[0] == '' pour `python -c`, sauf -I / -P).
        pythonpath = os.pathsep.join(
            [fake_dir] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p])
        env = mock.patch.dict(os.environ, {"PYTHONPATH": pythonpath,
                                           "HIB_FAKE_DOCX2PDF": "ok"})
        env.start()
        cls.addClassCleanup(env.stop)
        cls.addClassCleanup(os.chdir, os.getcwd())
        os.chdir(fake_dir)
        conv = mock.patch.object(mod, "_docx2pdf", CONVERTER_PRESENT)
        conv.start()
        cls.addClassCleanup(conv.stop)
        cls._preflight(tmp.name)

    @classmethod
    def _preflight(cls, tmp):
        """Une conversion en mode 'ok' doit réussir ; sinon, expliquer pourquoi."""
        src = os.path.join(tmp, "preflight.docx")
        with open(src, "wb") as f:
            f.write(b"faux docx")
        dst = os.path.join(tmp, "preflight.pdf")
        messages = []
        with mock.patch.object(mod.subprocess, "Popen", wraps=subprocess.Popen) as spy:
            result = generate_pdf(None, "preflight.docx", src, tmp, dst, messages.append)
        if result == "generated":
            return
        detail = "\n".join(messages)
        if spy.call_args:
            detail += "\n" + child_diag(spy.call_args[0][0])
        raise AssertionError(
            "Le process enfant lancé par generate_pdf() ne fonctionne pas dans cet "
            "environnement (résultat %r).\n"
            "- 'Fatal Python error', 'encodings' ou 'site' dans le stderr : PYTHONHOME "
            "ou PYTHONPATH sont pollués et l'enfant ne reçoit pas les options -E/-s "
            "de ce process (correctif : _child_python_flags()).\n"
            "- 'No module named docx2pdf' : l'enfant ignore PYTHONPATH et le "
            "répertoire courant (mode -I, ou fichier ._pth à côté de python.exe).\n"
            "%s" % (result, detail))

    def setUp(self):
        super().setUp()
        self.child_argv = None
        self._mode("ok")

    @staticmethod
    def _mode(mode):
        os.environ["HIB_FAKE_DOCX2PDF"] = mode   # restauré par patch.dict (classe)

    def call(self, *args, **kwargs):
        """Comme _Base.call, mais mémorise l'argv réellement passé à Popen."""
        with mock.patch.object(mod.subprocess, "Popen", wraps=subprocess.Popen) as spy:
            result = super().call(*args, **kwargs)
        self.child_argv = spy.call_args[0][0] if spy.call_args else None
        return result

    def diag(self):
        lines = list(self.messages)
        if self.child_argv:
            lines.append(child_diag(self.child_argv))
        return "\n".join(lines)

    def test_generated_end_to_end(self):
        self.assertEqual(self.call(), "generated", self.diag())
        with open(self.output_path, "rb") as f:
            self.assertTrue(f.read().startswith(b"%PDF"))
        self.assertEqual(self.messages, ["Generating PDF..."])

    def test_paths_with_spaces_and_accents(self):
        input_path = os.path.join(self.tmp, "mon rapport été.docx")
        output_path = os.path.join(self.tmp, "mon rapport été.pdf")
        with open(input_path, "wb") as f:
            f.write(b"faux docx")
        self.assertEqual(self.call(input_path=input_path, output_path=output_path),
                         "generated", self.diag())
        self.assertTrue(os.path.exists(output_path))

    def test_child_exception_is_failed(self):
        self._mode("raise")
        self.assertEqual(self.call(), "failed")
        self.assertFalse(os.path.exists(self.output_path))
        self.assertIn("code 1", self.messages[-1])

    def test_child_sys_exit_is_failed(self):
        self._mode("exit")
        self.assertEqual(self.call(), "failed")
        self.assertIn("code 1", self.messages[-1])

    def test_child_success_without_file_is_failed(self):
        self._mode("silent")
        self.assertEqual(self.call(), "failed", self.diag())
        self.assertIn("produced no PDF", self.messages[-1])

    def test_missing_input_file_is_failed(self):
        os.remove(self.input_path)
        self.assertEqual(self.call(), "failed")

    def test_nul_in_path_never_raises(self):
        # Popen refuse un NUL dans un argument (ValueError) : doit donner 'failed'.
        bad = os.path.join(self.tmp, "mauvais\x00nom.docx")
        self.assertEqual(self.call(input_path=bad), "failed")
        self.assertIn("failed to run", self.messages[-1])


# ---------------------------------------------------------------------------
# 3. Intégration : vraie conversion via Word (optionnel, lent)
# ---------------------------------------------------------------------------

@unittest.skipUnless(os.environ.get("HIB_PDF_INTEGRATION") == "1",
                     "définir HIB_PDF_INTEGRATION=1 pour la vraie conversion (Word requis)")
class WordIntegrationTests(_Base):

    def test_real_conversion(self):
        if mod._docx2pdf is None:
            self.skipTest("docx2pdf n'est pas installé dans cet interpréteur")
        write_minimal_docx(self.input_path)
        result = self.call()
        self.assertEqual(result, "generated", "\n".join(self.messages))
        with open(self.output_path, "rb") as f:
            self.assertTrue(f.read(8).startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main(verbosity=2)