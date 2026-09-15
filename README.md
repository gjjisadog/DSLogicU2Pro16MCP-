# DSLogic U2Pro16 MCP

DSLogic U2Pro16 MCP exposes DreamSourceLab logic-analyzer capture and PWM
analysis through the standard Model Context Protocol (MCP). The same server
works with Claude Code, ZCode, Codex, Zed, Cursor, OpenCode, and other clients
that support MCP.

The repository ships a Windows x64 native runtime because the bundled
DSLogic driver backend uses WinUSB. Agent compatibility is cross-client;
hardware support is currently Windows-only.

## MCP tools

- `logic_device_info` — detect the analyzer and report its model/channel count.
- `logic_capture` — capture digital samples at a selected rate and duration.
- `logic_measure_pwm` — measure frequency, period, duty cycle, and high/low time.
- `logic_measure_deadtime` — measure complementary PWM deadtime and shoot-through.

The default transport is stdio, which is the most portable choice for local
Agents. The executable also supports `streamable-http` and `sse` for clients
that connect to a local endpoint:

```powershell
dslogic-mcp.exe --transport streamable-http --host 127.0.0.1 --port 8000
```

## Offline one-click installation

Download `DSLogicU2Pro16MCP-Setup.exe` from the GitHub Release and double-click
it. The installer contains the Python runtime, MCP SDK, NumPy, native CLI,
runtime DLLs, and firmware resources, so the installation itself does not need
Internet access or a Python installation.

The installer installs per-user under:

```text
%LOCALAPPDATA%\DSLogicU2Pro16MCP
```

It registers the server in the following files when they exist or can be
created, keeping a `.dslogic.bak` backup before changing an existing file:

| Client | Configuration |
| --- | --- |
| Claude Code | `%USERPROFILE%\.claude.json` → `mcpServers` |
| Codex | `%USERPROFILE%\.codex\config.toml` → `mcp_servers.dslogic-u2pro16` |
| ZCode native | `%USERPROFILE%\.zcode\cli\config.json` → `mcp.servers` |
| Generic / ZCode compatibility | `%USERPROFILE%\.agents\mcp.json` → `mcpServers` |

Restart the Agent after installation. The WinUSB driver is not included; it
must be installed separately when Windows has not already associated the
device with WinUSB.

For a portable ZIP installation, extract the archive and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-DSLogicU2Pro16MCP.ps1
```

To remove only the Agent registrations:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-DSLogicU2Pro16MCP.ps1 -Uninstall
```

## Manual configuration

The executable prints the exact definitions it would generate without
modifying user files:

```powershell
dslogic-mcp.exe --print-config
```

Claude Code can also register it directly:

```powershell
claude mcp add --transport stdio --scope user dslogic-u2pro16 -- `
  "$env:LOCALAPPDATA\DSLogicU2Pro16MCP\dslogic-mcp.exe"
```

Codex uses `~/.codex/config.toml`:

```toml
[mcp_servers.dslogic-u2pro16]
command = "C:\\Users\\<user>\\AppData\\Local\\DSLogicU2Pro16MCP\\dslogic-mcp.exe"
args = []
env = { DSLOGIC_HOME = "C:\\Users\\<user>\\AppData\\Local\\DSLogicU2Pro16MCP" }
cwd = "C:\\Users\\<user>\\AppData\\Local\\DSLogicU2Pro16MCP"
```

ZCode and other clients supporting the `.agents` convention can use:

```json
{
  "mcpServers": {
    "dslogic-u2pro16": {
      "command": "C:\\Users\\<user>\\AppData\\Local\\DSLogicU2Pro16MCP\\dslogic-mcp.exe",
      "args": [],
      "env": {
        "DSLOGIC_HOME": "C:\\Users\\<user>\\AppData\\Local\\DSLogicU2Pro16MCP"
      },
      "cwd": "C:\\Users\\<user>\\AppData\\Local\\DSLogicU2Pro16MCP"
    }
  }
}
```

See [docs/agent-compatibility.md](docs/agent-compatibility.md) for the
configuration boundary and troubleshooting notes.

## Source development

Requirements: Windows 10/11 x64, Python 3.10+, and the WinUSB driver.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m mcp_server.server --check
python -m unittest discover -s tests -v
```

The native CLI is already included in `runtime/`. Rebuilding it requires
CMake, a C/C++ toolchain, and the DSView/libsigrok source dependency:

```powershell
.\build.ps1
```

To build the self-contained offline release artifacts on Windows:

```powershell
python -m pip install -r requirements-build.txt
.\packaging\build_offline.ps1 -Clean
```

The script produces a self-contained setup executable, a portable ZIP, and
SHA-256 checksums under `dist/`.

## References

- [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)
- [Claude Code MCP configuration](https://code.claude.com/docs/en/mcp)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference)
- [ZCode MCP configuration](https://zcode.z.ai/en/docs/mcp-services)
- [Zed MCP configuration](https://zed.dev/docs/ai/mcp)
