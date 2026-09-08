#!/bin/bash

# Verificar que se haya proporcionado una ruta como argumento
if [ $# -eq 0 ]; then
  echo "❌ Error: Falta la ruta al directorio gradle"
  echo "Uso: ./check-dependencies.sh /ruta/al/directorio/gradle"
  exit 1
fi

GRADLE_PATH=$1
shift  # el resto de argumentos se pasan tal cual al script de Python
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv-deps"
PYTHON_SCRIPT="${SCRIPT_DIR}/version-stats.py"

echo "🚀 Iniciando verificador de dependencias"
echo "📂 Directorio gradle a analizar: ${GRADLE_PATH}"

# Verificar que el directorio gradle exista
if [ ! -d "${GRADLE_PATH}" ]; then
  echo "❌ Error: El directorio ${GRADLE_PATH} no existe"
  exit 1
fi

# Verificar que exista el archivo libs.versions.toml
if [ ! -f "${GRADLE_PATH}/libs.versions.toml" ]; then
  echo "❌ Error: No se encontró el archivo libs.versions.toml en ${GRADLE_PATH}"
  exit 1
fi

# Crear entorno virtual si no existe
if [ ! -d "${VENV_DIR}" ]; then
  echo "🔨 Creando entorno virtual en ${VENV_DIR}..."
  python3 -m venv "${VENV_DIR}"
  if [ $? -ne 0 ]; then
    echo "❌ Error al crear el entorno virtual"
    exit 1
  fi
fi

# Localizar los binarios del venv (Windows/Git Bash usa Scripts/ en vez de bin/)
if [ -x "${VENV_DIR}/Scripts/python.exe" ]; then
  VENV_PYTHON="${VENV_DIR}/Scripts/python.exe"
elif [ -x "${VENV_DIR}/bin/python" ]; then
  VENV_PYTHON="${VENV_DIR}/bin/python"
else
  echo "❌ Error: no se encontró el intérprete de Python en ${VENV_DIR}"
  exit 1
fi

# Instalar dependencias (se llama al binario directamente, sin activar el entorno)
echo "📦 Instalando dependencias..."
REQUIREMENTS="${SCRIPT_DIR}/requirements.txt"
if [ -f "${REQUIREMENTS}" ]; then
  PIP_ARGS=(-r "${REQUIREMENTS}")
else
  PIP_ARGS=(requests)
fi
if ! "${VENV_PYTHON}" -m pip install --quiet "${PIP_ARGS[@]}"; then
  echo "❌ Error al instalar dependencias"
  exit 1
fi

# Ejecutar el script de Python con los argumentos extra que se hayan pasado
echo "🔎 Analizando dependencias..."
"${VENV_PYTHON}" "${PYTHON_SCRIPT}" "${GRADLE_PATH}" "$@"
SCRIPT_RESULT=$?

if [ ${SCRIPT_RESULT} -ne 0 ]; then
  echo "❌ Error al ejecutar el script de análisis"
  exit ${SCRIPT_RESULT}
fi

echo "✨ Proceso completado"