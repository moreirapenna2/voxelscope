"""Bounded, credential-safe connection checks. Never creates runtime files."""
import re
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError


def installed_bridges(instance):
    found = []
    mods = Path(instance) / "mods"
    if not mods.is_dir():
        return found
    for jar in sorted(mods.iterdir()):
        if jar.suffix != ".jar" or not jar.name.lower().startswith(("voxelscope", "stoneblock-bridge")):
            continue
        row = {"file": jar.name, "id": "unknown", "version": "unknown"}
        try:
            with zipfile.ZipFile(jar) as archive:
                info = archive.getinfo("META-INF/neoforge.mods.toml")
                if info.file_size > 32768:
                    raise ValueError()
                text = archive.read(info).decode("utf-8")
            section = re.search(r"(?ms)^\[\[mods\]\]\s*(.*?)(?=^\[\[|\Z)", text)
            if not section:
                raise ValueError()
            for key, field in (("modId", "id"), ("version", "version")):
                value = re.search(r'^' + key + r'\s*=\s*"([^"\n]{1,128})"', section[1], re.M)
                if value:
                    row[field] = value[1]
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            row["metadata"] = "unreadable"
        found.append(row)
        if len(found) == 32:
            break
    return found


def diagnose(instance, query_fn):
    instance = Path(instance)
    result = {"status": "needs_attention", "instance_exists": instance.is_dir(),
              "installed_bridges": installed_bridges(instance), "api_connection": "not_checked"}
    if not instance.is_dir():
        result["hint"] = "Select the instance/server directory containing mods, using --instance."
        return result
    bridges = result["installed_bridges"]
    conflicts = len(bridges) > 1 or any(r["id"] == "stonebridge" for r in bridges)
    if conflicts:
        result["installation_issue"] = "legacy_or_multiple_bridges"
    try:
        status = query_fn("status", {})
        if not isinstance(status, dict):
            raise ValueError("Invalid status response")
        if status.get("api_version") != 1 or status.get("name") != "VoxelScope" or status.get("read_only") is not True:
            result["api_connection"] = "incompatible_api"
            result["hint"] = "Use matching VoxelScope mod and companion versions."
            return result
        result.update(api_connection="connected", status="needs_attention" if conflicts else "ready",
                      version=status.get("bridge_version"), minecraft=status.get("minecraft"), world_loaded=True,
                      integrations={key: status.get(key, False) for key in (
                          "ae2_integration", "mekanism_capabilities_integration", "mekanism_matrix_integration", "mekanism_integration")})
        if not bridges:
            result["installation_note"] = "Connected without a recognized JAR in mods (for example a development run)."
        if conflicts:
            result["hint"] = "Close Minecraft and keep only the intended VoxelScope JAR; remove the legacy bridge."
    except FileNotFoundError:
        result.update(status="not_connected", api_connection="no_runtime_files",
                      hint=("Start Minecraft/server and load a world. Check --instance or restart if it is already running." if bridges else "Install VoxelScope, start Minecraft/server, and load a world. Check --instance if it is already running."))
    except HTTPError as error:
        result["api_connection"] = {401: "authentication_failed", 503: "game_thread_unavailable_or_paused"}.get(error.code, "http_error")
        result["http_status"] = error.code
        result["hint"] = "Unpause/load the world, or restart Minecraft to refresh the connection files."
    except (URLError, TimeoutError, ConnectionError):
        result.update(status="not_connected", api_connection="unreachable",
                      hint="No response from the saved local address. Start/load the world; a previous session may have left stale connection metadata.")
    except (OSError, ValueError, KeyError, TypeError):
        result.update(api_connection="invalid_runtime_files", hint="Check the instance path, or restart Minecraft to regenerate connection metadata. Never share token.txt.")
    return result
