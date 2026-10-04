"""La linea de comandos de punta a punta, con un repositorio en memoria."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from fakes import FakeRepository, metadata

from toml_deps_checker import __version__, cli

CATALOGO = """
[libraries]
gson = "com.google.code.gson:gson:2.10.1"
huerfana = { module = "com.x:sin-version" }
"""

FILES = {"com/google/code/gson/gson/maven-metadata.xml": metadata("2.10.1", "3.0.0")}


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = os.path.join(self.tmp.name, "proyecto")
        self.workdir = os.path.join(self.tmp.name, "trabajo")
        os.makedirs(os.path.join(self.project, "gradle"))
        os.makedirs(self.workdir)
        with open(os.path.join(self.project, "gradle", "libs.versions.toml"), "w",
                  encoding="utf-8") as handle:
            handle.write(CATALOGO)

        # Las cleanups van al reves: primero salir del directorio, luego borrarlo.
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.workdir)

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "MavenRepository", lambda **kw: FakeRepository(FILES, **kw)), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def read_output(self, name="dependency_status.json"):
        with open(os.path.join(self.workdir, name), encoding="utf-8") as handle:
            return json.load(handle)


class TestSalida(CliTestCase):
    def test_json_por_defecto_en_el_directorio_actual(self):
        code, stdout, _ = self.run_cli(self.project)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(self.workdir, "dependency_status.json")))
        self.assertIn(os.path.join(self.workdir, "dependency_status.json"), stdout)

    def test_acepta_la_raiz_del_proyecto_y_el_directorio_gradle(self):
        for path in (self.project, os.path.join(self.project, "gradle")):
            with self.subTest(path=path):
                self.assertEqual(self.run_cli(path, "-q")[0], 0)

    def test_progreso_por_stderr_y_resumen_por_stdout(self):
        _, stdout, stderr = self.run_cli(self.project)
        self.assertIn("Consultando", stderr)
        self.assertNotIn("Consultando", stdout)
        self.assertIn("Total: 2", stdout)

    def test_catalogo_inexistente(self):
        code, _, stderr = self.run_cli(os.path.join(self.tmp.name, "no-existe"))
        self.assertEqual(code, 1)
        self.assertIn("libs.versions.toml", stderr)

    def test_version(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as exit_:
            cli.main(["--version"])
        self.assertEqual(exit_.exception.code, 0)
        self.assertIn(__version__, stdout.getvalue())


class TestEsquema(CliTestCase):
    def test_v1_por_defecto_es_el_mapa_plano(self):
        self.run_cli(self.project, "-q")
        report = self.read_output()
        self.assertNotIn("schema", report)
        gson = report["com.google.code.gson:gson"]
        self.assertEqual(gson["status_code"], "major")
        self.assertEqual(gson["channel"], "stable")
        self.assertIn("timestamp", gson)

    def test_v2(self):
        self.run_cli(self.project, "-q", "--schema", "v2", "--patch-threshold", "2")
        report = self.read_output()
        self.assertEqual(report["schema"], "toml-deps-checker/status-2")

        meta = report["meta"]
        self.assertEqual(meta["tool_version"], __version__)
        self.assertEqual(meta["channel"], "stable")
        self.assertEqual(meta["thresholds"], {"patch": 2, "calver_months": 6})
        self.assertEqual(meta["catalog"], "../proyecto/gradle/libs.versions.toml")
        self.assertIn("generated_at", meta)
        self.assertTrue(any("huerfana" in w for w in meta["warnings"]))

        gson = report["dependencies"]["com.google.code.gson:gson"]
        self.assertEqual(gson["status_code"], "major")
        self.assertNotIn("timestamp", gson)
        self.assertNotIn("channel", gson)


if __name__ == "__main__":
    unittest.main()
