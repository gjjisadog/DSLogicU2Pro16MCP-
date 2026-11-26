import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class StdioSmokeTests(unittest.TestCase):
    def test_initialize_and_list_tools(self) -> None:
        root = Path(__file__).resolve().parents[1]
        patch = json.loads(
            subprocess.check_output(
                [
                    sys.executable, "-m", "mcp_server.server", "--print-dsh-patch",
                    "--app-root", str(root),
                ],
                cwd=root,
                text=True,
                timeout=15,
            )
        )
        (operation,) = patch
        (plugin,) = operation["insert"]
        self.assertEqual(plugin["id"], "mcp-dslogic-u2pro16")
        self.assertEqual(plugin["name"], "@deepseek-ai/dsh-mcp-client")
        config = plugin["config"]
        self.assertEqual(config["serverName"], "dslogic-u2pro16")
        self.assertEqual(config["transport"], "stdio")
        self.assertEqual(config["command"], sys.executable)
        self.assertEqual(config["env"], {"DSLOGIC_HOME": str(root)})
        process = subprocess.Popen(
            [config["command"], *config["args"]],
            cwd=config["cwd"],
            env={**os.environ, **config["env"]},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert process.stdin is not None
            assert process.stdout is not None
            initialize = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            }
            process.stdin.write(json.dumps(initialize) + "\n")
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            self.assertEqual(response["id"], 1)
            self.assertEqual(response["result"]["serverInfo"]["name"], "dslogic-u2pro16")

            process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
            process.stdin.flush()
            tools_response = json.loads(process.stdout.readline())
            names = {tool["name"] for tool in tools_response["result"]["tools"]}
            self.assertEqual(
                names,
                {
                    "logic_device_info",
                    "logic_capture",
                    "logic_measure_pwm",
                    "logic_measure_deadtime",
                },
            )
        finally:
            process.terminate()
            process.wait(timeout=5)
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
