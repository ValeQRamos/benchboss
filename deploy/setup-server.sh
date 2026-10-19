#!/bin/bash
# Set up a server for benchboss releases. Run as root from the folder that holds these files:
#   sudo bash setup-server.sh DEPLOY_USER [URL]
# DEPLOY_USER is an existing user that owns the releases and runs update.sh. URL is the address
# people will type, for example https://bb.1-2-3-4.sslip.io (needed the first time). Safe to run again.
set -euo pipefail

user=${1:-}
url=${2:-}
[ "$(id -u)" = 0 ] || { echo "run it with sudo" >&2; exit 1; }
{ [ -n "$user" ] && id "$user" >/dev/null 2>&1; } || { echo "usage: sudo bash setup-server.sh DEPLOY_USER [URL] (DEPLOY_USER already exists)" >&2; exit 1; }
[[ -z $url || $url =~ ^https?://[A-Za-z0-9.-]+(:[0-9]+)?$ ]] || { echo "URL is the address people type, for example https://bb.example.com" >&2; exit 1; }
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
install -m 644 "$here/benchboss-web.service" /etc/systemd/system/benchboss-web.service
systemctl daemon-reload

echo "==> the service user and the web app's settings"
id benchboss >/dev/null 2>&1 || adduser --system --group --home /var/lib/benchboss --shell /usr/sbin/nologin benchboss >/dev/null
install -d -o benchboss -g benchboss -m 700 /var/lib/benchboss
if [ ! -f /etc/benchboss/web.env ]; then
  if [ -n "$url" ]; then
    (umask 077; printf 'BB_PORT=8000\nBB_URL=%s\nBB_ARGS="--max-sessions 5 --max-per-user 2"\n' "$url" > /etc/benchboss/web.env)
  else
    echo "no /etc/benchboss/web.env yet: run this again with the address, for example https://bb.example.com"
  fi
fi
[ -f /etc/benchboss/web.env ] && systemctl enable benchboss-web >/dev/null 2>&1 || true

echo "==> swap for a small server"
mem=$(awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo)
if [ "$(swapon --show --noheadings | wc -l)" = 0 ] && [ "$mem" -lt 1500 ]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "added a 1 GB swap file"
else
  echo "swap is already there, or the server has enough memory"
fi

echo "done: next, deploy a version (deploy/deploy.sh update), then add the first person (sudo benchboss-users add NAME)"
