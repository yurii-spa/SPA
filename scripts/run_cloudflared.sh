#!/bin/bash
# run_cloudflared.sh — запускает cloudflared независимо от пути установки
# (Apple Silicon homebrew → /opt/homebrew/bin, Intel → /usr/local/bin)
for path in /opt/homebrew/bin/cloudflared /usr/local/bin/cloudflared /usr/bin/cloudflared; do
  if [ -x "$path" ]; then
    exec "$path" tunnel --no-autoupdate run spa
  fi
done
# Попробуем через PATH
if command -v cloudflared &>/dev/null; then
  exec cloudflared tunnel --no-autoupdate run spa
fi
echo "ERROR: cloudflared не найден. Установи: brew install cloudflared" >&2
exit 1
