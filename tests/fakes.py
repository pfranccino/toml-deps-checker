"""Repositorio Maven en memoria para probar sin red."""
from toml_deps_checker.maven import GOOGLE_MAVEN, MAVEN_CENTRAL, PLUGIN_PORTAL, MavenRepository

_BASES = (GOOGLE_MAVEN, MAVEN_CENTRAL, PLUGIN_PORTAL)


class FakeRepository(MavenRepository):
    """Sirve archivos por ruta relativa al repositorio: com/x/y/1.0/y-1.0.pom.

    El mismo archivo se sirve desde cualquiera de los repositorios.
    """

    def __init__(self, files: dict[str, str], **kwargs):
        super().__init__(retries=1, **kwargs)
        self.files = files
        self.requested: list[str] = []

    def _get(self, url: str) -> bytes | None:
        self.requested.append(url)
        for base in _BASES:
            if url.startswith(base + "/"):
                content = self.files.get(url[len(base) + 1:])
                return content.encode("utf-8") if content is not None else None
        return None


def metadata(*versions: str) -> str:
    items = "".join(f"<version>{v}</version>" for v in versions)
    return f"<metadata><versioning><versions>{items}</versions></versioning></metadata>"


def pom(
    group: str,
    artifact: str,
    version: str | None,
    parent: tuple[str, str, str] | None = None,
    properties: dict[str, str] | None = None,
    managed: list[dict[str, str]] = (),
) -> str:
    """Un POM con namespace, como los reales."""
    parts = ['<project xmlns="http://maven.apache.org/POM/4.0.0">']
    if parent:
        g, a, v = parent
        parts.append(f"<parent><groupId>{g}</groupId><artifactId>{a}</artifactId>"
                     f"<version>{v}</version></parent>")
    if group:
        parts.append(f"<groupId>{group}</groupId>")
    parts.append(f"<artifactId>{artifact}</artifactId>")
    if version:
        parts.append(f"<version>{version}</version>")
    if properties:
        parts.append("<properties>")
        parts.extend(f"<{k}>{v}</{k}>" for k, v in properties.items())
        parts.append("</properties>")
    if managed:
        parts.append("<dependencyManagement><dependencies>")
        for dep in managed:
            parts.append("<dependency>")
            parts.extend(f"<{k}>{v}</{k}>" for k, v in dep.items())
            parts.append("</dependency>")
        parts.append("</dependencies></dependencyManagement>")
    parts.append("</project>")
    return "".join(parts)


def pom_path(group: str, artifact: str, version: str) -> str:
    return f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.pom"
