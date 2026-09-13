import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from mcp.server.mcpserver import MCPServer
from mcp_server.analysis import measure_pwm as analyze_pwm, measure_deadtime as analyze_deadtime

# Project root is parent of mcp_server directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = PROJECT_ROOT / "runtime" / "dslogic_cli.exe"

server = MCPServer("dslogic-u2pro16")

def run_cli_command(args: List[str], input_json: Optional[Dict[str, Any]] = None, timeout: float = 15.0) -> Dict[str, Any]:
    """Helper to run dslogic_cli.exe and parse stdout JSON."""
    if not CLI_PATH.exists():
        return {
            "ok": False,
            "error": f"dslogic_cli.exe not found at {CLI_PATH}. Please build native binary first."
        }
    
    cmd = [str(CLI_PATH)] + args
    config_file = None
    try:
        if input_json is not None:
            # Write temporary config in project root
            config_file = PROJECT_ROOT / f"_tmp_cfg_{os.getpid()}.json"
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(input_json, f)
            cmd.append(str(config_file))

        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )

        stdout = proc.stdout.strip()
        if not stdout:
            return {
                "ok": False,
                "error": f"No JSON output from dslogic_cli. Exit code: {proc.returncode}.",
                "stderr": proc.stderr.strip()
            }

        try:
            res = json.loads(stdout)
            return res
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": "Failed to parse dslogic_cli stdout as JSON.",
                "raw_stdout": stdout,
                "stderr": proc.stderr.strip()
            }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"dslogic_cli timed out after {timeout} seconds."
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Execution error: {str(e)}"
        }
    finally:
        if config_file and config_file.exists():
            try:
                config_file.unlink()
            except OSError:
                pass


@server.tool()
def logic_device_info() -> Dict[str, Any]:
    """
    Detect connected DSLogic U2Pro16 logic analyzer and retrieve device information.
    Returns connection status, hardware model, and channel count.
    """
    return run_cli_command(["info"])


@server.tool()
def logic_capture(
    sample_rate_hz: int = 100_000_000,
    duration_us: int = 2000,
    channels: List[int] = [0, 1],
    trigger_channel: int = -1,
    trigger_edge: str = "none",
) -> Dict[str, Any]:
    """
    Configure and execute a digital logic capture on DSLogic U2Pro16.
    
    Parameters:
    - sample_rate_hz: Sampling frequency in Hz (e.g., 100000000 for 100MHz, 20000000 for 20MHz).
    - duration_us: Capture duration in microseconds (e.g., 2000 for 2ms).
    - channels: List of digital channels to enable (0-15), e.g. [0, 1].
    - trigger_channel: Channel index for trigger (-1 for immediate capture without trigger).
    - trigger_edge: Trigger edge condition: "none", "rising", or "falling".
    
    Returns:
    - JSON object containing capture_id, sample_count, sample_rate_hz, and capture_dir path.
    """
    cfg = {
        "sample_rate_hz": sample_rate_hz,
        "duration_us": duration_us,
        "channels": channels,
        "trigger": {
            "channel": trigger_channel,
            "edge": trigger_edge
        }
    }
    return run_cli_command(["capture"], input_json=cfg, timeout=30.0)


@server.tool()
def logic_measure_pwm(
    capture_id: str,
    channel: int = 0
) -> Dict[str, Any]:
    """
    Measure PWM characteristics on a specific digital channel from a captured dataset.
    
    Parameters:
    - capture_id: The capture timestamp ID (or path) returned by logic_capture.
    - channel: The digital channel index (0-15) to analyze.
    
    Returns:
    - Frequency (Hz), period (us), duty cycle (%), high time (us), low time (us), and cycle count.
    """
    try:
        return analyze_pwm(capture_id, channel=channel, base_dir=str(PROJECT_ROOT / "captures"))
    except Exception as e:
        return {
            "ok": False,
            "error": f"PWM analysis failed: {str(e)}"
        }


@server.tool()
def logic_measure_deadtime(
    capture_id: str,
    high_channel: int = 0,
    low_channel: int = 1
) -> Dict[str, Any]:
    """
    Measure complementary PWM deadtime and detect bridge shoot-through overlap.
    
    Parameters:
    - capture_id: The capture timestamp ID (or path) returned by logic_capture.
    - high_channel: High-side switch channel index (e.g. 0).
    - low_channel: Low-side switch channel index (e.g. 1).
    
    Returns:
    - HS->LS deadtime stats (ns), LS->HS deadtime stats (ns), and shoot-through detection flag.
    """
    try:
        return analyze_deadtime(capture_id, high_ch=high_channel, low_ch=low_channel, base_dir=str(PROJECT_ROOT / "captures"))
    except Exception as e:
        return {
            "ok": False,
            "error": f"Deadtime analysis failed: {str(e)}"
        }


def main():
    """Main entrypoint for MCP stdio server."""
    server.run()


if __name__ == "__main__":
    main()
