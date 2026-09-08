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
  - 🟡 Diferencia Minor, o Patch por encima del umbral configurable
  - 🟢 Actualizado (igual, más nuevo, o diferencia por debajo del umbral)
  - ⚪ Gestionada por un BOM
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

## 🎚️ Cómo se decide el color

### El orden de decisión

Para cada dependencia se compara la versión en uso con la última del canal elegido:

1. **¿La tuya es igual o más nueva?** → 🟢. La comparación es lexicográfica sobre la
   tupla completa, así que ir por delante nunca se marca como desactualizado.
2. **¿Ambas usan versionado por fecha?** (el primer número es un año entre 2000 y 2999)
   → se mide en **meses**, ver más abajo.
3. **Si no**, se aplica semver: major → 🔴, minor → 🟡, patch → según el umbral.
4. **¿Mismos números pero distinto canal?** (estás en un `-alpha` y ya salió la final)
   → 🟡.

### Qué se puede configurar y qué no

Solo los dos escalones más bajos. Lo grave no se negocia:

| Nivel | Regla | Configurable |
|---|---|---|
| major | 1 de diferencia ya es 🔴 | ❌ |
| minor | 1 de diferencia ya es 🟡 | ❌ |
| patch | tolera hasta N | ✅ `--patch-threshold` (por defecto `5`) |
| fecha (CalVer) | 🟡 desde 1 mes, 🔴 desde N | ✅ `--calver-months` (por defecto `6`) |

Ojo con el minor: **no tiene umbral**. Estar 2 minors por detrás se ve igual que estar
18, ambos 🟡. Para distinguirlos hay que mirar las columnas de versión, no el color.

### `--patch-threshold`

Cuántos parches por detrás siguen contando como al día. Tu versión `1.2.0` contra
`1.2.N`:

```
parches por detrás :  0   1   2   3   4   5   6   7   8
por defecto (5)    : 🟢  🟢  🟢  🟢  🟢  🟢  🟡  🟡  🟡
--patch-threshold 3: 🟢  🟢  🟢  🟢  🟡  🟡  🟡  🟡  🟡
--patch-threshold 0: 🟢  🟡  🟡  🟡  🟡  🟡  🟡  🟡  🟡
```

`0` significa "cualquier versión por detrás me interesa". Una diferencia de patch nunca
llega a 🔴, por grande que sea.

### `--calver-months`

Meses de retraso antes de marcar en rojo. Tu BOM en `2026.01.00` contra N meses después:

```
meses por detrás  :  0   1   2   3   4   5   6   7   8
por defecto (6)   : 🟢  🟡  🟡  🟡  🟡  🟡  🔴  🔴  🔴
--calver-months 3 : 🟢  🟡  🟡  🔴  🔴  🔴  🔴  🔴  🔴
--calver-months 2 : 🟢  🟡  🔴  🔴  🔴  🔴  🔴  🔴  🔴
```

Verde es **solo el mismo mes**, no un rango. Y `--calver-months 1` deja el amarillo sin
banda: cualquier versión de otro mes salta directa a 🔴, así que `2` es el mínimo útil.

El tercer número (`2026.08.**00**`) es una **revisión dentro del mes, no un día**: de
`2026.01.00` a `2026.01.05` hay cero meses de diferencia, y sale 🟢.

### Cuidado: los dos umbrales no cuentan igual

Es una inconsistencia heredada que conviene tener presente al configurarlos:

- En `--patch-threshold`, el número es **el último valor que sigue siendo 🟢**.
- En `--calver-months`, el número es **el primero que ya es 🔴**.

Con `3` en cada uno: 3 parches todavía es verde, pero 3 meses ya es rojo.

### La fecha no depende de que sea un BOM

La rama de meses se elige por **el formato de la versión**, no por el tipo de artefacto.
`firebase-bom` es un BOM y usa major/minor, porque su versión es `34.18.0`:

```bash
$ ./check-dependencies.sh ./gradle --calver-months 2
🔴 androidx.compose:compose-bom      2026.04.01  2026.08.00   ← CalVer, le afecta
🟡 com.google.firebase:firebase-bom  34.10.0     34.18.0      ← semver, ni se entera
🟡 com.squareup.okhttp3:okhttp       5.4.0       5.5.0        ← semver, ni se entera
```

De los BOM habituales, solo `compose-bom` usa fecha; `firebase-bom`, `okhttp-bom` y
`kotlin-bom` usan semver. Y al revés: una librería normal con versión de tipo fecha
también entraría por la rama de meses.

### Fijar el criterio del equipo

Como son flags, para no repetirlos envuélvelos en un script del proyecto:

```bash
#!/bin/bash
# scripts/deps.sh — criterio acordado por el equipo
exec ./check-dependencies.sh ./gradle --patch-threshold 2 --calver-months 4 "$@"
```

## 🤖 Uso en CI

La herramienta **informa, no bloquea**: siempre sale con código 0 salvo que el análisis
en sí falle (falta el `libs.versions.toml`, o es inválido). Un job que la ejecute no se
pondrá rojo porque haya dependencias viejas; genera el informe y lo publica.

```yaml
- name: Analizar dependencias
  run: ./check-dependencies.sh ./gradle --quiet

- name: Publicar informe
  uses: actions/upload-artifact@v4
  with:
    name: dependency-status
    path: dependency_status.json
```

El JSON incluye `status_code` (`ok`, `patch`, `minor`, `major`, `prerelease`, `managed`,
`unknown`), pensado para que otro paso lo procese: publicarlo como comentario, alimentar
un dashboard o abrir tickets.

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
| `status_code` | Versión legible por máquina del `status`: `ok`, `patch`, `minor`, `major`, `prerelease`, `managed`, `unknown`. |

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

| | `status_code` | Significado |
|---|---|---|
| 🔴 | `major` | Cambio de versión mayor, o BOM de fecha muy retrasado |
| 🟡 | `minor` / `patch` | Versión menor, o parches por encima del umbral |
| 🟡 | `prerelease` | Estás en un alpha/beta/rc y ya salió la versión final |
| 🟢 | `ok` | Igual, más nueva, o diferencia por debajo del umbral |
| ⚪ | `managed` | La versión la fija un BOM, no se actualiza por separado |
| ⚫ | `unknown` | No se pudo consultar o interpretar la versión |

Los umbrales y el orden de decisión están detallados en
la sección **Cómo se decide el color**.

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

`compose-bom` no usa semver sino la fecha: `2026.08.00`. Comparándolo por
major/minor/patch pasaban dos cosas, ambas mal: dentro del mismo año se quedaba en 🟡
para siempre por muchos meses que acumulara, y al cruzar de año saltaba a 🔴 aunque solo
hubiera un mes de diferencia — todos los BOM en rojo cada enero.

Cuando el primer componente es un año, la distancia se mide en **meses**. Ver
[`--calver-months`](#--calver-months).

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

Si encuentras algún bug o tienes una sugerencia, por favor abre un [issue](https://github.com/pfranccino/toml-deps-checker/issues).
