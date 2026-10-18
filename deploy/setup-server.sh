#!/bin/bash
# Set up a server for benchboss releases. Run as root from the folder that holds these files:
#   sudo bash setup-server.sh DEPLOY_USER
# DEPLOY_USER is an existing user that owns the releases and runs update.sh. Safe to run again.
set -euo pipefail

user=${1:-}
[ "$(id -u)" = 0 ] || { echo "run it with sudo" >&2; exit 1; }
{ [ -n "$user" ] && id "$user" >/dev/null 2>&1; } || { echo "usage: sudo bash setup-server.sh DEPLOY_USER (an existing user)" >&2; exit 1; }
here=$(cd "$(dirname "$0")" && pwd)

echo "==> uv for every user"
if ! command -v uv >/dev/null; then
  tmp=$(mktemp)
  curl -fsSL https://astral.sh/uv/install.sh -o "$tmp"
  UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh "$tmp"
  rm -f "$tmp"
fi

echo "==> release folders and tools"
install -d -o "$user" -g "$user" -m 755 /opt/benchboss /opt/benchboss/releases
install -o "$user" -g "$user" -m 755 "$here/update.sh" /opt/benchboss/update.sh
install -m 755 "$here/users.sh" /usr/local/sbin/benchboss-users
ln -sfn /opt/benchboss/current/bin/benchboss /usr/local/bin/benchboss
install -d -m 755 /etc/benchboss
install -m 644 "$here/benchboss-web@.service" /etc/systemd/system/benchboss-web@.service
systemctl daemon-reload

echo "==> swap for a small server"
mem=$(awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo)
if [ "$(swapon --show --noheadings | wc -l)" = 0 ] && [ "$mem" -lt 1500 ]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "added a 1 GB swap file"
else
  echo "swap is already there, or the server has enough memory"
fi

echo "done: next, deploy a version (deploy/deploy.sh update) and add the first user (sudo benchboss-users add)"
