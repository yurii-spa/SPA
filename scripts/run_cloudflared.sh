#!/bin/bash
# run_cloudflared.sh — reads tunnel token from Keychain, finds cloudflared
# binary across common install paths, and execs the tunnel.
# Token mode: `cloudflared tunnel run --token <JWT>` — config from CF edge.
# Secrets policy: token is NEVER stored in files.

export HOME="${HOME:-/Users/yuriikulieshov}"

TOKEN=$(security find-generic-password -s "CF_TUNNEL_TOKEN_SPA" -a "$USER" -w 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "$(date) ERROR: CF_TUNNEL_TOKEN_SPA not found in Keychain" >&2
  exit 1
fi

for bin in \
  /opt/homebrew/bin/cloudflared \
  /usr/local/bin/cloudflared \
  "$HOME/.local/bin/cloudflared" \
  /usr/bin/cloudflared \
  "$(command -v cloudflared 2>/dev/null)"; do
  if [ -n "$bin" ] && [ -x "$bin" ]; then
    echo "[run_cloudflared] using binary: $bin" >&2
    exec "$bin" tunnel --no-autoupdate run --token "$TOKEN"
  fi
done

echo "ERROR: cloudflared not found. Install: brew install cloudflared" >&2
exit 1
