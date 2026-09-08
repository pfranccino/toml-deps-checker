#!/usr/bin/env python3
"""Tests de las funciones puras de version-stats.py. No tocan la red.

Ejecutar con:  python -m unittest discover -v
"""
import importlib.util
import os
import tempfile
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "version_stats", os.path.join(os.path.dirname(os.path.abspath(__file__)), "version-stats.py")
)
vs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vs)


class TestVersionKey(unittest.TestCase):
    def test_rellena_hasta_tres_componentes(self):
        self.assertEqual(vs.version_key("1.2")[0], (1, 2, 0))
        self.assertEqual(vs.version_key("4")[0], (4, 0, 0))

    def test_ignora_prefijo_y_metadatos(self):
        self.assertEqual(vs.version_key("v1.2.3")[0], (1, 2, 3))
        self.assertEqual(vs.version_key("1.2.3+build5")[0], (1, 2, 3))

    def test_prerelease_ordena_por_debajo_de_su_final(self):
        self.assertLess(vs.version_key("5.0.0-alpha.16"), vs.version_key("5.0.0"))
        self.assertLess(vs.version_key("1.13.0-alpha02"), vs.version_key("1.13.0-beta01"))
        self.assertLess(vs.version_key("1.13.0-beta01"), vs.version_key("1.13.0-rc01"))
        self.assertLess(vs.version_key("1.13.0-rc01"), vs.version_key("1.13.0"))

    def test_secuencia_del_prerelease(self):
        self.assertLess(vs.version_key("1.0.0-alpha01"), vs.version_key("1.0.0-alpha02"))

    def test_version_no_numerica(self):
        self.assertIsNone(vs.version_key("RELEASE"))


class TestQualifierRank(unittest.TestCase):
    def test_estables(self):
        self.assertEqual(vs.qualifier_rank(""), vs.STABLE)
        # Sufijos que no son pre-release: variantes de guava
        self.assertEqual(vs.qualifier_rank("jre"), vs.STABLE)
        self.assertEqual(vs.qualifier_rank("android"), vs.STABLE)

    def test_prereleases(self):
        self.assertEqual(vs.qualifier_rank("alpha02"), vs.ALPHA)
        self.assertEqual(vs.qualifier_rank("Beta1"), vs.BETA)
        self.assertEqual(vs.qualifier_rank("RC3"), vs.RC)
        self.assertEqual(vs.qualifier_rank("SNAPSHOT"), vs.ALPHA)
        self.assertEqual(vs.qualifier_rank("M1"), vs.BETA)

    def test_preview_no_se_confunde_con_pre(self):
        self.assertEqual(vs.qualifier_rank("preview01"), vs.BETA)


class TestCompareVersions(unittest.TestCase):
    def test_version_en_uso_mas_nueva_que_latest(self):
        # El bug original: comparar componente a componente marcaba estos en amarillo
        # porque el minor o el patch de latest superaba al actual.
        self.assertEqual(vs.compare_versions("2.0.0", "1.9.0"), "ok")
        self.assertEqual(vs.compare_versions("2.1.0", "1.9.3"), "ok")
        self.assertEqual(vs.compare_versions("1.2.5", "1.1.20"), "ok")
        self.assertEqual(vs.compare_versions("3.0.0", "2.11.0"), "ok")

    def test_actualizaciones_reales(self):
        self.assertEqual(vs.compare_versions("1.9.0", "2.0.0"), "major")
        self.assertEqual(vs.compare_versions("1.2.3", "1.3.0"), "minor")
        self.assertEqual(vs.compare_versions("1.2.3", "1.2.10"), "patch")

    def test_diferencia_de_patch_pequena_es_ok(self):
        self.assertEqual(vs.compare_versions("1.2.3", "1.2.5"), "ok")

    def test_prerelease_con_estable_publicada(self):
        self.assertEqual(vs.compare_versions("5.0.0-alpha.16", "5.0.0"), "prerelease")
        self.assertEqual(vs.compare_versions("2.4.20-RC3", "2.4.20"), "prerelease")

    def test_sin_latest(self):
        self.assertEqual(vs.compare_versions("1.0.0", None), "unknown")
        self.assertEqual(vs.compare_versions("1.0.0", "no-es-una-version"), "unknown")


class TestCalVer(unittest.TestCase):
    def test_deteccion(self):
        self.assertTrue(vs.is_calver(vs.version_key("2026.08.00")))
        self.assertFalse(vs.is_calver(vs.version_key("33.7.1")))

    def test_salto_de_anyo_no_es_major(self):
        # Antes daba "major" solo porque cambiaba el digito del anyo.
        self.assertEqual(vs.compare_versions("2025.12.00", "2026.01.00"), "minor")

    def test_distancia_grande_si_es_major(self):
        self.assertEqual(vs.compare_versions("2025.12.00", "2026.08.00"), "major")

    def test_mismo_mes(self):
        self.assertEqual(vs.compare_versions("2026.06.00", "2026.06.01"), "ok")
        self.assertEqual(vs.compare_versions("2026.08.00", "2026.08.00"), "ok")


class TestUmbralesConfigurables(unittest.TestCase):
    def test_patch_threshold_por_defecto(self):
        self.assertEqual(vs.compare_versions("1.2.3", "1.2.8"), "ok")
        self.assertEqual(vs.compare_versions("1.2.3", "1.2.9"), "patch")

    def test_patch_threshold_estricto(self):
        self.assertEqual(vs.compare_versions("1.2.3", "1.2.4", patch_threshold=0), "patch")

    def test_patch_threshold_laxo(self):
        self.assertEqual(vs.compare_versions("1.2.3", "1.2.99", patch_threshold=100), "ok")

    def test_calver_months_configurable(self):
        # 3 meses de retraso: minor con el umbral por defecto (6), major si se baja a 3.
        self.assertEqual(vs.compare_versions("2026.01.00", "2026.04.00"), "minor")
        self.assertEqual(
            vs.compare_versions("2026.01.00", "2026.04.00", calver_months_major=3), "major"
        )


class TestFlavors(unittest.TestCase):
    VERSIONES = ["31.1-jre", "31.1-android", "33.7.1-jre", "33.7.1-android"]

    def test_deteccion_de_flavor(self):
        self.assertEqual(vs.version_flavor("31.1-jre"), "jre")
        self.assertEqual(vs.version_flavor("1.2.3"), "")
        self.assertEqual(vs.version_flavor("1.0.0-alpha01"), "")

    def test_no_cruza_de_variante(self):
        self.assertEqual(vs.pick_latest(self.VERSIONES, vs.STABLE, "jre"), "33.7.1-jre")
        self.assertEqual(vs.pick_latest(self.VERSIONES, vs.STABLE, "android"), "33.7.1-android")

    def test_sin_coincidencia_usa_todas(self):
        self.assertIsNotNone(vs.pick_latest(self.VERSIONES, vs.STABLE, "inexistente"))


class TestPickLatest(unittest.TestCase):
    VERSIONES = ["1.0.0", "1.1.0-alpha01", "1.1.0-beta01", "1.1.0-rc01", "1.1.0", "1.2.0-alpha01"]

    def test_canal_stable_ignora_prereleases(self):
        self.assertEqual(vs.pick_latest(self.VERSIONES, vs.STABLE), "1.1.0")

    def test_canal_alpha_incluye_todo(self):
        self.assertEqual(vs.pick_latest(self.VERSIONES, vs.ALPHA), "1.2.0-alpha01")

    def test_canal_rc_excluye_alpha_y_beta(self):
        self.assertEqual(vs.pick_latest(self.VERSIONES, vs.RC), "1.1.0")

    def test_lista_vacia(self):
        self.assertIsNone(vs.pick_latest([], vs.STABLE))


class TestParseCatalog(unittest.TestCase):
    CATALOGO = """
[versions]
coreKtx = "1.13.1"
guava = "31.1-jre"
agp = "8.5.0"
rica = { require = "4.12.0" }

[libraries]
core-ktx = { module = "androidx.core:core-ktx", version.ref = "coreKtx" }
guava = { group = "com.google.guava", name = "guava", version.ref = "guava" }
retrofit = { module = "com.squareup.retrofit2:retrofit", version = "2.9.0" }
gson = "com.google.code.gson:gson:2.10.1"
okhttp = { module = "com.squareup.okhttp3:okhttp", version.ref = "rica" }
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
        self.deps, self.warnings = vs.parse_catalog(self.path)
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


if __name__ == "__main__":
    unittest.main()
