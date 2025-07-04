# Gradle Deps Monitor 🔍

Un script automatizado para verificar y comparar las versiones de dependencias Maven en proyectos Android/Gradle contra las últimas versiones disponibles en Maven Central y Google Maven.

## 🚀 Características

- ✅ Analiza archivos `libs.versions.toml` de Gradle
- 🔍 Consulta automáticamente Maven Central y Google Maven
- 📊 Categoriza dependencias por estado de actualización:
  - 🔴 Diferencia Major (actualización importante requerida)
  - 🟡 Diferencia Minor o Patch > 5 (actualización recomendada)
  - 🟢 Actualizado (diferencia mínima o igual)
  - ⚫ Estado desconocido (no se pudo verificar)
- 🏷️ Distingue entre dependencias de Google y Maven Central
- 💾 Genera reporte JSON detallado
- 🐍 Manejo automático de entorno virtual Python

## 📋 Prerrequisitos

- Python 3.6+
- Bash
- jq (para generar reportes formateados)
- Acceso a internet para consultas Maven

## 🛠️ Instalación

1. Clona este repositorio:
```bash
git clone https://github.com/pfranccino/toml-deps-checker.git
cd toml-deps-checker
```

2. Dale permisos de ejecución a los scripts:
```bash
chmod +x check-dependencies.sh
chmod +x generate_dependency_report.sh
```

## 📖 Uso

### Verificación de dependencias

Ejecuta el script proporcionando la ruta a tu directorio Gradle que contiene `libs.versions.toml`:

```bash
./check-dependencies.sh /ruta/al/directorio/gradle
```

#### Ejemplo:
```bash
./check-dependencies.sh ./app/gradle
```

### Generación de reportes

Después de ejecutar la verificación de dependencias, puedes generar un reporte formateado usando:

```bash
./generate_dependency_report.sh [archivo_json]
```

Si no se proporciona un archivo JSON, se utilizará `dependency_status.json` por defecto.

#### Ejemplo:
```bash
./generate_dependency_report.sh
# O especificando un archivo JSON personalizado:
./generate_dependency_report.sh mi_archivo.json
```

El script generará un archivo `dependency_report.txt` con un formato legible de todas las dependencias y sus estados.

## 📊 Salida

El script genera un archivo `dependency_status.json` con información detallada de cada dependencia:

```json
{
  "com.squareup.retrofit2:retrofit": {
    "url": "https://central.sonatype.com/artifact/com.squareup.retrofit2/retrofit",
    "version_used": "2.9.0",
    "latest_version": "2.11.0",
    "timestamp": "2024-01-15T10:30:00",
    "status": "🟡",
    "type": "maven"
  },
  "androidx.core:core-ktx": {
    "url": "https://maven.google.com/web/index.html#androidx.core",
    "version_used": "1.10.1",
    "latest_version": "1.12.0",
    "timestamp": "2024-01-15T10:30:00",
    "status": "🟡",
    "type": "google"
  }
}
```

## 🏗️ Estructura del proyecto

```
├── check-dependencies.sh         # Script principal de Bash
├── generate_dependency_report.sh # Script para generar reportes formateados
├── version-stats.py              # Script de Python para análisis
├── README.md                     # Este archivo
├── dependency_status.json        # Archivo de salida JSON (generado)
└── dependency_report.txt         # Archivo de reporte formateado (generado)
```

## ⚙️ Cómo funciona

### check-dependencies.sh

1. **Validación**: Verifica que existe el directorio y el archivo `libs.versions.toml`
2. **Entorno virtual**: Crea y activa un entorno virtual Python
3. **Instalación**: Instala las dependencias Python necesarias (`requests`)
4. **Análisis**: 
   - Parsea el archivo `libs.versions.toml`
   - Extrae información de dependencias
   - Consulta Maven Central y/o Google Maven por las últimas versiones
5. **Comparación**: Evalúa el estado de cada dependencia
6. **Reporte**: Genera un archivo JSON con los resultados

### generate_dependency_report.sh

1. **Validación**: Verifica que existe el archivo JSON de entrada (por defecto `dependency_status.json`)
2. **Procesamiento**: 
   - Utiliza `jq` para procesar el archivo JSON
   - Extrae información de cada dependencia (nombre, versión actual, última versión, estado)
3. **Formateo**: Formatea cada dependencia según un formato legible
4. **Reporte**: Genera un archivo de texto (`dependency_report.txt`) con el reporte formateado

## 🔧 Configuración

### Tipos de dependencias soportadas

- **Google/Android**: `androidx.*`, `com.google.*`, `com.android.*`, etc.
- **Maven Central**: Todas las demás dependencias públicas

### Criterios de estado

- 🔴 **Major**: Cambio en versión mayor (ej: 1.x.x → 2.x.x)
- 🟡 **Minor/Patch**: Cambio en versión menor o parche > 5
- 🟢 **Actualizado**: Versión igual o diferencia mínima
- ⚫ **Desconocido**: No se pudo determinar la versión

## 🤝 Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 🐛 Reportar problemas

Si encuentras algún bug o tienes una sugerencia, por favor abre un [issue](https://github.com/pfranccino/gradle-deps-monitor/issues).
