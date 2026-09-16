"""Agent configuration helpers for the portable DSLogic MCP distribution.

The MCP protocol is shared by the supported hosts, but each host stores a
stdio server definition in a different file.  This module keeps those small
format adapters in one place and makes installation idempotent.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


SERVER_NAME = "dslogic-u2pro16"
MANAGED_BEGIN = "# BEGIN DSLOGIC-U2PRO16-MCP (managed by installer)"
MANAGED_END = "# END DSLOGIC-U2PRO16-MCP"


class ConfigError(RuntimeError):
    """Raised when an existing host configuration cannot be safely updated."""


def application_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Return the directory containing the portable application and runtime."""

    if explicit:
        return Path(explicit).expanduser().resolve()

    configured = os.environ.get("DSLOGIC_HOME")
    if configured:
        return Path(configured).expanduser().resolve()

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent.parent


def _user_home() -> Path:
    """Resolve the current user's profile without relying on shell aliases."""

    profile = os.environ.get("USERPROFILE")
    if profile:
        return Path(profile).expanduser().resolve()
    return Path.home().resolve()


def _entry(
    app_root: Path,
    executable: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Build a host-neutral stdio entry with absolute paths."""

    candidate = Path(executable).expanduser().resolve() if executable else None
    if candidate is None:
        frozen_executable = getattr(sys, "frozen", False)
        bundled_executable = app_root / "dslogic-mcp.exe"
        if frozen_executable:
            candidate = Path(sys.executable).resolve()
        elif bundled_executable.exists():
            candidate = bundled_executable.resolve()

    if candidate is not None:
        command = str(candidate)
        args: list[str] = []
    else:
        command = str(Path(sys.executable).resolve())
        args = ["-m", "mcp_server.server"]

    # DSLOGIC_HOME makes the same definition work regardless of the host's
    # current working directory.  It also keeps captures out of a project
    # checkout when the portable bundle is installed per-user.
    return {
        "command": command,
        "args": args,
        "env": {"DSLOGIC_HOME": str(app_root)},
        "cwd": str(app_root),
    }


def config_paths(home: Path | None = None) -> dict[str, Path]:
    """Return supported host configuration paths for a user profile."""

    root = (home or _user_home()).resolve()
    return {
        "claude": root / ".claude.json",
        "codex": root / ".codex" / "config.toml",
        "zcode": root / ".zcode" / "cli" / "config.json",
        "agents": root / ".agents" / "mcp.json",
    }


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.dslogic.bak")
    shutil.copy2(path, backup)
    return backup


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot read JSON configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"JSON configuration root must be an object: {path}")
    return value


def _write_json_entry(
    path: Path,
    key_path: Iterable[str],
    entry: Mapping[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any]:
    if entry is None and not path.exists():
        return {
            "target": path.name,
            "path": str(path),
            "action": "absent",
            "changed": False,
        }
    data = _read_json(path)
    current: dict[str, Any] = data
    keys = list(key_path)
    for key in keys:
        value = current.get(key)
        if value is None:
            if entry is None:
                return {
                    "target": path.name,
                    "path": str(path),
                    "action": "absent",
                    "changed": False,
                }
            value = {}
            current[key] = value
        if not isinstance(value, dict):
            raise ConfigError(f"Expected object at {key} in {path}")
        current = value

    changed = False
    if entry is None:
        if SERVER_NAME in current:
            del current[SERVER_NAME]
            changed = True
            action = "removed"
        else:
            action = "absent"
    else:
        if current.get(SERVER_NAME) != dict(entry):
            current[SERVER_NAME] = dict(entry)
            changed = True
        action = "updated" if changed else "unchanged"

    backup = None
    if changed and not dry_run:
        backup = _backup(path)
        _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    result: dict[str, Any] = {
        "target": path.name,
        "path": str(path),
        "action": action,
        "changed": changed,
    }
    if backup:
        result["backup"] = str(backup)
    return result


def _toml_string(value: str) -> str:
    """Encode a value as a TOML basic string."""

    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\f", "\\f")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _codex_block(entry: Mapping[str, Any], newline: str) -> str:
    env = entry.get("env", {})
    env_items = ", ".join(
        f"{key} = {_toml_string(str(value))}"
        for key, value in sorted(env.items())
    )
    args = ", ".join(_toml_string(str(arg)) for arg in entry.get("args", []))
    lines = [
        MANAGED_BEGIN,
        f"[mcp_servers.{SERVER_NAME}]",
        f"command = {_toml_string(str(entry['command']))}",
        f"args = [{args}]",
        f"env = {{ {env_items} }}",
        f"cwd = {_toml_string(str(entry['cwd']))}",
        MANAGED_END,
        "",
    ]
    return newline.join(lines)


def _section_name(line: str) -> str | None:
    match = re.match(r"^\s*\[([^\]]+)\]", line)
    return match.group(1).strip() if match else None


def _replace_codex_section(text: str, replacement: str | None) -> tuple[str, bool]:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    target = f"mcp_servers.{SERVER_NAME}"

    start: int | None = None
    end: int | None = None
    for index, line in enumerate(lines):
        section = _section_name(line)
        if section == target or (section and section.startswith(target + ".")):
            if start is None:
                start = index
            continue
        if start is not None and section is not None:
            end = index
            break

    if start is None:
        marker_re = re.compile(
            rf"(?ms)^{re.escape(MANAGED_BEGIN)}\r?\n.*?^{re.escape(MANAGED_END)}\r?\n?"
        )
        marker_match = marker_re.search(text)
        if marker_match:
            new_text = text[: marker_match.start()]
            if replacement:
                new_text += replacement
            new_text += text[marker_match.end() :]
            return new_text, new_text != text
        if replacement is None:
            return text, False
        prefix = text
        if prefix and not prefix.endswith(("\n", "\r")):
            prefix += newline
        if prefix and not prefix.endswith(newline * 2):
            prefix += newline
        new_text = prefix + replacement
        return new_text, new_text != text

    if end is None:
        end = len(lines)
    if start > 0 and lines[start - 1].strip() == MANAGED_BEGIN:
        start -= 1
    new_lines = lines[:start]
    if replacement:
        new_lines.append(replacement)
    new_lines.extend(lines[end:])
    new_text = "".join(new_lines)
    return new_text, new_text != text


def _write_codex_config(
    path: Path,
    entry: Mapping[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any]:
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Cannot read TOML configuration {path}: {exc}") from exc
    else:
        text = ""

    newline = "\r\n" if "\r\n" in text else "\n"
    replacement = _codex_block(entry, newline) if entry is not None else None
    updated, changed = _replace_codex_section(text, replacement)
    if changed and not dry_run:
        backup = _backup(path)
        _atomic_write(path, updated)
    else:
        backup = None

    if entry is None:
        action = "removed" if changed else "absent"
    else:
        action = "updated" if changed else "unchanged"
    result: dict[str, Any] = {
        "target": path.name,
        "path": str(path),
        "action": action,
        "changed": changed,
    }
    if backup:
        result["backup"] = str(backup)
    return result


def _normalise_targets(targets: Iterable[str] | str | None) -> set[str]:
    if targets is None:
        return {"claude", "codex", "zcode", "agents"}
    if isinstance(targets, str):
        values = {item.strip().lower() for item in targets.split(",") if item.strip()}
    else:
        values = {str(item).strip().lower() for item in targets if str(item).strip()}
    if "all" in values:
        return {"claude", "codex", "zcode", "agents"}
    aliases = {"generic": "agents", "zed": "agents"}
    values = {aliases.get(value, value) for value in values}
    unknown = values - {"claude", "codex", "zcode", "agents"}
    if unknown:
        raise ConfigError(f"Unsupported target(s): {', '.join(sorted(unknown))}")
    return values


def install_agent_configs(
    *,
    app_root: str | os.PathLike[str] | None = None,
    executable: str | os.PathLike[str] | None = None,
    home: str | os.PathLike[str] | None = None,
    targets: Iterable[str] | str | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Install or update the server entry in selected Agent configs."""

    root = application_root(app_root)
    entry = _entry(root, executable)
    paths = config_paths(Path(home).expanduser() if home else None)
    selected = _normalise_targets(targets)
    results: list[dict[str, Any]] = []

    if "claude" in selected:
        results.append(_write_json_entry(paths["claude"], ["mcpServers"], entry, dry_run))
    if "agents" in selected:
        results.append(_write_json_entry(paths["agents"], ["mcpServers"], entry, dry_run))
    if "zcode" in selected:
        results.append(_write_json_entry(paths["zcode"], ["mcp", "servers"], entry, dry_run))
    if "codex" in selected:
        results.append(_write_codex_config(paths["codex"], entry, dry_run))
    return results


def uninstall_agent_configs(
    *,
    home: str | os.PathLike[str] | None = None,
    targets: Iterable[str] | str | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Remove only the managed server entry from selected Agent configs."""

    paths = config_paths(Path(home).expanduser() if home else None)
    selected = _normalise_targets(targets)
    results: list[dict[str, Any]] = []
    if "claude" in selected:
        results.append(_write_json_entry(paths["claude"], ["mcpServers"], None, dry_run))
    if "agents" in selected:
        results.append(_write_json_entry(paths["agents"], ["mcpServers"], None, dry_run))
    if "zcode" in selected:
        results.append(_write_json_entry(paths["zcode"], ["mcp", "servers"], None, dry_run))
    if "codex" in selected:
        results.append(_write_codex_config(paths["codex"], None, dry_run))
    return results


def config_preview(
    *,
    app_root: str | os.PathLike[str] | None = None,
    executable: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return the generated host definitions without changing user files."""

    root = application_root(app_root)
    entry = _entry(root, executable)
    return {
        "server_name": SERVER_NAME,
        "transport": "stdio",
        "entry": entry,
        "paths": {name: str(path) for name, path in config_paths().items()},
    }
