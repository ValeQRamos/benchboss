#!/bin/bash
# Run from your own computer, inside a clone of the repo.
#
#   deploy/deploy.sh bootstrap USER@HOST     first time on a new server: tools, folders, swap
#   deploy/deploy.sh update USER@HOST [REF]  deploy a version (default: the commit you are on)
#   deploy/deploy.sh rollback USER@HOST      go back to the previous version
#   deploy/deploy.sh status USER@HOST
#
# SSH_OPTS adds ssh options, for example SSH_OPTS="-i ~/.ssh/benchboss_ssh".
set -euo pipefail

cmd=${1:-}; host=${2:-}; ref=${3:-}
{ [ -n "$cmd" ] && [ -n "$host" ]; } || { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
# shellcheck disable=SC2206
ssh_opts=(${SSH_OPTS:-})
here=$(cd "$(dirname "$0")" && pwd)
remote=/opt/benchboss/update.sh

case "$cmd" in
  bootstrap)
    user=${host%@*}
    echo "==> copying the setup files to $host"
    ssh "${ssh_opts[@]}" "$host" 'rm -rf /tmp/benchboss-setup && mkdir /tmp/benchboss-setup'
    scp "${ssh_opts[@]}" -q "$here"/setup-server.sh "$here"/update.sh "$here"/users.sh "$here"/benchboss-web@.service "$host:/tmp/benchboss-setup/"
    ssh -t "${ssh_opts[@]}" "$host" "sudo bash /tmp/benchboss-setup/setup-server.sh $user && rm -rf /tmp/benchboss-setup"
    ;;
  update)
    if [ -z "$ref" ]; then
      ref=$(git -C "$here" rev-parse HEAD)
      if ! git -C "$here" branch -r --contains "$ref" 2>/dev/null | grep -q .; then
        echo "==> $ref is not on GitHub yet: sending your local copy instead"
        git -C "$here" archive --format=tar HEAD | ssh "${ssh_opts[@]}" "$host" "$remote -"
        exit 0
      fi
    elif [ "$ref" = --local ]; then
      git -C "$here" archive --format=tar HEAD | ssh "${ssh_opts[@]}" "$host" "$remote -"
      exit 0
    fi
    ssh "${ssh_opts[@]}" "$host" "$remote $ref"
    ;;
  rollback) ssh "${ssh_opts[@]}" "$host" "$remote --rollback" ;;
  status)   ssh "${ssh_opts[@]}" "$host" "$remote --status" ;;
  *) echo "unknown command $cmd" >&2; exit 2 ;;
esac
