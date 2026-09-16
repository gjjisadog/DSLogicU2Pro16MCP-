import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from mcp_server.config import (
    SERVER_NAME,
    _replace_codex_section,
    install_agent_configs,
    uninstall_agent_configs,
)


class ConfigInstallerTests(unittest.TestCase):
    def test_install_is_idempotent_and_preserves_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            claude = home / ".claude.json"
            claude.write_text(
                json.dumps({"existing": True, "mcpServers": {"other": {"command": "x"}}}),
                encoding="utf-8",
            )

            first = install_agent_configs(
                app_root=home / "app",
                executable=home / "app" / "dslogic-mcp.exe",
                home=home,
                targets="claude",
            )
            second = install_agent_configs(
                app_root=home / "app",
                executable=home / "app" / "dslogic-mcp.exe",
                home=home,
                targets="claude",
            )

            data = json.loads(claude.read_text(encoding="utf-8"))
            self.assertTrue(data["existing"])
            self.assertIn("other", data["mcpServers"])
            self.assertIn(SERVER_NAME, data["mcpServers"])
            self.assertTrue(first[0]["changed"])
            self.assertFalse(second[0]["changed"])
            self.assertTrue((home / ".claude.json.dslogic.bak").exists())

    def test_codex_section_replaces_managed_section_without_duplicates(self) -> None:
        entry = {
            "command": r"C:\Apps\dslogic-mcp.exe",
            "args": [],
            "env": {"DSLOGIC_HOME": r"C:\Apps\DSLogic"},
            "cwd": r"C:\Apps\DSLogic",
        }
        from mcp_server.config import _codex_block

        block = _codex_block(entry, "\n")
        original = (
            "[mcp_servers.other]\ncommand = \"x\"\n"
            + block
            + "command = 'stale'\n"
            + "[mcp_servers.dslogic-u2pro16.env]\nDSLOGIC_HOME = 'stale'\n"
            + "[mcp_servers.after]\ncommand = \"y\"\n"
        )
        updated, changed = _replace_codex_section(original, block)
        self.assertTrue(changed)
        self.assertEqual(updated.count(f"[mcp_servers.{SERVER_NAME}]"), 1)
        self.assertEqual(updated.count("[mcp_servers.other]"), 1)
        self.assertEqual(updated.count("command = 'stale'"), 0)
        parsed = tomllib.loads(updated)
        self.assertEqual(parsed["mcp_servers"][SERVER_NAME]["command"], entry["command"])

        unchanged, changed = _replace_codex_section(updated, block)
        self.assertFalse(changed)
        self.assertEqual(unchanged, updated)

        removed, changed = _replace_codex_section(updated, None)
        self.assertTrue(changed)
        self.assertNotIn(SERVER_NAME, removed)
        self.assertIn("[mcp_servers.other]", removed)
        self.assertIn("[mcp_servers.after]", removed)
        tomllib.loads(removed)

    def test_uninstall_does_not_create_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            results = uninstall_agent_configs(home=home, targets="all")
            self.assertEqual(len(results), 4)
            self.assertFalse((home / ".claude.json").exists())
            self.assertFalse((home / ".codex" / "config.toml").exists())


if __name__ == "__main__":
    unittest.main()
