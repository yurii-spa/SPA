#!/bin/bash
# run_cloudflared.sh — reads tunnel token from Keychain, finds cloudflared
# binary across common install paths, and execs the tunnel.
# Token mode: `cloudflared tunnel run` reads TUNNEL_TOKEN from the environment
# (config from CF edge) — never passed as `--token <JWT>` on argv (ADR-556
# item: cloudflared carries its tunnel token on argv — a process-list secret
# leak on a shared-user host). cloudflared's own env var name is TUNNEL_TOKEN;
# exported here right before exec, never echoed, never written to a file.
# Secrets policy: token is NEVER stored in files.

export HOME="${HOME:-/Users/yuriikulieshov}"

TOKEN=$(security find-generic-password -s "CF_TUNNEL_TOKEN_SPA" -a "$USER" -w 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "$(date) ERROR: CF_TUNNEL_TOKEN_SPA not found in Keychain" >&2
  exit 1
fi

export TUNNEL_TOKEN="$TOKEN"
unset TOKEN

for bin in \
  /opt/homebrew/bin/cloudflared \
  /usr/local/bin/cloudflared \
  "$HOME/.local/bin/cloudflared" \
  /usr/bin/cloudflared \
  "$(command -v cloudflared 2>/dev/null)"; do
  if [ -n "$bin" ] && [ -x "$bin" ]; then
    echo "[run_cloudflared] using binary: $bin" >&2
    exec "$bin" tunnel --no-autoupdate run
  fi
done

echo "ERROR: cloudflared not found. Install: brew install cloudflared" >&2
exit 1
