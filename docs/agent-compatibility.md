# Agent compatibility

The server uses the MCP stdio transport by default. A host starts
`dslogic-mcp.exe` as a child process and exchanges JSON-RPC messages over its
standard input/output streams. Diagnostic messages are kept on stderr so the
protocol stream remains clean.

## Supported configuration adapters

The bundled installer writes the same server definition to each host's native
configuration shape:

| Host | File | Shape |
| --- | --- | --- |
| Claude Code | `%USERPROFILE%\\.claude.json` | `mcpServers.<name>` |
| Codex CLI | `%USERPROFILE%\\.codex\\config.toml` | `[mcp_servers.<name>]` |
| ZCode | `%USERPROFILE%\\.zcode\\cli\\config.json` | `mcp.servers.<name>` |
| `.agents` clients | `%USERPROFILE%\\.agents\\mcp.json` | `mcpServers.<name>` |

The generic `.agents` entry is also suitable for clients that consume the
common `mcpServers` JSON convention, including many IDE integrations.

The installer is idempotent. It updates only the `dslogic-u2pro16` entry and
creates a sibling `<file>.dslogic.bak` before changing an existing file. It
does not remove unrelated servers. `--uninstall` removes only this managed
entry.

## Source mode

When running from a source checkout, the generated stdio entry is equivalent
to:

```json
{
  "command": "<absolute path to python>",
  "args": ["-m", "mcp_server.server"],
  "cwd": "<absolute path to checkout>",
  "env": {"DSLOGIC_HOME": "<absolute path to checkout>"}
}
```

For a release bundle, the entry uses the absolute `dslogic-mcp.exe` path and
does not require Python, NumPy, or the MCP package to be installed.

## Local HTTP mode

Some MCP hosts prefer a URL. Start the local server with:

```powershell
dslogic-mcp.exe --transport streamable-http --host 127.0.0.1 --port 8000
```

The endpoint is `http://127.0.0.1:8000/mcp`. Keep the bind address on loopback
unless an explicit network deployment and authentication layer has been
added. The offline package does not expose the service to the LAN by default.

## Troubleshooting

1. Run `dslogic-mcp.exe --check` and confirm that the native CLI path exists.
2. Run `dslogic-mcp.exe --print-config` and compare the absolute path with the
   Agent configuration.
3. Restart the Agent after editing configuration. Project-scoped MCP entries
   may also require a trust/approval action in the host.
4. Confirm that the DSLogic device appears in Windows and that its driver is
   WinUSB. The MCP server cannot install a missing hardware driver silently.
5. If a host reports an empty tool list, launch the executable directly with
   `--help` and inspect the host's stderr/log panel; stdout must be reserved
   for MCP protocol traffic during a normal server run.
