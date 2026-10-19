#!/bin/bash
# Install a version of benchboss as a new release, switch to it, check it, and roll back by
# itself when the check fails. Runs on the server, as the deploy user.
#
#   update.sh REF          REF: a full commit sha, a tag or a branch of the GitHub repo
#   update.sh -            a tar of the source on stdin: git archive HEAD | ssh host update.sh -
#   update.sh --rollback   go back to the release before the current one
#   update.sh --status     the current release and the ones kept
#
# With an SSH forced command (docs/deploy.md) the REF arrives in SSH_ORIGINAL_COMMAND and only
# a full commit sha, a version tag, or the words rollback and status are accepted.
set -euo pipefail

case "${SSH_ORIGINAL_COMMAND:-}" in
  rollback) set -- --rollback ;;
  status) set -- --status ;;
esac

ROOT=${BENCHBOSS_ROOT:-/opt/benchboss}
REPO=${BENCHBOSS_REPO:-ValeQRamos/benchboss}
PYTHON=${BENCHBOSS_PYTHON:-3.12}
KEEP=4

say() { printf '==> %s\n' "$*"; }
die() { printf 'update: %s\n' "$*" >&2; exit 1; }

command -v uv >/dev/null || die "uv is not installed: run setup-server.sh first"

current() { local t; t=$(readlink "$ROOT/current" 2>/dev/null) || return 0; basename "$t"; }
# ids start with a timestamp, so sorting them sorts the releases by age
releases() { ls -1 "$ROOT/releases" 2>/dev/null | sort -r || true; }   # newest first

switch_to() {
  ln -sfn "releases/$1" "$ROOT/current.new"
  mv -Tf "$ROOT/current.new" "$ROOT/current"
}

instances() {  # the web services that should be running: the one for everyone, and any older per-person ones
  {
    systemctl list-units 'benchboss-web@*.service' --state=active --plain --no-legend | awk '{print $1}'
    if systemctl is-enabled --quiet benchboss-web.service 2>/dev/null; then echo benchboss-web.service; fi
  } || true
}

restart_all() {
  local u
  for u in $(instances); do sudo systemctl restart "$u"; done
}

port_of() {  # the unit's port, read with sudo because the settings file is private
  local name
  case $1 in
    benchboss-web.service) name=web ;;
    *) name=${1#benchboss-web@}; name=${name%.service} ;;
  esac
  sudo sed -n 's/^BB_PORT=//p' "/etc/benchboss/$name.env"
}

healthy() {  # every instance answers its sign in page within 40 seconds
  local u port n
  for u in $(instances); do
    port=$(port_of "$u")
    [ -n "$port" ] || { say "$u: no port in its settings"; return 1; }
    for n in $(seq 1 20); do
      if curl -fsS -o /dev/null -m 3 "http://127.0.0.1:$port/login" 2>/dev/null; then break; fi
      [ "$n" = 20 ] && { say "$u did not answer on port $port"; return 1; }
      sleep 2
    done
  done
}

case "${1:-}" in
  --status)
    say "current: $(current || true)"
    releases | sed 's/^/    /'
    exit 0 ;;
  --rollback)
    cur=$(current)
    prev=$(releases | awk -v c="$cur" '$0 < c' | head -1)
    [ -n "$prev" ] || die "no release older than $cur to go back to"
    say "rolling back $cur -> $prev"
    switch_to "$prev"; restart_all
    healthy || die "the previous release does not answer either: see journalctl -u 'benchboss-web*'"
    say "now on $prev"
    exit 0 ;;
esac

arg=${1:-}
if [ -n "${SSH_ORIGINAL_COMMAND:-}" ]; then
  arg=$SSH_ORIGINAL_COMMAND
  [[ $arg =~ ^([0-9a-f]{40}|v[0-9][0-9A-Za-z._-]*)$ ]] || die "a forced command takes a full commit sha, a version tag, rollback or status"
else
  [[ $arg == - || $arg =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || die "usage: update.sh REF | - | --rollback | --status"
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir "$work/src"

if [ "$arg" = - ]; then
  say "reading the source from stdin"
  tar -x -C "$work/src"
  id="$(date +%Y%m%d%H%M%S)-local"
else
  say "downloading $REPO @ $arg"
  curl -fsSL "https://github.com/$REPO/archive/$arg.tar.gz" | tar -xz -C "$work/src" --strip-components=1
  id="$(date +%Y%m%d%H%M%S)-$(printf '%s' "${arg:0:12}" | tr '/' '-')"
fi
[ -f "$work/src/pyproject.toml" ] || die "that does not look like benchboss (no pyproject.toml)"

rel="$ROOT/releases/$id"
say "building release $id"
uv venv --quiet --python "$PYTHON" "$rel"
uv pip install --quiet --python "$rel/bin/python" "$work/src[web]"
version=$("$rel/bin/benchboss" --version) || { rm -rf "$rel"; die "the new build does not start"; }

previous=$(current || true)
say "switching to $id ($version)"
switch_to "$id"
# the next update uses the updater that came with this version
if [ -f "$work/src/deploy/update.sh" ]; then
  install -m 755 "$work/src/deploy/update.sh" "$ROOT/update.sh.new" && mv -f "$ROOT/update.sh.new" "$ROOT/update.sh"
fi
restart_all

if ! healthy; then
  mkdir -p "$ROOT/failed"
  if [ -n "$previous" ]; then
    say "the check failed: going back to $previous"
    switch_to "$previous"; restart_all
    healthy && say "back on $previous" || say "the previous release does not answer either"
  fi
  mv "$rel" "$ROOT/failed/$id"   # out of the list, so a rollback never lands on it
  ls -1t "$ROOT/failed" | tail -n +3 | while read -r old; do rm -rf "${ROOT:?}/failed/$old"; done
  die "release $id failed its check: kept in $ROOT/failed/$id for inspection"
fi

releases | tail -n +$((KEEP + 1)) | while read -r old; do
  [ "$old" = "$(current)" ] || rm -rf "${ROOT:?}/releases/$old"
done
say "deployed $id (before: ${previous:-nothing})"
