"""Build a public release from an explicit source allowlist, never runtime data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile


def release_files(project):
    roots = ("src", "gradle", "tools", "docs", ".github")
    names = ("AGENTS.md", "README.md", "LICENSE", "TEMPLATE_LICENSE.txt", "CONTRIBUTING.md",
             "SECURITY.md", "CHANGELOG.md", "build-local.ps1", "build.gradle", "gradle.properties",
             "settings.gradle", "gradlew", "gradlew.bat", ".gitignore", ".gitattributes")
    allowed = {".java", ".toml", ".nbt", ".py", ".md", ".yml", ".yaml", ".properties"}
    files = [project / name for name in names]
    for root in roots:
        for path in (project / root).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                if path.name in ("token.txt", "connection.json") or path.suffix in (".db", ".sqlite3"):
                    raise ValueError("Private runtime file found in release source directories")
                if path.suffix in allowed or path.relative_to(project).as_posix() == "gradle/wrapper/gradle-wrapper.jar":
                    files.append(path)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    project = Path(__file__).resolve().parents[1]
    parser.add_argument("--output", type=Path, default=project / "dist")
    args = parser.parse_args()
    version = re.search(r"version = '([^']+)'", (project / "build.gradle").read_text()).group(1)
    jar = project / "build" / "libs" / f"voxelscope-{version}.jar"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar) as archive:
        if any("GameTest" in name or "RemovalTest" in name or name.startswith("data/") for name in archive.namelist()):
            raise ValueError("Test fixtures found in production JAR")
        if any(name.startswith(("appeng/", "mekanism/")) for name in archive.namelist()):
            raise ValueError("Third-party mod classes found in production JAR")
    destination = output / jar.name
    shutil.copy2(jar, destination)
    files = release_files(project)
    source = output / f"VoxelScope-{version}-source.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "voxelscope/" + path.relative_to(project).as_posix())
    companion = output / f"VoxelScope-{version}-companion.zip"
    with zipfile.ZipFile(companion, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(project)
            if relative.parts[0] in ("tools", "docs") and not path.name.startswith("test_") and path.name != "package_release.py" or str(relative) in ("README.md", "LICENSE", "CHANGELOG.md"):
                archive.write(path, relative.as_posix())
    manifest = {"name": "VoxelScope", "version": version, "minecraft": "1.21.1", "neoforge": "[21.1.233,21.2)",
                "artifacts": {path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
                              for path in (destination, source, companion)}}
    (output / f"VoxelScope-{version}-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
