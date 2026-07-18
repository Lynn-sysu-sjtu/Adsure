from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".codex" / "config.toml"


def test_pkulaw_mcp_servers_use_environment_auth() -> None:
    config_text = CONFIG_PATH.read_text(encoding="utf-8")

    expected_urls = {
        "pkulaw-law-semantic": (
            "https://apim-gateway.pkulaw.com/mcp-law-search-service"
        ),
        "pkulaw-law-keyword": "https://apim-gateway.pkulaw.com/mcp-law",
        "pkulaw-case-semantic": (
            "https://apim-gateway.pkulaw.com/mcp-case-search-service"
        ),
        "pkulaw-case-keyword": "https://apim-gateway.pkulaw.com/mcp-case",
    }

    for name, expected_url in expected_urls.items():
        match = re.search(
            rf"^\[mcp_servers\.{re.escape(name)}\]\n"
            rf"(?P<body>.*?)(?=^\[|\Z)",
            config_text,
            flags=re.MULTILINE | re.DOTALL,
        )
        assert match is not None
        body = match.group("body")
        assert f'url = "{expected_url}"' in body
        assert 'bearer_token_env_var = "PKULAW_MCP_TOKEN"' in body
        assert "http_headers" not in body


def test_pkulaw_token_is_documented_without_a_value() -> None:
    env_lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "PKULAW_MCP_TOKEN=" in env_lines
