#!/bin/bash
# Atajo para desarrollo: ejecuta el clon actual sin instalarlo con pipx.
# Uso: ./check-dependencies.sh [ruta] [opciones de toml-deps-checker]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv-deps"

# En Windows no suele existir python3, solo python.
PYTHON="$(command -v python3 || command -v python)"
if [ -z "${PYTHON}" ]; then
  echo "❌ Error: no se encontró Python" >&2
  exit 1
fi

# Crear el entorno virtual e instalar el paquete en modo editable, solo la primera vez.
if [ ! -d "${VENV_DIR}" ]; then
  echo "🔨 Creando entorno virtual en ${VENV_DIR}..." >&2
  if ! "${PYTHON}" -m venv "${VENV_DIR}"; then
    echo "❌ Error al crear el entorno virtual" >&2
    exit 1
  fi
  NEEDS_INSTALL=1
fi

# Localizar los binarios del venv (Windows/Git Bash usa Scripts/ en vez de bin/)
if [ -x "${VENV_DIR}/Scripts/python.exe" ]; then
  VENV_PYTHON="${VENV_DIR}/Scripts/python.exe"
elif [ -x "${VENV_DIR}/bin/python" ]; then
  VENV_PYTHON="${VENV_DIR}/bin/python"
else
  echo "❌ Error: no se encontró el intérprete de Python en ${VENV_DIR}" >&2
  exit 1
fi

if [ -n "${NEEDS_INSTALL}" ]; then
  echo "📦 Instalando toml-deps-checker..." >&2
  if ! "${VENV_PYTHON}" -m pip install --quiet -e "${SCRIPT_DIR}"; then
    echo "❌ Error al instalar dependencias" >&2
    rm -rf "${VENV_DIR}"
    exit 1
  fi
fi

exec "${VENV_PYTHON}" -m toml_deps_checker "$@"
