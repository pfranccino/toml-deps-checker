"""Lectura de BOM contra un repositorio en memoria."""
import os
import tempfile
import unittest

from fakes import FakeRepository, metadata, pom, pom_path

from toml_deps_checker.catalog import Dependency
from toml_deps_checker.checker import MavenVersionChecker
from toml_deps_checker.maven import interpolate

BOM = Dependency("bom", "com.acme", "acme-bom", "1.0.0")


def managed(group, artifact, version, **extra):
    return {"groupId": group, "artifactId": artifact, "version": version, **extra}


class TestInterpolate(unittest.TestCase):
    def test_anidada_y_dentro_de_texto(self):
        props = {"a": "${b}", "b": "1.2"}
        self.assertEqual(interpolate("${a}-jre", props), "1.2-jre")

    def test_no_resuelta(self):
        self.assertIsNone(interpolate("${falta}", {}))

    def test_ciclo(self):
        self.assertIsNone(interpolate("${a}", {"a": "${b}", "b": "${a}"}))


class TestBomManaged(unittest.TestCase):
    def bom_managed(self, files, dep=BOM):
        return FakeRepository(files).bom_managed(dep, dep.version)

    def test_versiones_literales(self):
        files = {pom_path("com.acme", "acme-bom", "1.0.0"): pom(
            "com.acme", "acme-bom", "1.0.0", managed=[managed("com.acme", "core", "1.4.0")]
        )}
        self.assertEqual(self.bom_managed(files), {"com.acme:core": "1.4.0"})

    def test_project_version(self):
        files = {pom_path("com.acme", "acme-bom", "1.0.0"): pom(
            "com.acme", "acme-bom", "1.0.0",
            managed=[managed("${project.groupId}", "core", "${project.version}")],
        )}
        self.assertEqual(self.bom_managed(files), {"com.acme:core": "1.0.0"})

    def test_version_y_grupo_heredados_del_parent(self):
        files = {
            pom_path("com.acme", "acme-bom", "1.0.0"): pom(
                "", "acme-bom", None, parent=("com.acme", "acme-parent", "1.0.0"),
                managed=[managed("com.acme", "core", "${project.version}")],
            ),
            pom_path("com.acme", "acme-parent", "1.0.0"): pom("com.acme", "acme-parent", "1.0.0"),
        }
        self.assertEqual(self.bom_managed(files), {"com.acme:core": "1.0.0"})

    def test_propiedades_del_parent(self):
        files = {
            pom_path("com.acme", "acme-bom", "1.0.0"): pom(
                "com.acme", "acme-bom", "1.0.0", parent=("com.acme", "acme-parent", "7"),
                properties={"okio.version": "3.9.0"},
                managed=[
                    managed("com.acme", "core", "${core.version}"),
                    managed("com.squareup.okio", "okio", "${okio.version}"),
                ],
            ),
            pom_path("com.acme", "acme-parent", "7"): pom(
                "com.acme", "acme-parent", "7",
                properties={"core.version": "2.1.0", "okio.version": "1.0.0"},
            ),
        }
        # La del hijo pisa a la del parent.
        self.assertEqual(
            self.bom_managed(files),
            {"com.acme:core": "2.1.0", "com.squareup.okio:okio": "3.9.0"},
        )

    def test_bom_importado(self):
        files = {
            pom_path("com.acme", "acme-bom", "1.0.0"): pom(
                "com.acme", "acme-bom", "1.0.0",
                managed=[
                    managed("com.acme", "core", "1.0.0"),
                    managed("org.other", "other-bom", "3.0", scope="import", type="pom"),
                ],
            ),
            pom_path("org.other", "other-bom", "3.0"): pom(
                "org.other", "other-bom", "3.0",
                managed=[
                    managed("org.other", "lib", "${project.version}"),
                    managed("com.acme", "core", "9.9.9"),
                ],
            ),
        }
        # Lo declarado directamente gana a lo importado.
        self.assertEqual(
            self.bom_managed(files), {"com.acme:core": "1.0.0", "org.other:lib": "3.0"}
        )

    def test_ignora_dependencies_fuera_de_dependency_management(self):
        raw = pom("com.acme", "acme-bom", "1.0.0", managed=[managed("com.acme", "core", "1.0")])
        raw = raw.replace("</project>", "<dependencies><dependency><groupId>x</groupId>"
                          "<artifactId>y</artifactId><version>1</version></dependency>"
                          "</dependencies></project>")
        self.assertEqual(
            self.bom_managed({pom_path("com.acme", "acme-bom", "1.0.0"): raw}),
            {"com.acme:core": "1.0"},
        )

    def test_no_se_pudo_leer(self):
        self.assertIsNone(self.bom_managed({}))

    def test_propiedad_sin_resolver_no_es_lo_mismo_que_vacio(self):
        files = {pom_path("com.acme", "acme-bom", "1.0.0"): pom(
            "com.acme", "acme-bom", "1.0.0", managed=[managed("com.acme", "core", "${falta}")]
        )}
        self.assertIsNone(self.bom_managed(files))


class TestAvisosDeBom(unittest.TestCase):
    CATALOGO = """
[libraries]
acme-bom = { module = "com.acme:acme-bom", version = "1.0.0" }
acme-core = { module = "com.acme:core" }
"""

    def analizar(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "libs.versions.toml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.CATALOGO)
            checker = MavenVersionChecker(FakeRepository(files))
            return checker.process_toml_file(tmp)

    def test_bom_ilegible_no_dice_que_ningun_bom_la_gestiona(self):
        result, warnings = self.analizar({})
        self.assertTrue(any("no se pudo leer el BOM com.acme:acme-bom:1.0.0" in w for w in warnings))
        self.assertFalse(any("ningun BOM" in w for w in warnings))
        self.assertTrue(any(w.startswith("acme-core:") and "acme-bom" in w for w in warnings))
        self.assertEqual(result["com.acme:core"]["status_code"], "unknown")

    def test_bom_con_project_version_gestiona_la_dependencia(self):
        files = {
            pom_path("com.acme", "acme-bom", "1.0.0"): pom(
                "com.acme", "acme-bom", "1.0.0",
                managed=[managed("com.acme", "core", "${project.version}")],
            ),
            "com/acme/acme-bom/maven-metadata.xml": metadata("1.0.0"),
        }
        result, warnings = self.analizar(files)
        self.assertEqual(warnings, [])
        self.assertEqual(result["com.acme:core"]["status_code"], "managed")
        self.assertEqual(result["com.acme:core"]["version_used"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
