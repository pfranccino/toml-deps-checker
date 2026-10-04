"""Lectura del catalogo de versiones (libs.versions.toml)."""
import os
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

CATALOG_NAME = "libs.versions.toml"


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


def find_catalog(path: str) -> str:
    """Localiza el libs.versions.toml a partir de lo que pase el usuario.

    Admite la ruta del archivo, el directorio gradle/ o la raiz del proyecto.
    """
    if os.path.isfile(path):
        return path
    for candidate in (
        os.path.join(path, CATALOG_NAME),
        os.path.join(path, "gradle", CATALOG_NAME),
    ):
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(
        f"No se encontro {CATALOG_NAME} en {path} ni en {os.path.join(path, 'gradle')}"
    )


def is_version_range(value: str) -> bool:
    """Rangos y versiones dinamicas de Gradle: [1.0, 2.0[, (,2.0], 1.+, latest.release."""
    value = value.strip()
    return (
        value.startswith(("[", "]", "("))
        or value.endswith("+")
        or value.startswith("latest.")
    )


def _plain_version(raw: Any) -> str | None:
    """Extrae el texto de una version, admitiendo las 'rich versions' de Gradle.

    Regla comun con android-module-map: strictly, luego require, luego prefer,
    saltando los que sean un rango. Con { strictly = "[1.0, 2.0[", prefer = "1.5" }
    sale 1.5. Si solo hay rangos, se devuelve el rango tal cual y saldra unknown.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        fields = [raw[f] for f in ("strictly", "require", "prefer") if isinstance(raw.get(f), str)]
        for value in fields:
            if not is_version_range(value):
                return value
        if fields:
            return fields[0]
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
