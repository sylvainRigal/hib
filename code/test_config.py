import os
import tempfile
import unittest

import config


class TestConfig(unittest.TestCase):
    def test_parse_toml(self):
        text = (
            "[storage]\n"
            "file  = 'C:\\hib\\f'\n"
            "html  = 'C:\\hib\\html'\n"
            "json  = 'C:\\hib\\json'\n"
            "trash = ''\n"
            "[pdf]\n"
            "powershell = ''\n"
            "cmd = 'copy /Y {input} {output}'\n"
        )
        c = config.parse_toml(text)
        self.assertEqual(c.file_storage_path, "C:\\hib\\f")
        self.assertEqual(c.html_storage_path, "C:\\hib\\html")
        self.assertEqual(c.json_storage_path, "C:\\hib\\json")
        self.assertIsNone(c.trash_storage_path)        # empty -> None
        self.assertEqual(c.pdf_converter_ps, "")       # present but empty
        self.assertEqual(c.pdf_converter_cmd, "copy /Y {input} {output}")
        with self.assertRaises(config.ConfigError):
            config.parse_toml("[storage]\nhtml='h'\njson='j'\n")

    def test_parse_backup_target(self):
        base = "[storage]\nfile='f'\nhtml='h'\njson='j'\n"
        self.assertIsNone(config.parse_toml(base).backup_target)           # absent
        self.assertIsNone(config.parse_toml(base + "[backup]\ntarget = ''\n").backup_target)
        c = config.parse_toml(base + "[backup]\ntarget = 'E:\\hib backup\\%USERNAME%'\n")
        self.assertEqual(c.backup_target, "E:\\hib backup\\%USERNAME%")    # literal, like storage
        # A `target` key in another section is not the backup target.
        self.assertIsNone(config.parse_toml(base + "[pdf]\ntarget = 'x'\n").backup_target)
        # The bootstrap template still parses once filled (its [backup] is commented).
        import hibtoml
        self.assertIn("# target = ''", hibtoml.TEMPLATE)
        self.assertIsNone(config.parse_legacy(
            'file storage path:"f"\nhtml storage path:"h"\njson storage path:"j"\n').backup_target)

    def test_parse_legacy_and_reject_toml(self):
        text = (
            'file storage path:"C:\\hib\\f"\n'
            'html storage path: "C:\\hib\\html"\n'
            'json storage path: "C:\\hib\\json"\n'
            "pdf converter (cmd): copy /Y {input} {output}\n"
        )
        c = config.parse_legacy(text)
        self.assertEqual(c.file_storage_path, "C:\\hib\\f")
        self.assertEqual(c.pdf_converter_cmd, "copy /Y {input} {output}")
        # TOML content fed to the legacy parser must be REJECTED, not mis-split.
        with self.assertRaises(config.ConfigError):
            config.parse_legacy("[storage]\nfile = 'C:\\hib\\f'\n")

    def test_parse_by_ext_case_insensitive(self):
        toml = "[storage]\nfile='f'\nhtml='h'\njson='j'\n"
        self.assertEqual(config.parse_by_ext("x.toml", toml).file_storage_path, "f")
        self.assertEqual(config.parse_by_ext("x.TOML", toml).file_storage_path, "f")
        legacy = 'file storage path:"f"\nhtml storage path:"h"\njson storage path:"j"\n'
        self.assertEqual(config.parse_by_ext("x.txt", legacy).file_storage_path, "f")

    def test_load_via_hib_config(self):
        msgs = []
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.toml")
            with open(p, "w", encoding="utf-8") as f:
                f.write("[storage]\nfile='F'\nhtml='H'\njson='J'\n")
            res = config.load({"HIB_CONFIG": p}, out=msgs.append)
            self.assertIsNotNone(res)
            cfg, cdir = res
            self.assertEqual(cfg.html_storage_path, "H")
            self.assertEqual(cdir, d)

    def test_load_bootstrap_when_nothing(self):
        msgs = []
        with tempfile.TemporaryDirectory() as d:
            res = config.load({"LOCALAPPDATA": d}, out=msgs.append)
            self.assertIsNone(res)                      # no config -> stop
            tmpl = os.path.join(d, "hib", "config", "config.toml")
            self.assertTrue(os.path.exists(tmpl))       # template written
            self.assertTrue(any("template" in m for m in msgs))

    def test_read_non_utf8_config_does_not_crash(self):
        # A config whose path has a cp1252 accented byte (0xE9 'é') must load,
        # not raise UnicodeDecodeError (configs are read as raw bytes).
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.toml")
            body = "[storage]\nfile  = 'C:\\caf\xe9\\f'\nhtml='H'\njson='J'\n"
            with open(p, "wb") as f:
                f.write(body.encode("cp1252"))
            res = config.load({"HIB_CONFIG": p}, out=lambda m: None)
            self.assertIsNotNone(res)
            self.assertEqual(res[0].file_storage_path, "C:\\caf\xe9\\f")

    def test_load_migrates_legacy(self):
        msgs = []
        with tempfile.TemporaryDirectory() as d:
            cdir = os.path.join(d, "hib", "config")
            os.makedirs(cdir)
            with open(os.path.join(cdir, "pathToFilesLocation.txt"), "w", encoding="utf-8") as f:
                f.write('file storage path:"C:\\a"\nhtml storage path:"C:\\b"\njson storage path:"C:\\c"\n')
            res = config.load({"LOCALAPPDATA": d}, out=msgs.append)
            self.assertIsNotNone(res)
            cfg, _ = res
            self.assertEqual(cfg.file_storage_path, "C:\\a")
            gen = os.path.join(cdir, "config.toml")
            self.assertTrue(os.path.exists(gen))        # migrated
            with open(gen, encoding="utf-8") as gf:
                back = config.parse_toml(gf.read())
            self.assertEqual(back.file_storage_path, "C:\\a")
            self.assertTrue(any("migrated" in m for m in msgs))


if __name__ == "__main__":
    unittest.main()
