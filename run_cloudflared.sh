#!/bin/bash
# run_cloudflared.sh — запускает cloudflared независимо от пути установки.
# Поддержка: Apple Silicon homebrew (/opt/homebrew/bin), Intel (/usr/local/bin),
#            user-local (~/.local/bin), системный /usr/bin и PATH-fallback.
# Вывод дублируется в лог (plist StandardOut/ErrorPath ловит stdout+stderr).

# HOME подстраховка на случай, если launchd-контекст без HOME.
export HOME="${HOME:-/Users/yuriikulieshov}"

for path in \
  /opt/homebrew/bin/cloudflared \
  /usr/local/bin/cloudflared \
  "$HOME/.local/bin/cloudflared" \
  /usr/bin/cloudflared \
  "$(command -v cloudflared 2>/dev/null)"; do
  if [ -n "$path" ] && [ -x "$path" ]; then
    echo "[run_cloudflared] using binary: $path" >&2
    exec "$path" tunnel --no-autoupdate run spa 2>&1
  fi
done

echo "ERROR: cloudflared не найден. Установи: brew install cloudflared" >&2
exit 1
