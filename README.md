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
- Acceso a internet para consultas Maven

## 🛠️ Instalación

1. Clona este repositorio:
```bash
git clone https://github.com/pfranccino/gradle-deps-monitor.git
cd gradle-deps-monitor
```

2. Dale permisos de ejecución al script:
```bash
chmod +x check-dependencies.sh
```

## 📖 Uso

Ejecuta el script proporcionando la ruta a tu directorio Gradle que contiene `libs.versions.toml`:

```bash
./check-dependencies.sh /ruta/al/directorio/gradle
```

### Ejemplo:
```bash
./check-dependencies.sh ./app/gradle
```

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
├── check-dependencies.sh    # Script principal de Bash
├── version-stats.py        # Script de Python para análisis
├── README.md              # Este archivo
└── dependency_status.json # Archivo de salida (generado)
```

## ⚙️ Cómo funciona

1. **Validación**: Verifica que existe el directorio y el archivo `libs.versions.toml`
2. **Entorno virtual**: Crea y activa un entorno virtual Python
3. **Instalación**: Instala las dependencias Python necesarias (`requests`)
4. **Análisis**: 
   - Parsea el archivo `libs.versions.toml`
   - Extrae información de dependencias
   - Consulta Maven Central y/o Google Maven por las últimas versiones
5. **Comparación**: Evalúa el estado de cada dependencia
6. **Reporte**: Genera un archivo JSON con los resultados

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
