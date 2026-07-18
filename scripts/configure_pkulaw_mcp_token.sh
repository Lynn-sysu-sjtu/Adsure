#!/bin/zsh
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This helper configures the Codex desktop environment on macOS only." >&2
  echo "On other systems, set PKULAW_MCP_TOKEN before starting Codex." >&2
  exit 1
fi

read -r -s "token?Enter the PKULaw MCP token (input is hidden): "
echo

if [[ -z "${token}" ]]; then
  echo "No token entered; nothing changed." >&2
  exit 1
fi

launchctl setenv PKULAW_MCP_TOKEN "${token}"
unset token

echo "PKULAW_MCP_TOKEN is set for newly launched applications."
echo "Fully quit and restart Codex, then open this trusted project."
echo "Use /mcp or Settings > MCP servers to verify the four pkulaw servers."
