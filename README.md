# DSLogic U2Pro16 MCO Server

**DSLogic U2Pro16 MCP** is a Model Context Protocol (MCP) server for the **DreamSourceLab DSLogic U2Pro16** logic analyzer on Windows 10/11.


## 1. Core MCP Tools

1. `logic_device_info`: Detect DSLogic U2Pro16 connection status, hardware model, and channel count.
2. `logic_capture`: Set sampling rate (e.g. 100MHz, 20MHz), duration (us), channels (0-15), and trigger edge (none/rising/falling). Captures and persists raw uint16 samples to `captures/<capture_id>/`.
3. `logic_measure_pwm`: Calculate PWM frequency (Hz), period (us), duty cycle (%i, high time (us), low time (us), and cycle count from a capture.
4. `logic_measure_deadtime`: Calculate complementary PWM deadtime (HS fall to LS rise, LS fall to HS @rise in nanoseconds) and verify absence of shoot-through / bridge short-circuit.

---

## 2. Architecture


```o
  Coding Agent / MCP Client (Claude / Antigravity / Cursor)
         |  (stdio JSON-RPC)
         v
  MCP Server (Python: mcp_server/server.py)
         |
         +---> Analysis Engine (mcp_server/analysis.py via NumPy)
         |
         v  (subprocess stdout JSON)
  Native CLI (C/C++: runtime/dslogic_cli.exe)
         |
         v  (WinUSB / DSL library)
  DreamSourceLab DSLogic U2Pro16 Hardware
```

---

## 3. Quick Start

### Prerequisites
- Windows 10 / 11 64-bit
- DSLogic U2Pro16 USB Driver (WinUSB)
- Python 3.10+
- Clang / MinGW / CMake (optional, for rebuilding C++ runtime)

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Rebuild Native Runtime (Optional)
```powershell
\.\build.ps1
```

---

## 4. MCP Configuration

Add this server to your MCP client config (e.g., `settings.json` / `mcp_config.json`):

```json
{
  "mcpServers": {
    "dslogic": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "E:\\Project\\DSLogicU2Pro16MCP"
    }
  }
}
```
