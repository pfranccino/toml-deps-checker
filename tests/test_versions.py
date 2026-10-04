"""Orden y comparacion de versiones. No tocan la red."""
import json
import os
import unittest

from toml_deps_checker import versions as vs

_CASES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "versions_cases.json")


class TestVersionKey(unittest.TestCase):
    def test_rellena_hasta_tres_componentes(self):
        self.assertEqual(vs.version_key("1.2")[0], (1, 2, 0))
        self.assertEqual(vs.version_key("4")[0], (4, 0, 0))

    def test_ignora_prefijo_y_metadatos(self):
        self.assertEqual(vs.version_key("v1.2.3")[0], (1, 2, 3))
        self.assertEqual(vs.version_key("1.2.3+build5")[0], (1, 2, 3))

    def test_conserva_la_cuarta_posicion(self):
        self.assertEqual(vs.version_key("1.2.3.4")[0], (1, 2, 3, 4))
        self.assertEqual(vs.version_key("1.2.3.0"), vs.version_key("1.2.3"))

    def test_prerelease_ordena_por_debajo_de_su_final(self):
        self.assertLess(vs.version_key("5.0.0-alpha.16"), vs.version_key("5.0.0"))
        self.assertLess(vs.version_key("1.13.0-alpha02"), vs.version_key("1.13.0-beta01"))
        self.assertLess(vs.version_key("1.13.0-beta01"), vs.version_key("1.13.0-rc01"))
        self.assertLess(vs.version_key("1.13.0-rc01"), vs.version_key("1.13.0"))

    def test_secuencia_del_prerelease(self):
        self.assertLess(vs.version_key("1.0.0-alpha01"), vs.version_key("1.0.0-alpha02"))

    def test_version_no_numerica(self):
        self.assertIsNone(vs.version_key("RELEASE"))


class TestVectoresCompartidos(unittest.TestCase):
    """versions_cases.json lo validan tambien los demas repos de la suite."""

    @classmethod
    def setUpClass(cls):
        with open(_CASES, encoding="utf-8") as handle:
            cls.cases = json.load(handle)

    def test_ascendentes(self):
        for serie in self.cases["ascending"]:
            for lower, higher in zip(serie, serie[1:]):
                with self.subTest(lower=lower, higher=higher):
                    self.assertLess(vs.version_key(lower), vs.version_key(higher))

    def test_iguales(self):
        for grupo in self.cases["equal"]:
            for other in grupo[1:]:
                with self.subTest(first=grupo[0], other=other):
                    self.assertEqual(vs.version_key(grupo[0]), vs.version_key(other))


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


class TestCuatroPosiciones(unittest.TestCase):
    """Antes se truncaba a 3 y 1.2.3.4 -> 1.2.3.9 salia igual."""

    def test_la_cuarta_posicion_cuenta_como_patch(self):
        self.assertEqual(vs.compare_versions("1.2.3.4", "1.2.3.10"), "patch")
        self.assertEqual(vs.compare_versions("1.2.3", "1.2.3.9"), "patch")

    def test_y_respeta_el_umbral_de_patch(self):
        self.assertEqual(vs.compare_versions("1.2.3.4", "1.2.3.9"), "ok")
        self.assertEqual(vs.compare_versions("1.2.3.4", "1.2.3.9", patch_threshold=0), "patch")

    def test_mas_nueva_en_la_cuarta_es_ok(self):
        self.assertEqual(vs.compare_versions("1.2.3.9", "1.2.3.4"), "ok")
        self.assertEqual(vs.compare_versions("1.2.3.0", "1.2.3"), "ok")

    def test_las_tres_primeras_siguen_mandando(self):
        self.assertEqual(vs.compare_versions("1.2.3.9", "1.3.0"), "minor")

    def test_pick_latest_no_depende_del_orden(self):
        self.assertEqual(vs.pick_latest(["1.2.3.9", "1.2.3.10"], vs.STABLE), "1.2.3.10")
        self.assertEqual(vs.pick_latest(["1.2.3.10", "1.2.3.9"], vs.STABLE), "1.2.3.10")


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


if __name__ == "__main__":
    unittest.main()
