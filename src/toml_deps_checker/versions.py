"""Orden y comparacion de versiones: canales, CalVer y variantes paralelas."""
import re

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

VersionKey = tuple[tuple[int, ...], int, int]


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


def version_key(version: str) -> VersionKey | None:
    """Convierte una version en una clave ordenable: (numeros, estabilidad, secuencia).

    Ordena los pre-releases por debajo de su version final, porque
    5.0.0-alpha.16 -> ((5,0,0), 0, 16) queda por debajo de 5.0.0 -> ((5,0,0), 3, 0).

    Los numeros se guardan completos: 1.2.3.10 tiene que quedar por encima de
    1.2.3.9. Se rellenan hasta 3 y se quitan los ceros finales a partir de ahi,
    para que 1.2, 1.2.0 y 1.2.0.0 den la misma clave.
    """
    raw = version.strip().lstrip("vV").split("+")[0]
    match = _NUMERIC_RE.match(raw)
    if not match:
        return None

    numbers = [int(part) for part in match.group(1).split(".")]
    numbers += [0] * (3 - len(numbers))
    while len(numbers) > 3 and numbers[-1] == 0:
        numbers.pop()

    qualifier = match.group(2).lstrip("-_.")
    sequence = re.search(r"(\d+)", qualifier)
    return (
        tuple(numbers),
        qualifier_rank(qualifier),
        int(sequence.group(1)) if sequence else 0,
    )


def is_prerelease(version: str) -> bool:
    key = version_key(version)
    return key is not None and key[1] < STABLE


def is_calver(key: VersionKey) -> bool:
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

    # Una cuarta posicion (1.2.3.4 -> 1.2.3.9) cuenta como patch: es un salto
    # aun mas pequenyo, asi que no puede pesar mas que uno, y aplica el umbral.
    width = max(len(current_nums), len(latest_nums))
    cur = current_nums + (0,) * (width - len(current_nums))
    new = latest_nums + (0,) * (width - len(latest_nums))
    for a, b in zip(cur[3:], new[3:]):
        if a != b:
            return "patch" if b - a > patch_threshold else "ok"

    # Mismos numeros: la diferencia esta en el canal (estas en un pre-release
    # y ya salio la version final) o en la secuencia del pre-release.
    return "prerelease"
