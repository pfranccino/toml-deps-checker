# Gradle Deps Monitor 🔍

Un script automatizado para verificar y comparar las versiones de dependencias Maven en proyectos Android/Gradle contra las últimas versiones disponibles en Maven Central y Google Maven.

## 🚀 Características

- ✅ Analiza archivos `libs.versions.toml` de Gradle, en todas las formas que admite
  Gradle: `module`, `group`/`name`, atajo en string, versión literal, `version.ref`,
  rich versions y la sección `[plugins]`
- 📦 Soporte de BOM: resuelve las dependencias sin versión propia y avisa de qué
  cambiaría al subir el BOM
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

- Python 3.11+ (para `tomllib`; en versiones anteriores, `pip install tomli`)
- Bash
- Acceso a internet para consultas Maven

## 🛠️ Instalación

1. Clona este repositorio:
```bash
git clone https://github.com/pfranccino/toml-deps-checker.git
cd toml-deps-checker
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

### Canales de versión

Por defecto se compara contra la **última versión estable**. Los pre-releases nunca
determinan el veredicto, pero sí se reportan como información adicional en el campo
`latest_prerelease`, para que sepas que existen sin que te empujen a usarlos.

Si quieres que el veredicto tenga en cuenta versiones no estables:

```bash
./check-dependencies.sh ./app/gradle --channel rc      # estables + rc
./check-dependencies.sh ./app/gradle --channel beta    # estables + rc + beta
./check-dependencies.sh ./app/gradle --channel alpha   # todo
./check-dependencies.sh ./app/gradle --include-prereleases   # atajo de --channel alpha
```

Cada canal incluye los más estables que él. Otras opciones: `-o/--output` para elegir
la ruta del JSON, `-q/--quiet` para silenciar el progreso, `-j/--jobs` para las
peticiones en paralelo (por defecto 8) y `--timeout` para el tiempo por petición.

## 🤖 Uso en CI

Por defecto el script **nunca falla por política**: analiza, informa y sale con 0. Para
que un pipeline pueda bloquear, se usa `--fail-on`:

```bash
./check-dependencies.sh ./app/gradle --fail-on major   # falla si hay algún 🔴
./check-dependencies.sh ./app/gradle --fail-on minor   # 🔴 y los minor
./check-dependencies.sh ./app/gradle --fail-on any     # cualquier desactualización
```

Las dependencias en ⚫ (no se pudieron consultar) **nunca hacen fallar**: que un
repositorio no responda es un problema de red, no un incumplimiento, y no tiene
sentido teñir el build de rojo por ello. Sí se listan aparte al final para que no
pasen desapercibidas.

Los umbrales también son ajustables, por si el criterio por defecto no encaja:

```bash
--patch-threshold 0    # cualquier patch por detrás cuenta como desactualizado
--calver-months 3      # un BOM CalVer con 3 meses de retraso ya es 🔴
```

### GitHub Actions

```yaml
- name: Comprobar dependencias
  run: ./check-dependencies.sh ./gradle --fail-on major --quiet

- name: Publicar informe
  if: always()          # también cuando el paso anterior falla
  uses: actions/upload-artifact@v4
  with:
    name: dependency-status
    path: dependency_status.json
```

El `if: always()` importa: sin él, el informe se pierde justo cuando falla, que es
cuando hace falta leerlo.

## 🧪 Tests

Las funciones puras (parseo del catálogo, orden de versiones, canales, CalVer,
variantes) están cubiertas por tests que no tocan la red:

```bash
python -m unittest discover -v
```

## 📊 Salida

El script genera un archivo `dependency_status.json` con información detallada de cada dependencia:

```json
{
  "androidx.compose.foundation:foundation": {
    "url": "https://maven.google.com/web/index.html#androidx.compose.foundation",
    "version_used": "1.12.0",
    "latest_version": "1.12.0",
    "latest_stable": "1.12.0",
    "latest_prerelease": "1.13.0-alpha02",
    "channel": "stable",
    "timestamp": "2026-09-08T19:02:50",
    "status": "🟢",
    "status_code": "ok",
    "type": "google"
  }
}
```

| Campo | Significado |
|---|---|
| `latest_version` | La última del canal seleccionado. Es la que determina el `status`. |
| `latest_stable` | La última estable, siempre presente sea cual sea el canal. |
| `latest_prerelease` | El pre-release más alto, solo si va por delante de la estable. `N/A` si no hay. |
| `channel` | Canal usado en esta ejecución. |
| `status_code` | Versión legible por máquina del `status`: `ok`, `patch`, `minor`, `major`, `prerelease`, `unknown`. |

## 🏗️ Estructura del proyecto

```
├── check-dependencies.sh     # Script principal de Bash
├── version-stats.py          # Script de Python para análisis
├── test_version_stats.py     # Tests (sin red)
├── requirements.txt          # Dependencias de Python
├── README.md                 # Este archivo
└── dependency_status.json    # Archivo de salida (generado)
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
- 🟡 **Pre-release**: Estás en un alpha/beta/rc y ya salió la versión final
- 🟢 **Actualizado**: Versión igual, más nueva, o diferencia mínima
- ⚪ **Gestionada**: La versión la fija un BOM, no se actualiza por separado
- ⚫ **Desconocido**: No se pudo determinar la versión

Las versiones se comparan de forma lexicográfica sobre la tupla completa, así que una
versión más nueva que la publicada nunca se marca como desactualizada.

### BOM (Bill of Materials)

Los BOM se detectan solos (artefactos acabados en `-bom`) y reciben un trato aparte:

- Las dependencias **sin versión propia** se resuelven leyendo el
  `<dependencyManagement>` del POM del BOM, así que dejan de ser invisibles y se
  reportan con su versión efectiva y el BOM que las fija.
- Esas dependencias **no llevan veredicto propio** (salen como ⚪). No se pueden
  actualizar por separado: se sube el BOM. Marcarlas en rojo llenaría el informe de
  quince alertas que se arreglan todas con un solo cambio de línea.
- El BOM sí lleva veredicto, y cuando está desactualizado se indica **qué versiones
  traería subirlo**, limitado a los módulos que realmente usas:

```
🔴 androidx.compose:compose-bom     2025.12.00   2026.08.00
   └─ al subir: androidx.compose.ui:ui 1.10.0 → 1.12.0
⚪ androidx.compose.ui:ui           1.10.0       (vía compose-bom 2025.12.00)
```

### Versionado por fecha (CalVer)

`compose-bom` no usa semver sino la fecha: `2026.08.00`. Comparar eso por
major/minor/patch pondría en rojo todos los BOM cada enero, solo porque cambia el
dígito del año. Cuando el primer componente es un año, la distancia se mide en
**meses**: 🟡 a partir de 1 mes y 🔴 a partir de 6.

### Variantes paralelas

Algunos artefactos publican líneas paralelas del mismo número: `guava:31.1-jre` y
`guava:31.1-android`. La comparación se mantiene dentro de la variante que ya usas,
porque saltar de `-jre` a `-android` no es una actualización.

## 🤝 Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 🐛 Reportar problemas

Si encuentras algún bug o tienes una sugerencia, por favor abre un [issue](https://github.com/pfranccino/gradle-deps-monitor/issues).
