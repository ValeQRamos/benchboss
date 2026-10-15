#!/bin/sh
# benchboss installer for macOS and Linux.
# Installs uv (https://docs.astral.sh/uv/) if it is missing, then installs the benchboss command
# in its own isolated environment. Safe to run again to upgrade. Does not need git.
set -eu

SOURCE="${BENCHBOSS_SOURCE:-https://github.com/ValeQRamos/benchboss/archive/refs/heads/main.zip}"

fail() {
  echo "benchboss: $*" >&2
  exit 1
}

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv (Python tool manager by Astral)"
  # Download first, then run: piping curl into sh would hide a failed download.
  uv_installer="$(mktemp)"
  trap 'rm -f "$uv_installer"' EXIT
  curl -LsSf https://astral.sh/uv/install.sh -o "$uv_installer" \
    || fail "could not download uv. Check your internet connection, or install uv from https://docs.astral.sh/uv/ and run this again."
  # </dev/null: when this script itself is piped into sh, the rest of it is on stdin
  sh "$uv_installer" </dev/null || fail "the uv installer failed (see above)."
  # The uv installer honors UV_INSTALL_DIR and XDG_BIN_HOME; otherwise it uses ~/.local/bin.
  PATH="${UV_INSTALL_DIR:+$UV_INSTALL_DIR:$UV_INSTALL_DIR/bin:}${XDG_BIN_HOME:+$XDG_BIN_HOME:}$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  export PATH
  command -v uv >/dev/null 2>&1 \
    || fail "uv was installed but this shell cannot find it. Open a new terminal and run this again."
fi

echo "==> Installing benchboss"
# Any Python 3.10 or newer that is already installed works; uv downloads one only if none is found.
uv tool install --force --python ">=3.10" "benchboss @ $SOURCE"
uv tool update-shell >/dev/null 2>&1 || true

echo
echo "benchboss is installed. Open a new terminal and run:"
echo "    benchboss setup      # connect your ESPN league"
echo "    benchboss            # open the app"
echo "    benchboss --demo     # look around with sample data"
