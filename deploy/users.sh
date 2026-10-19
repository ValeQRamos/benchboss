#!/bin/bash
# Manage the people who sign in to this server's benchboss web app. Run it with sudo; it runs
# `benchboss users` as the service user, so the files stay private to that user.
#
#   benchboss-users add NAME [--github LOGIN] [--password-file FILE]   prints a password, once
#   benchboss-users list
#   benchboss-users password NAME [--password-file FILE]               a new password
#   benchboss-users github NAME [LOGIN]    link a GitHub login to them (no LOGIN: unlink)
#   benchboss-users remove NAME --yes      delete them and everything of theirs
#   benchboss-users import NAME --from FOLDER [--password-file FILE]   move in an old install
#   benchboss-users oauth --client-id ID   turn on Sign in with GitHub for everyone (asks for the secret)
set -euo pipefail

SERVICE_USER=benchboss
HOME_DIR=/var/lib/benchboss
ENV_FILE=/etc/benchboss/web.env
die() { printf 'benchboss-users: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run it with sudo"
cd /

run() { exec runuser -u "$SERVICE_USER" -- env BENCHBOSS_HOME="$HOME_DIR" /usr/local/bin/benchboss users "$@"; }

set_var() {  # set KEY=VALUE in the settings file, keeping it private
  local key=$1 value=$2
  (umask 077; { grep -v "^$key=" "$ENV_FILE" || true; printf '%s=%s\n' "$key" "$value"; } > "$ENV_FILE.new")
  mv -f "$ENV_FILE.new" "$ENV_FILE"
}

cmd=${1:-}
case "$cmd" in
  add|list|password|remove) run "$@" ;;
  github)
    [ $# -ge 2 ] || die "usage: benchboss-users github NAME [LOGIN]"
    if [ $# -ge 3 ]; then run github "$2" --github "$3"; else run github "$2"; fi ;;
  import)
    # it reads another user's files, so it runs as root; the data goes to the service user after
    trap 'chown -R "$SERVICE_USER:$SERVICE_USER" "$HOME_DIR"' EXIT
    BENCHBOSS_HOME="$HOME_DIR" /usr/local/bin/benchboss users "$@" ;;
  oauth)
    shift
    { [ "${1:-}" = --client-id ] && [[ ${2:-} =~ ^[A-Za-z0-9]+$ ]]; } || die "usage: benchboss-users oauth --client-id ID (the id GitHub shows for your OAuth app)"
    [ -f "$ENV_FILE" ] || die "$ENV_FILE is missing: run setup-server.sh with the server's address"
    read -rsp "GitHub client secret (hidden): " secret; echo
    [[ $secret =~ ^[A-Za-z0-9_-]+$ ]] || die "that does not look like a client secret"
    set_var BENCHBOSS_GITHUB_CLIENT_ID "$2"
    set_var BENCHBOSS_GITHUB_CLIENT_SECRET "$secret"
    systemctl restart benchboss-web
    url=$(sed -n 's/^BB_URL=//p' "$ENV_FILE" | head -1)
    echo "Sign in with GitHub is on. The OAuth app's callback URL must be $url/login/github/callback"
    echo "Link people to their GitHub login with: benchboss-users github NAME LOGIN" ;;
  *) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
