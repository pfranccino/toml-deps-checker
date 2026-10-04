"""Log de progreso. Va a stderr para que stdout quede solo con el resumen."""
import sys

_quiet = False


def set_quiet(quiet: bool) -> None:
    global _quiet
    _quiet = quiet


def log(message: str) -> None:
    if not _quiet:
        print(message, file=sys.stderr)
