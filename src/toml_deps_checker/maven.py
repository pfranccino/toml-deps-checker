"""Acceso a los repositorios Maven: listados de versiones y POMs de BOM."""
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

from .catalog import Dependency
from .progress import log

GOOGLE_MAVEN = "https://dl.google.com/android/maven2"
MAVEN_CENTRAL = "https://repo1.maven.org/maven2"
PLUGIN_PORTAL = "https://plugins.gradle.org/m2"

# Cuantos <parent> o BOM importados se siguen como mucho desde el BOM del catalogo.
MAX_POM_DEPTH = 5

_PROPERTY_RE = re.compile(r"\$\{([^}]+)\}")


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_google_dependency(group_id: str) -> bool:
    google_groups = ("com.google.", "androidx.", "android.arch.", "com.android.")
    return group_id.startswith(google_groups)


@dataclass
class Pom:
    """Lo que hace falta de un POM para saber que versiones fija un BOM."""

    group_id: str
    artifact_id: str
    version: str
    parent: tuple[str, str, str] | None = None
    properties: dict[str, str] = field(default_factory=dict)
    # Cada <dependency> del <dependencyManagement>, sin interpolar: campo -> texto.
    managed: list[dict[str, str]] = field(default_factory=list)


def _child(node: ET.Element | None, name: str) -> ET.Element | None:
    if node is None:
        return None
    for child in node:
        if _localname(child.tag) == name:
            return child
    return None


def _text(node: ET.Element | None, name: str) -> str:
    child = _child(node, name)
    return (child.text or "").strip() if child is not None else ""


def parse_pom(raw: bytes) -> Pom:
    root = ET.fromstring(raw)

    parent = None
    parent_node = _child(root, "parent")
    if parent_node is not None:
        coords = tuple(_text(parent_node, f) for f in ("groupId", "artifactId", "version"))
        if all(coords):
            parent = coords

    properties = {}
    props_node = _child(root, "properties")
    if props_node is not None:
        for prop in props_node:
            properties[_localname(prop.tag)] = (prop.text or "").strip()

    managed = []
    deps_node = _child(_child(root, "dependencyManagement"), "dependencies")
    if deps_node is not None:
        for dep in deps_node:
            if _localname(dep.tag) == "dependency":
                managed.append({_localname(c.tag): (c.text or "").strip() for c in dep})

    return Pom(
        group_id=_text(root, "groupId"),
        artifact_id=_text(root, "artifactId"),
        version=_text(root, "version"),
        parent=parent,
        properties=properties,
        managed=managed,
    )


def interpolate(value: str, properties: dict[str, str]) -> str | None:
    """Sustituye ${propiedad}, tambien anidadas. None si alguna no se resuelve."""
    for _ in range(10):
        if "${" not in value:
            return value
        replaced = _PROPERTY_RE.sub(lambda m: properties.get(m.group(1), m.group(0)), value)
        if replaced == value:
            return None
        value = replaced
    return None


class MavenRepository:
    """Acceso a los repositorios: listados de versiones y POMs de BOM."""

    def __init__(self, timeout: int = 15, retries: int = 3, jobs: int = 8):
        self.timeout = timeout
        self.retries = retries
        self.jobs = max(1, jobs)
        self._versions_cache: dict[str, list[str] | None] = {}
        self._bom_cache: dict[str, dict[str, str] | None] = {}
        self._pom_cache: dict[str, Pom | None] = {}
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
        return self._repos_for_group(dep.group_id)

    @staticmethod
    def _repos_for_group(group_id: str) -> list[str]:
        if is_google_dependency(group_id):
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

    def _fetch_pom(self, group_id: str, artifact_id: str, version: str) -> Pom | None:
        cache_key = f"{group_id}:{artifact_id}:{version}"
        if cache_key in self._pom_cache:
            return self._pom_cache[cache_key]

        pom = None
        path = group_id.replace(".", "/")
        for base in self._repos_for_group(group_id):
            url = f"{base}/{path}/{artifact_id}/{version}/{artifact_id}-{version}.pom"
            log(f"🔍 Leyendo POM: {url}")
            raw = self._get(url)
            if not raw:
                continue
            try:
                pom = parse_pom(raw)
            except ET.ParseError as exc:
                log(f"❌ POM invalido: {exc}")
                continue
            break

        self._pom_cache[cache_key] = pom
        return pom

    def _effective_model(
        self, group_id: str, artifact_id: str, version: str, depth: int
    ) -> tuple[dict[str, str], list[dict[str, str]]] | None:
        """Propiedades y <dependencyManagement> del POM, con lo heredado del <parent>.

        Como en Maven, se interpola despues de heredar: una propiedad del parent
        que use ${project.version} toma la version del hijo.
        """
        pom = self._fetch_pom(group_id, artifact_id, version)
        if pom is None:
            return None

        properties: dict[str, str] = {}
        managed: list[dict[str, str]] = []
        if pom.parent and depth < MAX_POM_DEPTH:
            inherited = self._effective_model(*pom.parent, depth + 1)
            if inherited:
                properties.update(inherited[0])
                managed.extend(inherited[1])
        properties.update(pom.properties)

        parent_group, _, parent_version = pom.parent or ("", "", "")
        own_version = pom.version or parent_version
        properties.update({
            "project.version": own_version,
            "pom.version": own_version,
            "version": own_version,
            "project.groupId": pom.group_id or parent_group,
            "project.artifactId": pom.artifact_id,
        })
        if pom.parent:
            properties["project.parent.version"] = parent_version
            properties["project.parent.groupId"] = parent_group

        # Las del hijo van detras: al construir el indice, pisan a las heredadas.
        managed.extend(pom.managed)
        return properties, managed

    def _managed_for(
        self, group_id: str, artifact_id: str, version: str, depth: int
    ) -> dict[str, str] | None:
        model = self._effective_model(group_id, artifact_id, version, depth)
        if model is None:
            return None
        properties, entries = model

        managed: dict[str, str] = {}
        imports: list[tuple[str, str, str]] = []
        for fields in entries:
            coords = [
                interpolate(fields.get(name, ""), properties)
                for name in ("groupId", "artifactId", "version")
            ]
            if not all(coords):
                continue
            group, artifact, managed_version = coords
            if fields.get("scope") == "import" and fields.get("type") == "pom":
                imports.append((group, artifact, managed_version))
            else:
                managed[f"{group}:{artifact}"] = managed_version

        # Lo declarado directamente gana a lo importado; entre importados, el primero.
        if depth < MAX_POM_DEPTH:
            for imported in imports:
                for coordinate, imported_version in (
                    self._managed_for(*imported, depth + 1) or {}
                ).items():
                    managed.setdefault(coordinate, imported_version)
        return managed

    def bom_managed(self, dep: Dependency, version: str) -> dict[str, str] | None:
        """Lee el <dependencyManagement> efectivo de un BOM: modulo -> version.

        Devuelve None si no se pudo leer el POM o no se resolvio ninguna version,
        para no confundir "no se pudo leer" con "no gestiona esa dependencia".
        """
        cache_key = f"{dep.coordinate}:{version}"
        if cache_key not in self._bom_cache:
            log(f"📦 Leyendo BOM: {cache_key}")
            managed = self._managed_for(dep.group_id, dep.artifact_id, version, depth=0)
            if managed:
                log(f"✅ El BOM gestiona {len(managed)} modulos")
            self._bom_cache[cache_key] = managed or None
        return self._bom_cache[cache_key]
