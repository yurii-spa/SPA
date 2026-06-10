#!/usr/bin/env bash
#
# secure_git_push.sh — SPA-V375
# -----------------------------------------------------------------------------
# Безопасная замена связке push_v*.html -> http://localhost:8765 -> Chrome.
# Токен НИКОГДА не хранится в plaintext в файлах репозитория. Скрипт читает
# его из переменной окружения GITHUB_TOKEN или из macOS Keychain и передаёт
# git через временный credential-helper (ничего не пишется на диск).
#
# Использование:
#   1) Положить новый (ротированный) PAT в Keychain один раз:
#        security add-generic-password -a "$USER" -s SPA_GITHUB_TOKEN -w
#      (введёте токен интерактивно, он не попадёт в историю shell)
#      ИЛИ экспортировать в окружение текущей сессии:
#        export GITHUB_TOKEN=ghp_...    # только в env, не в файлы
#   2) Запустить:
#        ./secure_git_push.sh            # push текущей ветки в origin
#        ./secure_git_push.sh main       # push конкретной ветки
#
# Скрипт ОТКАЗЫВАЕТСЯ работать, если обнаружит заведомо утёкший токен.
# -----------------------------------------------------------------------------
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# --- Суффиксы заведомо скомпрометированных токенов (отозваны 2026-06-10). -----
# Полные значения в файле не храним — даже мёртвые.
LEAKED_PAT_SUFFIXES=("2kN31r" "1s3vGZ")

KEYCHAIN_SERVICE="SPA_GITHUB_TOKEN"
REMOTE="${SPA_GIT_REMOTE:-origin}"

die() { echo "❌ $*" >&2; exit 1; }

# --- 1. Получить токен из env или Keychain (никогда из файла) -----------------
TOKEN="${GITHUB_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
  if command -v security >/dev/null 2>&1; then
    TOKEN="$(security find-generic-password -a "$USER" -s "$KEYCHAIN_SERVICE" -w 2>/dev/null || true)"
  fi
fi
[[ -n "$TOKEN" ]] || die "Токен не найден. Задайте GITHUB_TOKEN в env или добавьте в Keychain (service=$KEYCHAIN_SERVICE)."

# --- 2. Жёсткий отказ при утёкшем токене -------------------------------------
for sfx in "${LEAKED_PAT_SUFFIXES[@]}"; do
  if [[ "$TOKEN" == *"$sfx" ]]; then
    die "Обнаружен ЗАВЕДОМО УТЁКШИЙ PAT (…$sfx). Сначала отзовите его в GitHub и выпустите новый. Push прерван."
  fi
done

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"

# --- 3. Push через временный askpass-хелпер (токен не пишется на диск) --------
ASKPASS="$(mktemp)"
trap 'rm -f "$ASKPASS"' EXIT
cat > "$ASKPASS" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  *Username*) echo "x-access-token" ;;
  *Password*) echo "$SPA_PUSH_TOKEN" ;;
esac
EOF
chmod 700 "$ASKPASS"

REMOTE_URL="$(git remote get-url "$REMOTE")"
# Нормализуем в https-форму без встроенного токена
case "$REMOTE_URL" in
  git@github.com:*) REMOTE_URL="https://github.com/${REMOTE_URL#git@github.com:}" ;;
  https://*@github.com/*) REMOTE_URL="https://github.com/${REMOTE_URL#https://*@github.com/}" ;;
esac

echo "→ Push ветки '$BRANCH' в $REMOTE ($REMOTE_URL) безопасным способом…"
SPA_PUSH_TOKEN="$TOKEN" \
GIT_ASKPASS="$ASKPASS" GIT_TERMINAL_PROMPT=0 \
  git push "$REMOTE_URL" "HEAD:$BRANCH"

echo "✅ Push выполнен. Токен в файлы не записывался."
