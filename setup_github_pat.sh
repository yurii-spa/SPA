#!/usr/bin/env bash
# setup_github_pat.sh — сохраняет GitHub PAT в файл ~/.github_pat (chmod 600).
# Используется агентами/Linux sandbox, где macOS Keychain недоступен.
#
# Использование:
#   ./setup_github_pat.sh ghp_ТВОЙ_ТОКЕН
#
# Токен НИКОГДА не попадает в git (файл в .gitignore).

set -euo pipefail

if [[ $# -ne 1 || -z "$1" ]]; then
    echo "❌ Укажи токен как аргумент: $0 ghp_ТВОЙ_ТОКЕН" >&2
    exit 1
fi

PAT="$1"
TARGET="$HOME/.github_pat"

# Базовая проверка формата (ghp_ / ghs_ / github_pat_)
if [[ ! "$PAT" =~ ^(ghp_|ghs_|github_pat_) ]]; then
    echo "⚠️  Предупреждение: токен не начинается с ghp_/ghs_/github_pat_ — убедись, что это GitHub PAT"
fi

printf '%s' "$PAT" > "$TARGET"
chmod 600 "$TARGET"

echo "✅ Токен сохранён в $TARGET (chmod 600)"
echo "   push_to_github.py подхватит его автоматически (fallback #4)."
