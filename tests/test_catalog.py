"""Lectura del libs.versions.toml. No tocan la red."""
import os
import tempfile
import unittest

from toml_deps_checker import catalog


class TestParseCatalog(unittest.TestCase):
    CATALOGO = """
[versions]
coreKtx = "1.13.1"
guava = "31.1-jre"
agp = "8.5.0"
rica = { require = "4.12.0" }
rango = { strictly = "[1.0, 2.0[", prefer = "1.5" }
estricta = { strictly = "3.0.0", require = "2.0.0" }
solo-rango = { strictly = "[1.0, 2.0[" }

[libraries]
core-ktx = { module = "androidx.core:core-ktx", version.ref = "coreKtx" }
guava = { group = "com.google.guava", name = "guava", version.ref = "guava" }
retrofit = { module = "com.squareup.retrofit2:retrofit", version = "2.9.0" }
gson = "com.google.code.gson:gson:2.10.1"
okhttp = { module = "com.squareup.okhttp3:okhttp", version.ref = "rica" }
con-rango = { module = "com.x:rango", version.ref = "rango" }
con-estricta = { module = "com.x:estricta", version.ref = "estricta" }
con-solo-rango = { module = "com.x:solo-rango", version.ref = "solo-rango" }
compose-ui = { module = "androidx.compose.ui:ui" }
compose-bom = { module = "androidx.compose:compose-bom", version = "2025.12.00" }
rota = { module = "sin-dos-puntos" }
ref-inexistente = { module = "com.x:y", version.ref = "noExiste" }

[plugins]
android-application = { id = "com.android.application", version.ref = "agp" }
"""

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".toml", delete=False, encoding="utf-8"
        )
        handle.write(self.CATALOGO)
        handle.close()
        self.path = handle.name
        self.deps, self.warnings = catalog.parse_catalog(self.path)
        self.por_alias = {d.alias: d for d in self.deps}

    def tearDown(self):
        os.unlink(self.path)

    def test_module_con_version_ref(self):
        dep = self.por_alias["core-ktx"]
        self.assertEqual(dep.coordinate, "androidx.core:core-ktx")
        self.assertEqual(dep.version, "1.13.1")

    def test_group_y_name(self):
        dep = self.por_alias["guava"]
        self.assertEqual(dep.coordinate, "com.google.guava:guava")
        self.assertEqual(dep.version, "31.1-jre")

    def test_version_literal(self):
        self.assertEqual(self.por_alias["retrofit"].version, "2.9.0")

    def test_atajo_en_string(self):
        dep = self.por_alias["gson"]
        self.assertEqual(dep.coordinate, "com.google.code.gson:gson")
        self.assertEqual(dep.version, "2.10.1")

    def test_rich_version(self):
        self.assertEqual(self.por_alias["okhttp"].version, "4.12.0")

    def test_rich_version_con_rango_usa_prefer(self):
        self.assertEqual(self.por_alias["con-rango"].version, "1.5")

    def test_rich_version_strictly_gana_a_require(self):
        self.assertEqual(self.por_alias["con-estricta"].version, "3.0.0")

    def test_rich_version_solo_con_rango_se_queda_el_rango(self):
        self.assertEqual(self.por_alias["con-solo-rango"].version, "[1.0, 2.0[")

    def test_sin_version_la_gestiona_un_bom(self):
        self.assertIsNone(self.por_alias["compose-ui"].version)

    def test_deteccion_de_bom(self):
        self.assertTrue(self.por_alias["compose-bom"].is_bom)
        self.assertFalse(self.por_alias["core-ktx"].is_bom)

    def test_plugin_usa_el_artefacto_marcador(self):
        dep = self.por_alias["android-application"]
        self.assertEqual(dep.kind, "plugin")
        self.assertEqual(dep.artifact_id, "com.android.application.gradle.plugin")
        self.assertEqual(dep.display, "com.android.application")
        self.assertEqual(dep.version, "8.5.0")

    def test_entradas_invalidas_avisan_en_vez_de_desaparecer(self):
        self.assertNotIn("rota", self.por_alias)
        self.assertTrue(any("rota" in w for w in self.warnings))
        self.assertTrue(any("noExiste" in w for w in self.warnings))


class TestIsVersionRange(unittest.TestCase):
    def test_rangos_y_dinamicas(self):
        for value in ("[1.0, 2.0[", "[1.0,)", "(,2.0]", "]1.0, 2.0]", "1.+", "latest.release"):
            with self.subTest(value=value):
                self.assertTrue(catalog.is_version_range(value))

    def test_versiones_concretas(self):
        for value in ("1.0", "2.4.20-RC3", "31.1-jre", ""):
            with self.subTest(value=value):
                self.assertFalse(catalog.is_version_range(value))


class TestFindCatalog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "gradle"))
        self.toml = os.path.join(self.root, "gradle", "libs.versions.toml")
        with open(self.toml, "w", encoding="utf-8") as handle:
            handle.write("[libraries]\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_ruta_del_archivo(self):
        self.assertEqual(catalog.find_catalog(self.toml), self.toml)

    def test_directorio_gradle(self):
        self.assertEqual(catalog.find_catalog(os.path.join(self.root, "gradle")), self.toml)

    def test_raiz_del_proyecto(self):
        self.assertEqual(catalog.find_catalog(self.root), self.toml)

    def test_no_existe(self):
        with self.assertRaises(FileNotFoundError):
            catalog.find_catalog(os.path.join(self.root, "otro"))


if __name__ == "__main__":
    unittest.main()
