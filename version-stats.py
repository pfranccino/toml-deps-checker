#!/usr/bin/env python3
"""Verifica las versiones de un libs.versions.toml contra Maven Central y Google Maven."""
import argparse
import contextlib
import json
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import requests

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        sys.exit(
            "❌ Se necesita Python 3.11+ (tomllib) o el paquete 'tomli'.\n"
            "   Instala con: pip install tomli"
        )

# En Windows stdout usa cp1252 cuando esta redirigido a un archivo o a una pipe,
# y los emoji revientan con UnicodeEncodeError a mitad del analisis.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _stream.reconfigure(encoding="utf-8", errors="replace")

GOOGLE_MAVEN = "https://dl.google.com/android/maven2"
MAVEN_CENTRAL = "https://repo1.maven.org/maven2"
PLUGIN_PORTAL = "https://plugins.gradle.org/m2"

# Rango de estabilidad de una version: cuanto mayor, mas estable.
ALPHA, BETA, RC, STABLE = 0, 1, 2, 3

# Canal pedido por el usuario -> estabilidad minima que se acepta como "latest".
CHANNEL_MIN_RANK = {"stable": STABLE, "rc": RC, "beta": BETA, "alpha": ALPHA}

# El orden importa: "preview" se comprueba antes que "pre", "eap" antes que "ea".
_QUALIFIER_RANKS = (
    ("alpha", ALPHA),
    ("beta", BETA),
    ("milestone", BETA),
    ("preview", BETA),
    ("snapshot", ALPHA),
    ("eap", BETA),
    ("dev", ALPHA),
    ("rc", RC),
    ("cr", RC),
    ("pre", ALPHA),
    ("ea", ALPHA),
)

_NUMERIC_RE = re.compile(r"^(\d+(?:\.\d+)*)(.*)$")

# Umbrales por defecto, ajustables desde la linea de comandos.
PATCH_THRESHOLD = 5  # diferencia de patch a partir de la cual deja de ser 🟢
CALVER_MONTHS_MAJOR = 6  # meses de retraso de un BOM CalVer para marcarlo en rojo

STATUS_EMOJI = {
    "major": "🔴",
    "minor": "🟡",
    "patch": "🟡",
    "prerelease": "🟡",
    "ok": "🟢",
    "managed": "⚪",
    "unknown": "⚫",
}

# Gravedad de cada estado, para decidir el codigo de salida en CI.
# "unknown" vale 0 a proposito: que un repositorio no responda es un aviso, no
# un incumplimiento de politica, y no debe tenyir el build de rojo.
STATUS_SEVERITY = {
    "major": 3,
    "minor": 2,
    "patch": 1,
    "prerelease": 1,
    "ok": 0,
    "managed": 0,
    "unknown": 0,
}

# --fail-on <nivel>: gravedad minima que hace fallar la ejecucion.
FAIL_LEVELS = {"never": 99, "major": 3, "minor": 2, "any": 1}

_QUIET = False


def log(message: str) -> None:
    if not _QUIET:
        print(message)


# --------------------------------------------------------------------------
# Versiones
# --------------------------------------------------------------------------


def qualifier_rank(qualifier: str) -> int:
    """Clasifica el sufijo de una version segun su estabilidad.

    Los sufijos que no son pre-release cuentan como estables: guava publica
    31.1-jre y 31.1-android, y ninguno de los dos es una version de prueba.
    """
    q = qualifier.lower()
    if not q:
        return STABLE
    for keyword, rank in _QUALIFIER_RANKS:
        if q.startswith(keyword):
            return rank
    if re.match(r"^m\d", q):  # milestone: 1.0-M1
        return BETA
    return STABLE


def version_key(version: str) -> tuple[tuple[int, int, int], int, int] | None:
    """Convierte una version en una clave ordenable: (numeros, estabilidad, secuencia).

    Ordena los pre-releases por debajo de su version final, porque
    5.0.0-alpha.16 -> ((5,0,0), 0, 16) queda por debajo de 5.0.0 -> ((5,0,0), 3, 0).
    """
    raw = version.strip().lstrip("vV").split("+")[0]
    match = _NUMERIC_RE.match(raw)
    if not match:
        return None

    numbers = [int(part) for part in match.group(1).split(".")][:3]
    numbers += [0] * (3 - len(numbers))

    qualifier = match.group(2).lstrip("-_.")
    sequence = re.search(r"(\d+)", qualifier)
    return (
        (numbers[0], numbers[1], numbers[2]),
        qualifier_rank(qualifier),
        int(sequence.group(1)) if sequence else 0,
    )


def is_prerelease(version: str) -> bool:
    key = version_key(version)
    return key is not None and key[1] < STABLE


def is_calver(key: tuple[tuple[int, int, int], int, int]) -> bool:
    """Detecta versionado por fecha: compose-bom usa 2026.08.00, no semver."""
    return 2000 <= key[0][0] <= 2999


def version_flavor(version: str) -> str:
    """Sufijo estable que distingue variantes paralelas del mismo artefacto.

    Guava publica 33.7.1-jre y 33.7.1-android a la vez: no son pre-releases, son
    dos lineas distintas, y saltar de una a otra no es una actualizacion.
    """
    raw = version.strip().lstrip("vV").split("+")[0]
    match = _NUMERIC_RE.match(raw)
    if not match:
        return ""
    qualifier = match.group(2).lstrip("-_.")
    if not qualifier or qualifier_rank(qualifier) < STABLE:
        return ""
    return qualifier.lower()


def pick_latest(versions: list[str], min_rank: int, flavor: str = "") -> str | None:
    """Devuelve la version mas alta que alcance al menos `min_rank` de estabilidad.

    Se restringe al mismo flavor que la version en uso cuando existe alguno.
    """
    candidates = [v for v in versions if version_flavor(v) == flavor]
    if not candidates:
        candidates = versions

    best_key = None
    best_version = None
    for version in candidates:
        key = version_key(version)
        if key is None or key[1] < min_rank:
            continue
        if best_key is None or key > best_key:
            best_key, best_version = key, version
    return best_version


def compare_versions(
    current: str,
    latest: str | None,
    patch_threshold: int = PATCH_THRESHOLD,
    calver_months_major: int = CALVER_MONTHS_MAJOR,
) -> str:
    """Codigo de estado comparando la version en uso con la ultima disponible.

    La comparacion es lexicografica sobre la clave completa: comparar cada
    componente por separado marca 2.0.0 como desactualizado frente a 1.9.0,
    porque el minor 9 > 0 dispara sin saber que el major ya decidio.
    """
    if not current or not latest:
        return "unknown"

    current_key = version_key(current)
    latest_key = version_key(latest)
    if current_key is None or latest_key is None:
        return "unknown"

    if latest_key <= current_key:
        return "ok"

    current_nums, latest_nums = current_key[0], latest_key[0]

    # CalVer: major/minor/patch no significan nada. Un salto de anyo es una
    # release rutinaria, asi que se mide la distancia real en meses.
    if is_calver(current_key) and is_calver(latest_key):
        months = (latest_nums[0] - current_nums[0]) * 12 + (latest_nums[1] - current_nums[1])
        if months >= calver_months_major:
            return "major"
        if months >= 1:
            return "minor"
        return "ok"

    if latest_nums[0] > current_nums[0]:
        return "major"
    if latest_nums[1] > current_nums[1]:
        return "minor"
    if latest_nums[2] > current_nums[2]:
        return "patch" if latest_nums[2] - current_nums[2] > patch_threshold else "ok"

    # Mismos numeros: la diferencia esta en el canal (estas en un pre-release
    # y ya salio la version final) o en la secuencia del pre-release.
    return "prerelease"


# --------------------------------------------------------------------------
# Catalogo de versiones (libs.versions.toml)
# --------------------------------------------------------------------------


class Dependency:
    """Una entrada del catalogo, ya resuelta a coordenadas Maven."""

    def __init__(self, alias, group_id, artifact_id, version, kind="library"):
        self.alias = alias
        self.group_id = group_id
        self.artifact_id = artifact_id
        self.version = version  # None si la gestiona un BOM
        self.kind = kind
        self.managed_by: str | None = None

    @property
    def coordinate(self) -> str:
        return f"{self.group_id}:{self.artifact_id}"

    @property
    def display(self) -> str:
        """Nombre para mostrar e indexar.

        Un plugin se publica como <id>:<id>.gradle.plugin, que repite el id dos
        veces; se muestra solo el id, que es lo que aparece en el catalogo.
        """
        return self.group_id if self.kind == "plugin" else self.coordinate

    @property
    def is_bom(self) -> bool:
        return self.artifact_id == "bom" or self.artifact_id.endswith("-bom")


def _plain_version(raw: Any) -> str | None:
    """Extrae el texto de una version, admitiendo las 'rich versions' de Gradle."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for field in ("require", "strictly", "prefer"):
            if isinstance(raw.get(field), str):
                return raw[field]
    return None


def _resolve_version(raw: Any, versions: dict[str, Any], warnings: list[str], alias: str):
    """Resuelve el campo `version` de una entrada, siguiendo version.ref si hace falta."""
    if raw is None:
        return None
    if isinstance(raw, dict) and "ref" in raw:
        ref = raw["ref"]
        if ref not in versions:
            warnings.append(f"{alias}: la referencia de version '{ref}' no existe en [versions]")
            return None
        resolved = _plain_version(versions[ref])
        if resolved is None:
            warnings.append(f"{alias}: no se pudo leer la version de la referencia '{ref}'")
        return resolved
    return _plain_version(raw)


def parse_catalog(file_path: str) -> tuple[list[Dependency], list[str]]:
    """Lee el catalogo completo con tomllib.

    Cubre las formas que admite Gradle: module, group/name, atajo en string,
    version literal, version.ref, rich versions y la seccion [plugins].
    """
    warnings: list[str] = []
    with open(file_path, "rb") as handle:
        data = tomllib.load(handle)

    versions = data.get("versions", {})
    deps: list[Dependency] = []

    for alias, entry in data.get("libraries", {}).items():
        group_id = artifact_id = None
        version = None

        if isinstance(entry, str):
            # Atajo: "com.google.code.gson:gson:2.11.0"
            parts = entry.split(":")
            if len(parts) == 3:
                group_id, artifact_id, version = parts
            elif len(parts) == 2:
                group_id, artifact_id = parts
            else:
                warnings.append(f"{alias}: no se entiende el atajo '{entry}'")
                continue
        elif isinstance(entry, dict):
            module = entry.get("module")
            if isinstance(module, str) and ":" in module:
                group_id, artifact_id = module.split(":", 1)
            else:
                group_id = entry.get("group")
                artifact_id = entry.get("name")
            version = _resolve_version(entry.get("version"), versions, warnings, alias)
        else:
            warnings.append(f"{alias}: formato de entrada no reconocido")
            continue

        if not group_id or not artifact_id:
            warnings.append(f"{alias}: faltan las coordenadas (module o group/name)")
            continue

        deps.append(Dependency(alias, group_id, artifact_id, version))

    for alias, entry in data.get("plugins", {}).items():
        if isinstance(entry, str):
            parts = entry.split(":")
            plugin_id, version = (parts[0], parts[1]) if len(parts) == 2 else (parts[0], None)
        elif isinstance(entry, dict):
            plugin_id = entry.get("id")
            version = _resolve_version(entry.get("version"), versions, warnings, alias)
        else:
            warnings.append(f"{alias}: formato de plugin no reconocido")
            continue

        if not plugin_id:
            warnings.append(f"{alias}: al plugin le falta el 'id'")
            continue

        # Gradle publica cada plugin como un artefacto marcador.
        deps.append(
            Dependency(alias, plugin_id, f"{plugin_id}.gradle.plugin", version, kind="plugin")
        )

    return deps, warnings


# --------------------------------------------------------------------------
# Consultas a los repositorios
# --------------------------------------------------------------------------


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_google_dependency(group_id: str) -> bool:
    google_groups = ("com.google.", "androidx.", "android.arch.", "com.android.")
    return group_id.startswith(google_groups)


class MavenRepository:
    """Acceso a los repositorios: listados de versiones y POMs de BOM."""

    def __init__(self, timeout: int = 15, retries: int = 3, jobs: int = 8):
        self.timeout = timeout
        self.retries = retries
        self.jobs = max(1, jobs)
        self._versions_cache: dict[str, list[str] | None] = {}
        self._bom_cache: dict[str, dict[str, str]] = {}
        # requests.Session no esta pensada para compartirse entre hilos, asi que
        # cada hilo del pool usa la suya y aprovecha su propio connection pool.
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def repos_for(self, dep: Dependency) -> list[str]:
        if dep.kind == "plugin":
            # com.android.* vive en Google; el resto en el portal de Gradle.
            if is_google_dependency(dep.group_id):
                return [GOOGLE_MAVEN, PLUGIN_PORTAL, MAVEN_CENTRAL]
            return [PLUGIN_PORTAL, MAVEN_CENTRAL, GOOGLE_MAVEN]
        if is_google_dependency(dep.group_id):
            return [GOOGLE_MAVEN, MAVEN_CENTRAL]
        return [MAVEN_CENTRAL]

    def _get(self, url: str) -> bytes | None:
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                log(f"⚠️ Intento {attempt}/{self.retries} fallo: {exc}")
                if attempt < self.retries:
                    time.sleep(attempt)
                continue

            if response.status_code == 200:
                return response.content
            if response.status_code == 404:
                return None
            if response.status_code == 429:
                log(f"⏳ Rate limit, reintentando ({attempt}/{self.retries})")
                time.sleep(attempt * 2)
                continue
            log(f"❌ Respuesta {response.status_code}: {url}")
            return None
        return None

    def versions_for(self, dep: Dependency) -> list[str] | None:
        """Lee el maven-metadata.xml del primer repositorio que lo tenga.

        Se usa el listado completo <versions> en vez de <release>/<latest>: ninguno
        de los dos significa "estable" (el <release> de AndroidX suele ser un alpha,
        porque un alpha no es un SNAPSHOT y por tanto califica como release).
        """
        if dep.coordinate not in self._versions_cache:
            self._versions_cache[dep.coordinate] = self._fetch_versions(dep)
        return self._versions_cache[dep.coordinate]

    def prefetch(self, deps: list[Dependency]) -> None:
        """Descarga en paralelo los metadatos de todo lo que aun no este en cache.

        El pool solo devuelve resultados; el cache se rellena desde el hilo
        principal, asi no hace falta sincronizarlo.
        """
        pendientes: dict[str, Dependency] = {}
        for dep in deps:
            if dep.version and dep.coordinate not in self._versions_cache:
                pendientes.setdefault(dep.coordinate, dep)
        if not pendientes:
            return

        log(f"\n🌐 Consultando {len(pendientes)} artefactos ({self.jobs} en paralelo)...")
        objetivos = list(pendientes.values())
        with ThreadPoolExecutor(max_workers=self.jobs) as pool:
            resultados = pool.map(self._fetch_versions, objetivos)
            for dep, versions in zip(objetivos, resultados, strict=True):
                self._versions_cache[dep.coordinate] = versions

    def _fetch_versions(self, dep: Dependency) -> list[str] | None:
        path = dep.group_id.replace(".", "/")
        found = None
        for base in self.repos_for(dep):
            url = f"{base}/{path}/{dep.artifact_id}/maven-metadata.xml"
            log(f"🔍 Consultando: {url}")
            raw = self._get(url)
            if not raw:
                continue
            try:
                root = ET.fromstring(raw)
            except ET.ParseError as exc:
                log(f"❌ maven-metadata.xml invalido: {exc}")
                continue
            versions = [e.text for e in root.findall("versioning/versions/version") if e.text]
            if versions:
                log(f"✅ {len(versions)} versiones encontradas")
                found = versions
                break

        return found

    def bom_managed(self, dep: Dependency, version: str) -> dict[str, str]:
        """Lee el <dependencyManagement> del POM de un BOM: modulo -> version."""
        cache_key = f"{dep.coordinate}:{version}"
        if cache_key in self._bom_cache:
            return self._bom_cache[cache_key]

        path = dep.group_id.replace(".", "/")
        managed: dict[str, str] = {}
        for base in self.repos_for(dep):
            url = f"{base}/{path}/{dep.artifact_id}/{version}/{dep.artifact_id}-{version}.pom"
            log(f"🔍 Leyendo BOM: {url}")
            raw = self._get(url)
            if not raw:
                continue
            try:
                root = ET.fromstring(raw)
            except ET.ParseError as exc:
                log(f"❌ POM invalido: {exc}")
                continue

            properties: dict[str, str] = {}
            for node in root:
                if _localname(node.tag) == "properties":
                    for prop in node:
                        properties[_localname(prop.tag)] = (prop.text or "").strip()

            for node in root.iter():
                if _localname(node.tag) != "dependency":
                    continue
                fields = {_localname(c.tag): (c.text or "").strip() for c in node}
                group = fields.get("groupId")
                artifact = fields.get("artifactId")
                managed_version = fields.get("version")
                if not (group and artifact and managed_version):
                    continue
                # Resolver ${propiedad} cuando el BOM la usa.
                if managed_version.startswith("${") and managed_version.endswith("}"):
                    managed_version = properties.get(managed_version[2:-1], "")
                    if not managed_version:
                        continue
                managed[f"{group}:{artifact}"] = managed_version

            if managed:
                log(f"✅ El BOM gestiona {len(managed)} modulos")
                break

        self._bom_cache[cache_key] = managed
        return managed


# --------------------------------------------------------------------------
# Analisis del catalogo
# --------------------------------------------------------------------------


class MavenVersionChecker:
    """Recorre el catalogo y produce el informe, apoyandose en un MavenRepository."""

    def __init__(
        self,
        repository: MavenRepository,
        channel: str = "stable",
        patch_threshold: int = PATCH_THRESHOLD,
        calver_months_major: int = CALVER_MONTHS_MAJOR,
    ):
        self.repo = repository
        self.channel = channel
        self.min_rank = CHANNEL_MIN_RANK[channel]
        self.patch_threshold = patch_threshold
        self.calver_months_major = calver_months_major
        log(f"Iniciando MavenVersionChecker (canal: {channel}, {repository.jobs} hilos)...")

    def resolve_versions(self, dep: Dependency) -> dict[str, str | None]:
        """Calcula la ultima del canal pedido, la ultima estable y el ultimo pre-release."""
        versions = self.repo.versions_for(dep)
        if not versions:
            return {"latest": None, "latest_stable": None, "latest_prerelease": None}

        flavor = version_flavor(dep.version or "")
        latest_stable = pick_latest(versions, STABLE, flavor)
        latest_any = pick_latest(versions, ALPHA, flavor)

        # Solo interesa el pre-release si va por delante de la estable.
        latest_prerelease = None
        if latest_any and is_prerelease(latest_any):
            stable_key = version_key(latest_stable) if latest_stable else None
            if stable_key is None or version_key(latest_any) > stable_key:
                latest_prerelease = latest_any

        return {
            "latest": pick_latest(versions, self.min_rank, flavor),
            "latest_stable": latest_stable,
            "latest_prerelease": latest_prerelease,
        }

    def process_toml_file(self, folder_path: str) -> tuple[dict[str, Any], list[str]]:
        file_path = os.path.join(folder_path, "libs.versions.toml")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"No se encontro libs.versions.toml en {folder_path}")

        log(f"\n📂 Procesando: {file_path}")
        deps, warnings = parse_catalog(file_path)
        log(f"📖 {len(deps)} entradas leidas del catalogo")

        timestamp = datetime.now().isoformat()
        result: dict[str, Any] = {}

        # 1) Los BOM primero: hacen falta para resolver las que no llevan version.
        boms = [d for d in deps if d.is_bom and d.version]
        managed_index: dict[str, tuple[Dependency, str]] = {}
        for bom in boms:
            for coordinate, version in self.repo.bom_managed(bom, bom.version).items():
                managed_index.setdefault(coordinate, (bom, version))

        # 2) Atribuir su version efectiva a las que dependen de un BOM.
        for dep in deps:
            if dep.version or dep.coordinate not in managed_index:
                continue
            bom, effective = managed_index[dep.coordinate]
            dep.version = effective
            dep.managed_by = f"{bom.artifact_id} {bom.version}"

        # 3) Descargar los metadatos en paralelo antes de comparar nada.
        self.repo.prefetch([d for d in deps if not d.managed_by])

        # 4) Comprobar cada entrada.
        for dep in deps:
            log(f"\n📦 Procesando: {dep.coordinate}")

            if dep.managed_by:
                # No lleva veredicto propio: no se puede subir por separado, se
                # sube el BOM. El BOM es la linea sobre la que se puede actuar.
                result[dep.display] = self._entry(
                    dep, timestamp, "managed",
                    {"latest": None, "latest_stable": None, "latest_prerelease": None},
                )
                continue

            if not dep.version:
                warnings.append(f"{dep.alias}: sin version y ningun BOM del catalogo la gestiona")
                result[dep.display] = self._entry(
                    dep, timestamp, "unknown",
                    {"latest": None, "latest_stable": None, "latest_prerelease": None},
                )
                continue

            resolved = self.resolve_versions(dep)
            status = compare_versions(
                dep.version,
                resolved["latest"],
                self.patch_threshold,
                self.calver_months_major,
            )
            entry = self._entry(dep, timestamp, status, resolved)

            # Para un BOM desactualizado, decir que traeria subirlo.
            if dep.is_bom and status not in ("ok", "unknown") and resolved["latest"]:
                entry["managed_changes"] = self._bom_diff(dep, resolved["latest"], deps)

            result[dep.display] = entry

        log(f"\n✅ Completado. Dependencias analizadas: {len(result)}")
        return result, warnings

    def _bom_diff(self, bom: Dependency, new_version: str, deps: list[Dependency]) -> dict[str, Any]:
        """Que versiones cambiarian en las dependencias del catalogo al subir el BOM."""
        actual = self.repo.bom_managed(bom, bom.version)
        nueva = self.repo.bom_managed(bom, new_version)
        usados = {d.coordinate for d in deps if d.managed_by and d.managed_by.startswith(bom.artifact_id)}

        cambios = {}
        for coordinate in sorted(usados):
            antes = actual.get(coordinate)
            despues = nueva.get(coordinate)
            if antes and despues and antes != despues:
                cambios[coordinate] = {"from": antes, "to": despues}
        return cambios

    def _entry(self, dep, timestamp, status, resolved) -> dict[str, Any]:
        if dep.kind == "plugin":
            url = f"https://plugins.gradle.org/plugin/{dep.group_id}"
            dep_type = "plugin"
        elif is_google_dependency(dep.group_id):
            url = f"https://maven.google.com/web/index.html#{dep.group_id}"
            dep_type = "google"
        else:
            url = f"https://central.sonatype.com/artifact/{dep.group_id}/{dep.artifact_id}"
            dep_type = "maven"

        entry = {
            "url": url,
            "alias": dep.alias,
            "version_used": dep.version or "N/A",
            "latest_version": resolved["latest"] or "N/A",
            "latest_stable": resolved["latest_stable"] or "N/A",
            "latest_prerelease": resolved["latest_prerelease"] or "N/A",
            "channel": self.channel,
            "timestamp": timestamp,
            "status": STATUS_EMOJI[status],
            "status_code": status,
            "type": dep_type,
        }
        if dep.managed_by:
            entry["managed_by"] = dep.managed_by
        if dep.is_bom:
            entry["is_bom"] = True
        return entry


# --------------------------------------------------------------------------
# Salida
# --------------------------------------------------------------------------


def policy_violations(result: dict[str, Any], fail_on: str) -> list[str]:
    """Dependencias que incumplen la politica de --fail-on, de peor a mejor.

    Las que salen en ⚫ nunca cuentan: que un repositorio no responda es un
    aviso, no un incumplimiento, y no debe hacer fallar el build.
    """
    if fail_on == "never":
        return []
    umbral = FAIL_LEVELS[fail_on]
    incumplen = [
        (STATUS_SEVERITY[info["status_code"]], nombre)
        for nombre, info in result.items()
        if STATUS_SEVERITY[info["status_code"]] >= umbral
    ]
    return [nombre for _, nombre in sorted(incumplen, key=lambda x: (-x[0], x[1]))]


def print_summary(result: dict[str, Any], warnings: list[str]) -> None:
    if not result:
        return

    name_width = min(52, max(len(dep) for dep in result)) + 2
    used_width = max(len(i["version_used"]) for i in result.values()) + 2
    total_width = name_width + used_width + 22

    print("\n" + "=" * total_width)
    print(f"{'':3}{'DEPENDENCIA':<{name_width}}{'USADA':<{used_width}}{'ULTIMA'}")
    print("-" * total_width)

    for dep, info in sorted(result.items()):
        name = dep if len(dep) <= name_width else dep[: name_width - 1] + "…"
        ultima = info["latest_version"]
        if info["status_code"] == "managed":
            ultima = f"(vía {info['managed_by']})"
        print(f"{info['status']} {name:<{name_width}}{info['version_used']:<{used_width}}{ultima}")

        if info["latest_prerelease"] != "N/A" and info["status_code"] != "managed":
            print(f"   └─ pre-release disponible: {info['latest_prerelease']}")

        for coordinate, cambio in info.get("managed_changes", {}).items():
            print(f"   └─ al subir: {coordinate} {cambio['from']} → {cambio['to']}")

    print("-" * total_width)

    counts: dict[str, int] = {}
    for info in result.values():
        counts[info["status_code"]] = counts.get(info["status_code"], 0) + 1
    resumen = "  ".join(
        f"{STATUS_EMOJI[code]} {counts[code]}" for code in STATUS_EMOJI if code in counts
    )
    print(f"Total: {len(result)}   {resumen}")

    if warnings:
        print(f"\n⚠️ {len(warnings)} entradas no se pudieron analizar:")
        for warning in warnings:
            print(f"   - {warning}")


def main() -> int:
    global _QUIET

    parser = argparse.ArgumentParser(
        description="Compara las dependencias de un libs.versions.toml con Maven Central y Google Maven."
    )
    parser.add_argument("folder", help="Directorio que contiene libs.versions.toml")
    parser.add_argument(
        "--channel",
        choices=("stable", "rc", "beta", "alpha"),
        default="stable",
        help="Canal contra el que comparar (por defecto: stable). "
             "'beta' incluye rc y estables; 'alpha' incluye todo.",
    )
    parser.add_argument(
        "--include-prereleases", action="store_true", help="Atajo para --channel alpha"
    )
    parser.add_argument("-o", "--output", help="Ruta del JSON de salida")
    parser.add_argument("-q", "--quiet", action="store_true", help="Silencia el log de progreso")
    parser.add_argument("--timeout", type=int, default=15, help="Timeout por peticion en segundos")
    parser.add_argument(
        "-j", "--jobs", type=int, default=8, help="Peticiones en paralelo (por defecto: 8)"
    )
    parser.add_argument(
        "--fail-on",
        choices=tuple(FAIL_LEVELS),
        default="never",
        help="Sale con código 1 si alguna dependencia llega a este nivel. "
             "'major' solo 🔴; 'minor' añade los minor; 'any' cualquier desactualización. "
             "Las ⚫ nunca hacen fallar (por defecto: never).",
    )
    parser.add_argument(
        "--patch-threshold",
        type=int,
        default=PATCH_THRESHOLD,
        help=f"Diferencia de patch a partir de la cual deja de considerarse al día "
             f"(por defecto: {PATCH_THRESHOLD})",
    )
    parser.add_argument(
        "--calver-months",
        type=int,
        default=CALVER_MONTHS_MAJOR,
        help=f"Meses de retraso de un BOM con versionado por fecha para marcarlo en rojo "
             f"(por defecto: {CALVER_MONTHS_MAJOR})",
    )
    args = parser.parse_args()

    _QUIET = args.quiet
    channel = "alpha" if args.include_prereleases else args.channel

    log("\n🚀 Iniciando verificador de versiones Maven")

    repository = MavenRepository(timeout=args.timeout, jobs=args.jobs)
    checker = MavenVersionChecker(
        repository,
        channel=channel,
        patch_threshold=args.patch_threshold,
        calver_months_major=args.calver_months,
    )
    try:
        result, warnings = checker.process_toml_file(args.folder)
    except FileNotFoundError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    except tomllib.TOMLDecodeError as exc:
        print(f"❌ El libs.versions.toml no es válido: {exc}", file=sys.stderr)
        return 1

    if not result:
        print("❌ No se pudo analizar ninguna dependencia", file=sys.stderr)
        return 1

    output_file = args.output or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dependency_status.json"
    )
    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)

    print_summary(result, warnings)
    print(f"\n💾 Resultados guardados en: {output_file}")

    sin_resolver = [n for n, i in result.items() if i["status_code"] == "unknown"]
    if sin_resolver and args.fail_on != "never":
        # No cuentan para el código de salida, pero no pueden pasar en silencio:
        # un repositorio caído deja huecos en el análisis, no un visto bueno.
        print(
            f"\n⚫ {len(sin_resolver)} sin verificar (no afectan al código de salida): "
            + ", ".join(sin_resolver)
        )

    incumplen = policy_violations(result, args.fail_on)
    if incumplen:
        print(f"\n❌ --fail-on {args.fail_on}: {len(incumplen)} dependencias incumplen la política")
        for nombre in incumplen:
            print(f"   {result[nombre]['status']} {nombre} "
                  f"{result[nombre]['version_used']} → {result[nombre]['latest_version']}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
