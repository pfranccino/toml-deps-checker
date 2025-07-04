#!/usr/bin/env python3
import requests
import json
import os
from datetime import datetime
import re
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any

class MavenVersionChecker:
   def __init__(self):
       self.maven_search_url = "https://search.maven.org/solrsearch/select"
       print("Iniciando MavenVersionChecker...")

   def is_google_dependency(self, group_id: str) -> bool:
       google_groups = [
           'com.google.',
           'androidx.',
           'android.arch.',
           'com.android.',
           'com.google.android',
           'com.google.firebase'
       ]
       return any(group_id.startswith(prefix) for prefix in google_groups)

   def get_google_version(self, group_id: str, artifact_id: str) -> Optional[str]:
       try:
           path_group = group_id.replace('.', '/')
           google_url = f"https://dl.google.com/android/maven2/{path_group}/{artifact_id}/maven-metadata.xml"
           print(f"🔍 Consultando Google Maven: {google_url}")

           response = requests.get(google_url, timeout=5)
           if response.status_code != 200:
               print(f"❌ Error en respuesta de Google Maven: {response.status_code}")
               return None

           root = ET.fromstring(response.content)
           versioning = root.find('versioning')
           if versioning is not None:
               # Primero intentamos obtener 'release'
               release = versioning.find('release')
               if release is not None:
                   print(f"✅ Versión release encontrada en Google Maven: {release.text}")
                   return release.text

               # Si no hay 'release', intentamos con 'latest'
               latest = versioning.find('latest')
               if latest is not None:
                   print(f"✅ Versión latest encontrada en Google Maven (no se encontró release): {latest.text}")
                   return latest.text

           print("⚠️ No se encontró versión en Google Maven")
           return None

       except Exception as e:
           print(f"❌ Error consultando Google Maven: {str(e)}")
           return None

   def get_latest_version(self, group_id: str, artifact_id: str) -> Optional[str]:
       if self.is_google_dependency(group_id):
           print(f"📦 Detectada dependencia de Google: {group_id}:{artifact_id}")
           google_version = self.get_google_version(group_id, artifact_id)
           if google_version:
               return google_version

       try:
           print(f"\n📦 Buscando versión más reciente en Maven Central para: {group_id}:{artifact_id}")
           params = {
               'q': f'g:{group_id} AND a:{artifact_id}',
               'core': 'gav',
               'rows': '1',
               'wt': 'json'
           }

           url = self.maven_search_url
           query_string = '&'.join([f'{k}={v}' for k, v in params.items()])
           full_url = f"{url}?{query_string}"
           print(f"🔍 URL de búsqueda Maven Central: {full_url}")

           response = requests.get(self.maven_search_url, params=params, timeout=5)
           print(f"📡 Código de respuesta: {response.status_code}")

           if response.status_code != 200:
               print(f"❌ Error en la respuesta: {response.status_code}")
               return None

           data = response.json()
           print(f"📥 Respuesta recibida: {json.dumps(data, indent=2)}")

           if (data.get('response', {}).get('docs') and 
               len(data['response']['docs']) > 0 and 
               'v' in data['response']['docs'][0]):

               latest = data['response']['docs'][0]['v']
               print(f"✅ Última versión encontrada en Maven Central: {latest}")
               return latest

           print(f"⚠️ No se encontraron versiones para {group_id}:{artifact_id}")
           return None

       except requests.Timeout:
           print(f"⏰ Timeout buscando {group_id}:{artifact_id}")
           return None
       except Exception as e:
           print(f"❌ Error buscando {group_id}:{artifact_id}: {str(e)}")
           return None

   def compare_versions(self, current: str, latest: str) -> str:
       """
       Determina el estado de la versión basado en la diferencia entre versiones.
       Returns:
       - 🔴 : Diferencia Major
       - 🟡 : Diferencia Minor o Patch > 5
       - 🟢 : Versiones iguales o Patch < 5
       - ⚫ : No se puede determinar (versión no encontrada o error)
       """
       print(f"\n🔄 Comparando versiones - Actual: {current}, Última: {latest}")

       # Si no se encontró la última versión o hay algún problema
       if not current or not latest or latest == "N/A":
           print("⚫ No se pueden comparar las versiones - versión no encontrada")
           return "⚫"

       try:
           current_parts = self._parse_version(current)
           latest_parts = self._parse_version(latest)

           if not current_parts or not latest_parts:
               print("⚫ Error al parsear las versiones")
               return "⚫"

           print(f"📊 Versión actual: {current_parts}")
           print(f"📊 Última versión: {latest_parts}")

           current_major, current_minor, current_patch = current_parts
           latest_major, latest_minor, latest_patch = latest_parts

           # Verificar si las versiones son exactamente iguales
           if current_parts == latest_parts:
               print("🟢 Versiones son exactamente iguales")
               return "🟢"

           # Diferencia en versión mayor (Major)
           if latest_major > current_major:
               print("🔴 Diferencia en versión mayor (Major)")
               return "🔴"

           # Diferencia en versión menor (Minor)
           if latest_minor > current_minor:
               print("🟡 Diferencia en versión menor (Minor)")
               return "🟡"

           # Diferencia en versión patch
           if latest_patch > current_patch:
               patch_diff = latest_patch - current_patch
               print(f"📊 Diferencia en patch: {patch_diff}")

               if patch_diff > 5:
                   print("🟡 Diferencia en patch > 5")
                   return "🟡"
               else:
                   print("🟢 Diferencia en patch ≤ 5")
                   return "🟢"

           # Si la versión actual es más nueva que la "latest" encontrada
           print("🟢 Versión actual es igual o más nueva")
           return "🟢"

       except Exception as e:
           print(f"❌ Error en comparación: {str(e)}")
           return "⚫"

   def _parse_version(self, version: str) -> Optional[tuple]:
       print(f"🔍 Parseando versión: {version}")
       try:
           # Remover prefijos como 'v' o 'V'
           version = re.sub(r'^[vV]', '', version)
           # Tomar solo la parte antes del primer '-' o '+'
           version = version.split('-')[0].split('+')[0]

           parts = version.split('.')
           # Asegurar que tenemos al menos 3 partes (major.minor.patch)
           if len(parts) < 3:
               parts.extend(['0'] * (3 - len(parts)))

           # Convertir a enteros solo las primeras 3 partes
           result = tuple(int(p) for p in parts[:3])
           print(f"✅ Versión parseada: {result}")
           return result
       except Exception as e:
           print(f"❌ Error parseando versión {version}: {str(e)}")
           return None

   def parse_library_line(self, line: str, versions: dict) -> Optional[tuple]:
       print(f"\n📝 Procesando línea: {line}")
       try:
           if '=' in line:
               key, content = line.split('=', 1)
               key = key.strip()
               print(f"🔑 Key encontrada: {key}")

               # Check for module format
               if 'module' in content:
                   module_match = re.search(r'module\s*=\s*"([^"]+)"', content)
                   version_ref_match = re.search(r'version\.ref\s*=\s*"([^"]+)"', content)

                   if module_match and version_ref_match:
                       module = module_match.group(1)
                       version_ref = version_ref_match.group(1)
                       print(f"📦 Módulo: {module}")
                       print(f"🏷️ Referencia de versión: {version_ref}")

                       current_version = versions.get(version_ref)
                       if current_version:
                           current_version = current_version.strip('"')
                           group_id, artifact_id = module.split(':', 1)
                           print(f"✅ Parseado - Group: {group_id}, Artifact: {artifact_id}, Version: {current_version}")
                           return group_id, artifact_id, current_version
                       else:
                           print(f"⚠️ No se encontró la versión para la referencia: {version_ref}")

               # Check for group and name format
               elif 'group' in content and 'name' in content:
                   group_match = re.search(r'group\s*=\s*"([^"]+)"', content)
                   name_match = re.search(r'name\s*=\s*"([^"]+)"', content)
                   version_ref_match = re.search(r'version\.ref\s*=\s*"([^"]+)"', content)

                   if group_match and name_match and version_ref_match:
                       group_id = group_match.group(1)
                       artifact_id = name_match.group(1)
                       version_ref = version_ref_match.group(1)

                       # Construct module as group + ":" + name
                       module = f"{group_id}:{artifact_id}"
                       print(f"📦 Módulo construido: {module}")
                       print(f"🏷️ Referencia de versión: {version_ref}")

                       current_version = versions.get(version_ref)
                       if current_version:
                           current_version = current_version.strip('"')
                           print(f"✅ Parseado - Group: {group_id}, Artifact: {artifact_id}, Version: {current_version}")
                           return group_id, artifact_id, current_version
                       else:
                           print(f"⚠️ No se encontró la versión para la referencia: {version_ref}")

           return None
       except Exception as e:
           print(f"❌ Error parseando línea: {str(e)}")
           return None

   def process_toml_file(self, folder_path: str) -> Dict[str, Any]:
       print(f"\n📂 Procesando directorio: {folder_path}")
       result = {}
       timestamp = datetime.now().isoformat()
       file_path = os.path.join(folder_path, "libs.versions.toml")

       try:
           if not os.path.exists(file_path):
               print(f"❌ No se encontró el archivo libs.versions.toml en: {folder_path}")
               return {}

           versions = {}
           in_versions_section = False
           print(f"📖 Primera pasada: leyendo versiones del archivo: {file_path}")

           with open(file_path, 'r', encoding='utf-8') as f:
               for line in f:
                   line = line.strip()
                   if not line or line.startswith('#'):
                       continue

                   if line == '[versions]':
                       print("✅ Sección [versions] encontrada")
                       in_versions_section = True
                       continue
                   elif line.startswith('['):
                       in_versions_section = False
                       continue

                   if in_versions_section and '=' in line:
                       key, value = line.split('=', 1)
                       versions[key.strip()] = value.strip()
                       print(f"📝 Versión encontrada - {key.strip()}: {value.strip()}")

           print(f"\n📖 Segunda pasada: procesando librerías")
           in_libraries_section = False

           with open(file_path, 'r', encoding='utf-8') as f:
               for line in f:
                   line = line.strip()
                   if not line or line.startswith('#'):
                       continue

                   if line == '[libraries]':
                       print("✅ Sección [libraries] encontrada")
                       in_libraries_section = True
                       continue
                   elif line.startswith('['):
                       in_libraries_section = False
                       continue

                   if in_libraries_section:
                       parsed = self.parse_library_line(line, versions)
                       if parsed:
                           group_id, artifact_id, current_version = parsed
                           dep_key = f"{group_id}:{artifact_id}"
                           print(f"\n📦 Procesando dependencia: {dep_key}")

                           latest_version = self.get_latest_version(group_id, artifact_id)
                           status = self.compare_versions(current_version, latest_version)

                           # Determinar tipo y URL basado en si es dependencia de Google
                           if self.is_google_dependency(group_id):
                               dep_type = "google"
                               url = f"https://maven.google.com/web/index.html#{group_id}"
                           else:
                               dep_type = "maven"
                               url = f"https://central.sonatype.com/artifact/{group_id}/{artifact_id}"

                           result[dep_key] = {
                               "url": url,
                               "version_used": current_version,
                               "latest_version": latest_version or "N/A",
                               "timestamp": timestamp,
                               "status": status,
                               "type": dep_type
                           }
                           print(f"✅ Resultado para {dep_key}:")
                           print(json.dumps(result[dep_key], indent=2))

       except Exception as e:
           print(f"❌ Error procesando archivo: {str(e)}")
           return {}

       print(f"\n✅ Proceso completado. Total de dependencias: {len(result)}")
       return result

def main():
   import sys

   print("\n🚀 Iniciando verificador de versiones Maven")

   if len(sys.argv) != 2:
       print("❌ Error: Falta la ruta del directorio")
       print("Uso: python script.py ruta/al/directorio")
       sys.exit(1)

   folder_path = sys.argv[1]
   print(f"📂 Directorio a procesar: {folder_path}")

   checker = MavenVersionChecker()
   result = checker.process_toml_file(folder_path)

   # Obtener la ruta donde está el script
   script_dir = os.path.dirname(os.path.abspath(__file__))
   output_file = os.path.join(script_dir, "dependency_status.json")
   print(f"\n💾 Guardando resultados en: {output_file}")

   with open(output_file, 'w', encoding='utf-8') as f:
       json.dump(result, f, indent=2, ensure_ascii=False)

   print("✅ Proceso completado exitosamente")

if __name__ == "__main__":
   main()
