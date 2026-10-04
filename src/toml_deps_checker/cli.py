"""Linea de comandos: `toml-deps-checker [ruta]`."""
import argparse
import contextlib
import json
import os
import sys
from typing import Any

from . import __version__
from .catalog import tomllib
from .checker import STATUS_EMOJI, MavenVersionChecker
from .maven import MavenRepository
from .progress import log, set_quiet
from .versions import CALVER_MONTHS_MAJOR, PATCH_THRESHOLD

DEFAULT_OUTPUT = "dependency_status.json"
SCHEMA_V2 = "toml-deps-checker/status-2"

# Campos que en v2 son de la ejecucion, no de cada entrada: pasan a `meta`.
_RUN_FIELDS = ("timestamp", "channel")


def build_report(
    result: dict[str, Any],
    warnings: list[str],
    schema: str,
    checker: MavenVersionChecker,
) -> dict[str, Any]:
    """Arma el JSON de salida.

    v1 es el mapa plano coordenada -> entrada de siempre. v2 lo envuelve con
    `schema` y `meta`, y saca de cada entrada lo que es comun a la ejecucion.
    """
    if schema == "v1":
        return result

    return {
        "schema": SCHEMA_V2,
        "meta": {
            "generated_at": checker.timestamp,
            "tool_version": __version__,
            "catalog": _display_path(checker.catalog_path),
            "channel": checker.channel,
            "thresholds": {
                "patch": checker.patch_threshold,
                "calver_months": checker.calver_months_major,
            },
            "warnings": warnings,
        },
        "dependencies": {
            name: {k: v for k, v in entry.items() if k not in _RUN_FIELDS}
            for name, entry in result.items()
        },
    }


def _display_path(path: str | None) -> str | None:
    """Ruta relativa al directorio actual si se puede, siempre con '/'."""
    if path is None:
        return None
    try:
        path = os.path.relpath(path)
    except ValueError:  # otra unidad en Windows
        path = os.path.abspath(path)
    return path.replace(os.sep, "/")


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toml-deps-checker",
        description="Compara las dependencias de un libs.versions.toml con Maven Central y Google Maven.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="libs.versions.toml, el directorio gradle/ que lo contiene o la raiz del "
             "proyecto (por defecto: el directorio actual)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
    parser.add_argument(
        "-o", "--output", help=f"Ruta del JSON de salida (por defecto: ./{DEFAULT_OUTPUT})"
    )
    parser.add_argument(
        "--schema",
        choices=("v1", "v2"),
        default="v1",
        help="Forma del JSON: v1, el mapa plano de siempre (por defecto), o v2, "
             f"con 'schema' ({SCHEMA_V2}), 'meta' y 'dependencies'",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Silencia el log de progreso")
    parser.add_argument("--timeout", type=int, default=15, help="Timeout por peticion en segundos")
    parser.add_argument(
        "-j", "--jobs", type=int, default=8, help="Peticiones en paralelo (por defecto: 8)"
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
    return parser


def main(argv: list[str] | None = None) -> int:
    # En Windows stdout usa cp1252 cuando esta redirigido a un archivo o a una pipe,
    # y los emoji revientan con UnicodeEncodeError a mitad del analisis.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)

    set_quiet(args.quiet)
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
        result, warnings = checker.process_toml_file(args.path)
    except FileNotFoundError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    except tomllib.TOMLDecodeError as exc:
        print(f"❌ El libs.versions.toml no es válido: {exc}", file=sys.stderr)
        return 1

    if not result:
        print("❌ No se pudo analizar ninguna dependencia", file=sys.stderr)
        return 1

    output_file = os.path.abspath(args.output or DEFAULT_OUTPUT)
    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(build_report(result, warnings, args.schema, checker), handle,
                  indent=2, ensure_ascii=False)

    print_summary(result, warnings)
    print(f"\n💾 Resultados guardados en: {output_file}")

    return 0
