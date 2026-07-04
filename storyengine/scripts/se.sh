#!/usr/bin/env bash
# se - one command for all StoryEngine VPS operations. Runs locally on the Mac.
#
# Why this exists: agent sessions were making 50-165 raw ssh calls each, plus
# hand-typed inline Python that broke on quoting. This wraps the common ops in
# single, batched, predictable calls. Companion skill: ~/.claude/skills/se/
#
# Usage:
#   se health                                  full health report in one call
#   se logs [backend|frontend|worker] [N]      last N log lines (default 100)
#   se db "SQL"                                run SQL (read-only by default)
#   se db --write "SQL"                        allow INSERT/UPDATE/etc.
#   se deploy <session-name> [--with-frontend] [--force]   sanctioned deploy
#   se restart [backend|frontend]              restart one service, no git pull
#   se token                                   print API token from /tmp/se_token
#   se run 'commands'                          arbitrary command on the VPS
set -euo pipefail

HOST="storyengine-vps"
RREPO='$HOME/projects/economy-fastforward'
RPY="$RREPO/storyengine/backend/venv/bin/python3"
DBHELPER="$RREPO/storyengine/scripts/se_db.py"

cmd="${1:-help}"; shift || true

unit() {
  case "${1:-backend}" in
    backend)  echo "storyengine-backend.service" ;;
    frontend) echo "storyengine-frontend.service" ;;
    worker)   echo "storyengine-worker.service" ;;
    *) echo "unknown service: $1" >&2; exit 2 ;;
  esac
}

case "$cmd" in
  health)
    ssh "$HOST" '
      echo "== services ==";
      for u in storyengine-backend storyengine-frontend; do
        printf "%s: %s\n" "$u" "$(systemctl is-active $u.service 2>/dev/null || systemctl --user is-active $u.service 2>/dev/null)";
      done
      echo "== api ==";
      curl -sf -m 10 http://localhost:8001/api/health || echo "API DOWN";
      echo; echo "== frontend ==";
      printf "http %s\n" "$(curl -s -o /dev/null -w "%{http_code}" -m 10 http://localhost:3001)";
      echo "== deploy lock ==";
      cat ~/deploy.lock 2>/dev/null || echo "no lock (clear to deploy)";
      echo "== last deploy ==";
      tail -1 ~/deploys.log 2>/dev/null || echo "no deploy log";
      echo "== disk ==";
      df -h / | tail -1
    '
    ;;
  logs)
    svc="${1:-backend}"; n="${2:-100}"; u="$(unit "$svc")"
    ssh "$HOST" "journalctl -u $u -n $n --no-pager 2>/dev/null | grep . || journalctl --user -u $u -n $n --no-pager 2>/dev/null | grep . || tail -n $n ~/${svc}.log 2>/dev/null || echo 'no logs found for $u'"
    ;;
  db)
    args=""
    if [ "${1:-}" = "--write" ]; then args="--write"; shift; fi
    sql="${1:?usage: se db [--write] \"SQL\"}"
    printf '%s' "$sql" | ssh "$HOST" "$RPY $DBHELPER $args"
    ;;
  deploy)
    who="${1:?usage: se deploy <session-name> [--with-frontend] [--force]}"; shift || true
    ssh "$HOST" "$RREPO/storyengine/scripts/vps-deploy.sh $who $*"
    echo "-- post-deploy health --"
    "$0" health
    ;;
  restart)
    svc="${1:-backend}"; u="$(unit "$svc")"
    if [ "$svc" = "frontend" ]; then
      echo "note: frontend needs 'npm run build' before a restart shows new code. Use 'se deploy <name> --with-frontend' for code changes."
    fi
    # Kill by exact unit MainPID, then let systemd revive it. NEVER pkill -f
    # uvicorn on this box - it has matched voice-osiris and the ssh session.
    ssh "$HOST" "
      PID=\$(systemctl show -p MainPID --value $u 2>/dev/null);
      [ -z \"\$PID\" -o \"\$PID\" = 0 ] && PID=\$(systemctl --user show -p MainPID --value $u 2>/dev/null);
      if [ -n \"\$PID\" ] && [ \"\$PID\" != 0 ]; then kill -9 \$PID; fi;
      sleep 4;
      for i in 1 2 3 4 5; do
        (systemctl is-active --quiet $u || systemctl --user is-active --quiet $u) && break; sleep 3;
      done;
      printf '%s: %s\n' '$u' \"\$(systemctl is-active $u 2>/dev/null || systemctl --user is-active $u 2>/dev/null)\"
    "
    ;;
  token)
    ssh "$HOST" 'cat /tmp/se_token 2>/dev/null || echo "no token at /tmp/se_token - mint one (see /se skill)"'
    ;;
  run)
    ssh "$HOST" "$*"
    ;;
  help|*)
    sed -n '2,16p' "$0"
    ;;
esac
