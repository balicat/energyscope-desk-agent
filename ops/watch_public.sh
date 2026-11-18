#!/usr/bin/env bash
# Is the public site answering? Run from cron every two minutes on the lab server.
#   page:  GET /             must be 200 and contain the page's name
#   api:   POST /api/ask {}  must be 400 (an empty question is refused before any model is called: free)
# Sends one ntfy message when the state changes (down, and again when it is back), not one per run.
# On 18 Nov 2026 the page's own server looped for half an hour on launch day and a reviewer's
# script found it; nothing was watching the address a visitor uses.
set -u
URL=${PUBLIC_URL:-https://thelibrarian.energy}
NTFY=${NTFY-https://ntfy.scotty.host/ES}
STATE=${STATE:-$HOME/.librarian-public-state}
problem=""
code=$(curl -s -m 20 -o /tmp/librarian-page.$$ -w '%{http_code}' "$URL/") || problem="page: no answer"
if [ -z "$problem" ]; then
  if [ "$code" != "200" ]; then problem="page: HTTP $code"
  elif ! grep -q "THE LIBRARIAN" /tmp/librarian-page.$$; then problem="page: 200 but not the page"; fi
fi
rm -f /tmp/librarian-page.$$
if [ -z "$problem" ]; then
  api=$(curl -s -m 20 -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d '{"question":""}' "$URL/api/ask") || api="none"
  [ "$api" = "400" ] || problem="api: an empty question returned $api, expected 400"
fi
now=${problem:-ok}
was=$(cat "$STATE" 2>/dev/null || echo ok)
if [ "$now" != "$was" ]; then
  printf '%s' "$now" > "$STATE"
  if [ -n "$NTFY" ]; then
    if [ "$now" = "ok" ]; then msg="The Librarian is answering again ($URL)."; pri=3
    else msg="The Librarian is DOWN for visitors: $now ($URL)."; pri=5; fi
    curl -s -m 15 -H "Title: The Librarian" -H "Priority: $pri" -d "$msg" "$NTFY" > /dev/null || true
  fi
fi
echo "$(date -u +%FT%TZ) $now"
