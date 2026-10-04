"""Analisis del catalogo: cruza cada entrada con los repositorios y le pone estado."""
from datetime import datetime
from typing import Any

from .catalog import Dependency, find_catalog, parse_catalog
from .maven import MavenRepository, is_google_dependency
from .progress import log
from .versions import (
    ALPHA,
    CALVER_MONTHS_MAJOR,
    CHANNEL_MIN_RANK,
    PATCH_THRESHOLD,
    STABLE,
    compare_versions,
    is_prerelease,
    pick_latest,
    version_flavor,
    version_key,
)

STATUS_EMOJI = {
    "major": "🔴",
    "minor": "🟡",
    "patch": "🟡",
    "prerelease": "🟡",
    "ok": "🟢",
    "managed": "⚪",
    "unknown": "⚫",
}

_NO_VERSIONS = {"latest": None, "latest_stable": None, "latest_prerelease": None}


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
        self.catalog_path: str | None = None
        self.timestamp: str | None = None
        log(f"Iniciando MavenVersionChecker (canal: {channel}, {repository.jobs} hilos)...")

    def resolve_versions(self, dep: Dependency) -> dict[str, str | None]:
        """Calcula la ultima del canal pedido, la ultima estable y el ultimo pre-release."""
        versions = self.repo.versions_for(dep)
        if not versions:
            return dict(_NO_VERSIONS)

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

    def process_toml_file(self, path: str) -> tuple[dict[str, Any], list[str]]:
        """Analiza el catalogo. `path` puede ser el archivo, gradle/ o la raiz del proyecto."""
        file_path = find_catalog(path)
        self.catalog_path = file_path

        log(f"\n📂 Procesando: {file_path}")
        deps, warnings = parse_catalog(file_path)
        log(f"📖 {len(deps)} entradas leidas del catalogo")

        self.timestamp = datetime.now().isoformat()
        result: dict[str, Any] = {}

        # 1) Los BOM primero: hacen falta para resolver las que no llevan version.
        boms = [d for d in deps if d.is_bom and d.version]
        managed_index: dict[str, tuple[Dependency, str]] = {}
        unreadable: list[Dependency] = []
        for bom in boms:
            managed = self.repo.bom_managed(bom, bom.version)
            if managed is None:
                unreadable.append(bom)
                warnings.append(f"{bom.alias}: no se pudo leer el BOM {bom.coordinate}:{bom.version}")
                continue
            for coordinate, version in managed.items():
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
                result[dep.display] = self._entry(dep, "managed", _NO_VERSIONS)
                continue

            if not dep.version:
                if unreadable:
                    nombres = ", ".join(b.artifact_id for b in unreadable)
                    warnings.append(
                        f"{dep.alias}: sin version; podria gestionarla {nombres}, "
                        f"pero no se pudo leer"
                    )
                else:
                    warnings.append(f"{dep.alias}: sin version y ningun BOM del catalogo la gestiona")
                result[dep.display] = self._entry(dep, "unknown", _NO_VERSIONS)
                continue

            resolved = self.resolve_versions(dep)
            status = compare_versions(
                dep.version,
                resolved["latest"],
                self.patch_threshold,
                self.calver_months_major,
            )
            entry = self._entry(dep, status, resolved)

            # Para un BOM desactualizado, decir que traeria subirlo.
            if dep.is_bom and status not in ("ok", "unknown") and resolved["latest"]:
                entry["managed_changes"] = self._bom_diff(dep, resolved["latest"], deps)

            result[dep.display] = entry

        log(f"\n✅ Completado. Dependencias analizadas: {len(result)}")
        return result, warnings

    def _bom_diff(self, bom: Dependency, new_version: str, deps: list[Dependency]) -> dict[str, Any]:
        """Que versiones cambiarian en las dependencias del catalogo al subir el BOM."""
        actual = self.repo.bom_managed(bom, bom.version) or {}
        nueva = self.repo.bom_managed(bom, new_version) or {}
        usados = {d.coordinate for d in deps if d.managed_by and d.managed_by.startswith(bom.artifact_id)}

        cambios = {}
        for coordinate in sorted(usados):
            antes = actual.get(coordinate)
            despues = nueva.get(coordinate)
            if antes and despues and antes != despues:
                cambios[coordinate] = {"from": antes, "to": despues}
        return cambios

    def _entry(self, dep, status, resolved) -> dict[str, Any]:
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
            "timestamp": self.timestamp,
            "status": STATUS_EMOJI[status],
            "status_code": status,
            "type": dep_type,
        }
        if dep.managed_by:
            entry["managed_by"] = dep.managed_by
        if dep.is_bom:
            entry["is_bom"] = True
        return entry
