# Reusable PKULaw MCP installer

This directory can be copied into another legal AI repository. The installer:

- adds law-semantic, law-keyword, case-semantic, and case-keyword MCP servers;
- preserves unrelated content in an existing `.codex/config.toml`;
- skips server sections that already exist;
- never accepts, prints, or writes the PKULaw token;
- uses only the Python standard library and supports Python 3.9+.

Install all four services into the current project:

```bash
python3 tools/pkulaw_mcp/install.py
```

Install only one service group:

```bash
python3 tools/pkulaw_mcp/install.py --services law
python3 tools/pkulaw_mcp/install.py --services case
```

Preview without writing:

```bash
python3 tools/pkulaw_mcp/install.py --dry-run
```

Check configuration and whether the current process can see the token:

```bash
python3 tools/pkulaw_mcp/install.py --check
```

Authentication uses the `PKULAW_MCP_TOKEN` environment variable. After setting
it, fully restart Codex so the new process inherits the variable.
