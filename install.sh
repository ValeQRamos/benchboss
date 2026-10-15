#!/bin/sh
# benchboss installer for macOS and Linux.
# Installs uv (https://docs.astral.sh/uv/) if it is missing, then installs the benchboss command
# in its own isolated environment. Safe to run again to upgrade.
set -eu

SOURCE="${BENCHBOSS_SOURCE:-https://github.com/ValeQRamos/benchboss/archive/refs/heads/main.zip}"

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv (Python tool manager by Astral)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  export PATH
fi

echo "==> Installing benchboss"
uv tool install --force --python 3.12 "benchboss @ $SOURCE"
uv tool update-shell >/dev/null 2>&1 || true

echo
echo "benchboss is installed. Open a new terminal and run:"
echo "    benchboss setup      # connect your ESPN league"
echo "    benchboss            # open the app"
echo "    benchboss --demo     # look around with sample data"
