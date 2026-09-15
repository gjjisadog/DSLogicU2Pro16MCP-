"""DSLogic U2Pro16 MCP server.

The protocol surface is intentionally host-neutral: Claude Code, ZCode,
Codex, Zed, Cursor, and other MCP clients can all launch this process over
stdio.  Streamable HTTP and SSE are also available for clients that connect
to a local endpoint instead of spawning a child process.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    # MCP SDK v2 (the current stable line).
    from mcp.server.mcpserver import MCPServer
except ImportError:  # pragma: no cover - compatibility with older SDKs
    from mcp.server.fastmcp import FastMCP as MCPServer

from mcp_server.analysis import (
    measure_deadtime as analyze_deadtime,
    measure_pwm as analyze_pwm,
)
from mcp_server.config import (
    SERVER_NAME,
    application_root,
    config_preview,
    install_agent_configs,
    uninstall_agent_configs,
)


APP_VERSION = os.environ.get("DSLOGIC_VERSION", "0.2.0")
APP_ROOT = application_root()
CAPTURE_DIR = (APP_ROOT / "captures").resolve()
CLI_PATH = Path(
    os.environ.get("DSLOGIC_CLI_PATH", str(APP_ROOT / "runtime" / "dslogic_cli.exe"))
).expanduser().resolve()

server = MCPServer(
    SERVER_NAME,
    version=APP_VERSION,
    description=(
        "Digital logic capture and PWM/deadtime analysis for DreamSourceLab "
        "DSLogic analyzers."
    ),
    instructions=(
        "Use logic_device_info before capture when hardware status is unknown. "
        "Capture IDs returned by logic_capture can be passed to the analysis tools."
    ),
)

_hardware_lock = threading.Lock()


def _error(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {"ok": False, "error_code": code, "error": message}
    result.update(extra)
    return result


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_capture_args(
    sample_rate_hz: int,
    duration_us: int,
    channels: List[int],
    trigger_channel: int,
    trigger_edge: str,
) -> Optional[Dict[str, Any]]:
    if not _is_int(sample_rate_hz) or sample_rate_hz <= 0:
        return _error("INVALID_SAMPLE_RATE", "sample_rate_hz must be a positive integer")
    if not _is_int(duration_us) or duration_us <= 0:
        return _error("INVALID_DURATION", "duration_us must be a positive integer")
    if not isinstance(channels, list) or not channels:
        return _error("INVALID_CHANNELS", "channels must be a non-empty list")
    if any(not _is_int(channel) or channel < 0 or channel > 15 for channel in channels):
        return _error("INVALID_CHANNELS", "channels must contain integers from 0 through 15")
    if len(set(channels)) != len(channels):
        return _error("INVALID_CHANNELS", "channels must not contain duplicates")
    if not _is_int(trigger_channel) or trigger_channel < -1 or trigger_channel > 15:
        return _error("INVALID_TRIGGER_CHANNEL", "trigger_channel must be -1 or an integer from 0 through 15")
    if trigger_edge not in {"none", "rising", "falling"}:
        return _error("INVALID_TRIGGER_EDGE", "trigger_edge must be none, rising, or falling")
    if trigger_channel == -1 and trigger_edge != "none":
        return _error("INVALID_TRIGGER", "trigger_edge must be none when trigger_channel is -1")
    if trigger_channel >= 0 and trigger_edge == "none":
        return _error("INVALID_TRIGGER", "trigger_edge must be rising or falling for a trigger channel")
    return None


def _subprocess_environment() -> Dict[str, str]:
    env = os.environ.copy()
    runtime_dir = str(CLI_PATH.parent)
    env["PATH"] = runtime_dir + os.pathsep + env.get("PATH", "")
    env.setdefault("DSLOGIC_HOME", str(APP_ROOT))
    return env


def run_cli_command(
    args: List[str],
    input_json: Optional[Dict[str, Any]] = None,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """Run the bundled native CLI and return its JSON response."""

    if not CLI_PATH.exists():
        return _error(
            "RUNTIME_NOT_FOUND",
            f"dslogic_cli.exe not found at {CLI_PATH}. Reinstall the portable package or rebuild the native runtime.",
            path=str(CLI_PATH),
        )

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    working_dir = CAPTURE_DIR.parent
    cmd = [str(CLI_PATH), *args]
    config_file: Optional[Path] = None
    try:
        if input_json is not None:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                prefix=".dslogic-config-",
                dir=str(working_dir),
                delete=False,
            ) as stream:
                json.dump(input_json, stream, ensure_ascii=False)
                config_file = Path(stream.name)
            cmd.append(str(config_file))

        proc = subprocess.run(
            cmd,
            cwd=str(working_dir),
            env=_subprocess_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        stdout = proc.stdout.strip()
        if not stdout:
            return _error(
                "CLI_NO_OUTPUT",
                f"No JSON output from dslogic_cli. Exit code: {proc.returncode}.",
                exit_code=proc.returncode,
                stderr=proc.stderr.strip(),
            )
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError:
            return _error(
                "CLI_INVALID_OUTPUT",
                "Failed to parse dslogic_cli stdout as JSON.",
                exit_code=proc.returncode,
                raw_stdout=stdout,
                stderr=proc.stderr.strip(),
            )
        if not isinstance(result, dict):
            return _error(
                "CLI_INVALID_OUTPUT",
                "dslogic_cli returned a JSON value instead of an object.",
                exit_code=proc.returncode,
            )
        if proc.returncode != 0 and result.get("ok") is True:
            result["ok"] = False
            result.setdefault("error_code", "CLI_EXITED_WITH_ERROR")
            result.setdefault("error", f"dslogic_cli exited with code {proc.returncode}")
        return result
    except subprocess.TimeoutExpired:
        return _error("CLI_TIMEOUT", f"dslogic_cli timed out after {timeout:g} seconds")
    except OSError as exc:
        return _error("CLI_EXECUTION_FAILED", f"Failed to execute dslogic_cli: {exc}")
    finally:
        if config_file:
            try:
                config_file.unlink()
            except OSError:
                pass


@server.tool()
def logic_device_info() -> Dict[str, Any]:
    """Detect a connected DSLogic analyzer and return model/channel information."""

    with _hardware_lock:
        return run_cli_command(["info"])


@server.tool()
def logic_capture(
    sample_rate_hz: int = 100_000_000,
    duration_us: int = 2000,
    channels: Optional[List[int]] = None,
    trigger_channel: int = -1,
    trigger_edge: str = "none",
) -> Dict[str, Any]:
    """Capture digital samples and persist them under the portable app's captures directory.

    ``channels`` accepts channel numbers 0 through 15.  The native runtime
    stores all 16 bits so later analysis can use channels that were not named
    in this display-level parameter.
    """

    selected_channels = list(channels) if channels is not None else [0, 1]
    validation_error = _validate_capture_args(
        sample_rate_hz,
        duration_us,
        selected_channels,
        trigger_channel,
        trigger_edge,
    )
    if validation_error:
        return validation_error

    config = {
        "sample_rate_hz": sample_rate_hz,
        "duration_us": duration_us,
        "channels": selected_channels,
        # Keep these fields flat: the bundled native parser consumes this
        # shape, and it is also easy to reproduce from non-Python clients.
        "trigger_channel": trigger_channel,
        "trigger_edge": trigger_edge,
    }
    with _hardware_lock:
        return run_cli_command(["capture"], input_json=config, timeout=30.0)


@server.tool()
def logic_measure_pwm(capture_id: str, channel: int = 0) -> Dict[str, Any]:
    """Measure frequency, period, duty cycle, and timing from one capture."""

    try:
        return analyze_pwm(capture_id, channel=channel, base_dir=str(CAPTURE_DIR))
    except Exception as exc:  # return tool-friendly errors instead of crashing the session
        return _error("PWM_ANALYSIS_FAILED", f"PWM analysis failed: {exc}")


@server.tool()
def logic_measure_deadtime(
    capture_id: str,
    high_channel: int = 0,
    low_channel: int = 1,
) -> Dict[str, Any]:
    """Measure complementary PWM deadtime and detect shoot-through overlap."""

    try:
        return analyze_deadtime(
            capture_id,
            high_ch=high_channel,
            low_ch=low_channel,
            base_dir=str(CAPTURE_DIR),
        )
    except Exception as exc:
        return _error("DEADTIME_ANALYSIS_FAILED", f"Deadtime analysis failed: {exc}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dslogic-mcp",
        description="DSLogic U2Pro16 MCP server and offline Agent installer",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP/SSE bind address")
    parser.add_argument("--port", type=int, default=8000, help="HTTP/SSE bind port")
    parser.add_argument("--install", action="store_true", help="register this server in Agent configs")
    parser.add_argument("--uninstall", action="store_true", help="remove this server from Agent configs")
    parser.add_argument("--print-config", action="store_true", help="print generated host configuration")
    parser.add_argument("--check", action="store_true", help="print a local installation health check")
    parser.add_argument(
        "--targets",
        default="all",
        help="comma-separated targets: claude,codex,zcode,agents,all (default: all)",
    )
    parser.add_argument("--app-root", help="portable app root used for config generation")
    parser.add_argument("--executable", help="absolute server executable used in generated configs")
    parser.add_argument("--home", help="user profile root used for config generation")
    parser.add_argument("--dry-run", action="store_true", help="show config changes without writing files")
    return parser


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.install and args.uninstall:
        print("--install and --uninstall cannot be used together", file=sys.stderr)
        return 2

    if args.install:
        try:
            _print_json(
                {
                    "ok": True,
                    "operation": "install",
                    "results": install_agent_configs(
                        app_root=args.app_root,
                        executable=args.executable,
                        home=args.home,
                        targets=args.targets,
                        dry_run=args.dry_run,
                    ),
                }
            )
            return 0
        except Exception as exc:
            _print_json({"ok": False, "operation": "install", "error": str(exc)})
            return 1

    if args.uninstall:
        try:
            _print_json(
                {
                    "ok": True,
                    "operation": "uninstall",
                    "results": uninstall_agent_configs(
                        home=args.home,
                        targets=args.targets,
                        dry_run=args.dry_run,
                    ),
                }
            )
            return 0
        except Exception as exc:
            _print_json({"ok": False, "operation": "uninstall", "error": str(exc)})
            return 1

    if args.print_config:
        _print_json(config_preview(app_root=args.app_root, executable=args.executable))
        return 0

    if args.check:
        _print_json(
            {
                "ok": CLI_PATH.exists(),
                "version": APP_VERSION,
                "server_name": SERVER_NAME,
                "app_root": str(APP_ROOT),
                "cli_path": str(CLI_PATH),
                "capture_dir": str(CAPTURE_DIR),
                "platform": sys.platform,
            }
        )
        return 0 if CLI_PATH.exists() else 1

    if args.transport == "stdio":
        server.run()
    else:
        server.run(transport=args.transport, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
