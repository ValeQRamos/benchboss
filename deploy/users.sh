#!/bin/bash
# Manage the people who use this server's benchboss web app. One person is one Linux user with
# their own ESPN account, settings and sign in password. Run it with sudo.
#
#   benchboss-users add NAME --url URL [--port N] [--existing]
#   benchboss-users list
#   benchboss-users password NAME            make a new sign in password
#   benchboss-users github NAME --client-id ID --users LOGIN[,LOGIN...]   (asks for the secret)
#   benchboss-users remove NAME --yes        stop, and delete the user and everything of theirs
set -euo pipefail

ENV_DIR=/etc/benchboss
die() { printf 'benchboss-users: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run it with sudo"

valid_name() { [[ $1 =~ ^[a-z][a-z0-9]{1,15}$ ]]; }
env_of() { echo "$ENV_DIR/$1.env"; }
get() { sed -n "s/^$2=//p" "$(env_of "$1")" | head -1 | sed 's/^"//; s/"$//'; }

new_password() {  # writes a random password file that only the user can read
  local name=$1 file=/home/$1/.bb-web-password
  (umask 077; openssl rand -base64 24 | tr -d '=+/' | cut -c1-24 > "$file")
  chown "$name:$name" "$file"; chmod 600 "$file"
}

next_port() {
  local p=8000
  while grep -qs "^BB_PORT=$p\$" "$ENV_DIR"/*.env || ss -tln | grep -q ":$p "; do p=$((p + 1)); done
  echo "$p"
}

cmd=${1:-}; shift || true
case "$cmd" in
  add)
    name=${1:-}; shift || true
    url=""; port=""; existing=0
    while [ $# -gt 0 ]; do
      case "$1" in
        --url) url=${2:-}; shift 2 ;;
        --port) port=${2:-}; shift 2 ;;
        --existing) existing=1; shift ;;
        *) die "unknown option $1" ;;
      esac
    done
    valid_name "$name" || die "the name is 2 to 16 lowercase letters and digits, starting with a letter"
    [[ $url =~ ^https?://[A-Za-z0-9.-]+(:[0-9]+)?$ ]] || die "--url is the address people type, for example https://alice.example.com"
    [ ! -e "$(env_of "$name")" ] || die "$name is already set up (benchboss-users list)"
    [ -z "$port" ] && port=$(next_port)
    [[ $port =~ ^[0-9]+$ ]] && [ "$port" -ge 1024 ] && [ "$port" -le 65535 ] || die "--port is a number from 1024 to 65535"
    ! grep -qs "^BB_PORT=$port\$" "$ENV_DIR"/*.env || die "port $port belongs to another user"

    if id "$name" >/dev/null 2>&1; then
      [ "$existing" = 1 ] || die "$name is already a Linux user: add --existing to use that account"
    else
      adduser --disabled-password --gecos "" "$name" >/dev/null
    fi
    [ -f "/home/$name/.bb-web-password" ] || new_password "$name"
    umask 077
    printf 'BB_PORT=%s\nBB_URL=%s\nBB_ARGS=""\n' "$port" "$url" > "$(env_of "$name")"
    systemctl enable --now "benchboss-web@$name" >/dev/null 2>&1
    host=${url#*://}; host=${host%%:*}
    cat <<EOF

$name is set up on port $port: $url
  sign in as     owner
  password file  /home/$name/.bb-web-password   (read it with: sudo cat /home/$name/.bb-web-password)
  first sign in  they paste their own ESPN cookies on the setup screen

Caddy: add this to /etc/caddy/Caddyfile, then run: sudo systemctl reload caddy
$host {
    reverse_proxy 127.0.0.1:$port
}
EOF
    ;;

  list)
    printf '%-12s %-6s %-9s %s\n' USER PORT STATE URL
    for f in "$ENV_DIR"/*.env; do
      [ -e "$f" ] || exit 0
      n=$(basename "$f" .env)
      printf '%-12s %-6s %-9s %s\n' "$n" "$(get "$n" BB_PORT)" "$(systemctl is-active "benchboss-web@$n" || true)" "$(get "$n" BB_URL)"
    done
    ;;

  password)
    name=${1:-}
    [ -e "$(env_of "$name")" ] || die "no such user (benchboss-users list)"
    new_password "$name"
    # the signing key stays, so open sessions end only when they expire; delete web-secret to end them now
    systemctl restart "benchboss-web@$name"
    echo "new password for $name: sudo cat /home/$name/.bb-web-password"
    ;;

  github)
    name=${1:-}; shift || true
    id=""; users=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --client-id) id=${2:-}; shift 2 ;;
        --users) users=${2:-}; shift 2 ;;
        *) die "unknown option $1" ;;
      esac
    done
    [ -e "$(env_of "$name")" ] || die "no such user (benchboss-users list)"
    [[ $id =~ ^[A-Za-z0-9]+$ ]] || die "--client-id is the id GitHub shows for your OAuth app"
    [[ $users =~ ^[A-Za-z0-9,-]+$ ]] || die "--users is GitHub logins or ids, comma separated"
    read -rsp "GitHub client secret (hidden): " secret; echo
    [[ $secret =~ ^[A-Za-z0-9_-]+$ ]] || die "that does not look like a client secret"
    port=$(get "$name" BB_PORT); url=$(get "$name" BB_URL)
    (umask 077; printf 'BB_PORT=%s\nBB_URL=%s\nBB_ARGS="--github-client-id %s --github-users %s"\nBENCHBOSS_GITHUB_CLIENT_SECRET=%s\n' \
      "$port" "$url" "$id" "$users" "$secret" > "$(env_of "$name")")
    systemctl restart "benchboss-web@$name"
    echo "GitHub sign in is on for $name. The OAuth app's callback URL must be $url/login/github/callback"
    ;;

  remove)
    name=${1:-}; yes=${2:-}
    [ -e "$(env_of "$name")" ] || die "no such user (benchboss-users list)"
    [ "$yes" = --yes ] || die "this deletes $name's account, settings and ESPN cookies: add --yes"
    systemctl disable --now "benchboss-web@$name" >/dev/null 2>&1 || true
    rm -f "$(env_of "$name")"
    deluser --remove-home "$name" >/dev/null
    echo "removed $name. Remove their block from /etc/caddy/Caddyfile and reload Caddy."
    ;;

  *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
