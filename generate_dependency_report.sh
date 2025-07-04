#!/bin/bash

# Script to generate dependency report from JSON file
# Usage: ./generate_dependency_report.sh [json_file]
# If no json_file is provided, dependency_status.json will be used by default

echo "🚀 Iniciando generador de reporte de dependencias"

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "❌ Error: jq is required but not installed. Please install jq."
    exit 1
fi

# Path to input and output files
JSON_FILE="${1:-dependency_status.json}"
REPORT_FILE="dependency_report.txt"

echo "📂 Archivo de entrada: $JSON_FILE"
echo "📄 Archivo de salida: $REPORT_FILE"

# Check if JSON file exists
if [ ! -f "$JSON_FILE" ]; then
    echo "❌ Error: $JSON_FILE not found."
    exit 1
fi

# Clear the report file if it exists
> "$REPORT_FILE"

# Process each dependency in the JSON file
echo "🔎 Procesando dependencias..."
jq -r 'to_entries | .[] | @json' "$JSON_FILE" | while read -r dependency; do
    # Extract dependency information
    name=$(echo "$dependency" | jq -r '.key')
    status=$(echo "$dependency" | jq -r '.value.status')
    version_used=$(echo "$dependency" | jq -r '.value.version_used')
    latest_version=$(echo "$dependency" | jq -r '.value.latest_version')

    # Format the line according to the specified format
    formatted_line="$status *$name* - Actual: \`$version_used\`| Última: \`$latest_version\`"

    # Append the formatted line to the report file
    echo "$formatted_line" >> "$REPORT_FILE"

    # Print the formatted line to the terminal
    echo "📝 Añadiendo: $formatted_line"
done

echo "✅ Reporte de dependencias generado: $REPORT_FILE"
echo "✨ Proceso completado"
