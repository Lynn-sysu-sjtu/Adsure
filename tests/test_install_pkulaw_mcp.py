import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = ROOT / "tools" / "pkulaw_mcp" / "install.py"
SPEC = importlib.util.spec_from_file_location("pkulaw_mcp_installer", INSTALLER_PATH)
assert SPEC is not None and SPEC.loader is not None
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class PKULawMCPInstallerTests(unittest.TestCase):
    def test_installs_all_services_without_a_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            added = INSTALLER.install(project, "all")
            config_text = (project / ".codex" / "config.toml").read_text(
                encoding="utf-8"
            )

            self.assertEqual(len(added), 4)
            self.assertEqual(config_text.count("[mcp_servers.pkulaw-"), 4)
            self.assertEqual(
                config_text.count(
                    'bearer_token_env_var = "PKULAW_MCP_TOKEN"'
                ),
                4,
            )
            self.assertNotIn("Authorization", config_text)

    def test_preserves_existing_config_and_skips_existing_server(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            config_path = project / ".codex" / "config.toml"
            config_path.parent.mkdir()
            original = (
                'model = "example-model"\n\n'
                "[mcp_servers.pkulaw-law-keyword]\n"
                'url = "https://custom.example/mcp"\n'
            )
            config_path.write_text(original, encoding="utf-8")

            added = INSTALLER.install(project, "all")
            config_text = config_path.read_text(encoding="utf-8")

            self.assertTrue(config_text.startswith(original.rstrip()))
            self.assertNotIn("pkulaw-law-keyword", added)
            self.assertEqual(
                config_text.count("[mcp_servers.pkulaw-law-keyword]"), 1
            )
            self.assertIn('url = "https://custom.example/mcp"', config_text)

    def test_second_install_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            INSTALLER.install(project, "all")
            config_path = project / ".codex" / "config.toml"
            first_content = config_path.read_text(encoding="utf-8")

            added = INSTALLER.install(project, "all")

            self.assertEqual(added, [])
            self.assertEqual(
                config_path.read_text(encoding="utf-8"), first_content
            )

    def test_quoted_existing_server_name_is_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            config_path = project / ".codex" / "config.toml"
            config_path.parent.mkdir()
            config_path.write_text(
                '[mcp_servers."pkulaw-law-semantic"]\n'
                'url = "https://custom.example/mcp"\n',
                encoding="utf-8",
            )

            added = INSTALLER.install(project, "law")
            config_text = config_path.read_text(encoding="utf-8")

            self.assertNotIn("pkulaw-law-semantic", added)
            self.assertEqual(config_text.count("pkulaw-law-semantic"), 1)

    def test_can_install_only_law_services(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            added = INSTALLER.install(project, "law")
            config_text = (project / ".codex" / "config.toml").read_text(
                encoding="utf-8"
            )

            self.assertEqual(len(added), 2)
            self.assertIn("[mcp_servers.pkulaw-law-semantic]", config_text)
            self.assertNotIn("[mcp_servers.pkulaw-case-semantic]", config_text)

    def test_audit_never_requires_a_token_value_in_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            INSTALLER.install(project, "all")
            with mock.patch.dict(
                os.environ, {"PKULAW_MCP_TOKEN": "test-only"}, clear=False
            ):
                self.assertEqual(INSTALLER.audit_config(project, "all"), [])


if __name__ == "__main__":
    unittest.main()
