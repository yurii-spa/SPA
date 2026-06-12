#!/bin/bash
echo "=== SPA GitHub PAT Diagnostic ==="
echo ""

echo "1. Keychain (GITHUB_PAT_SPA):"
PAT_KEY=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>&1)
if [[ "$PAT_KEY" == ghp_* ]] || [[ "$PAT_KEY" == github_pat_* ]]; then
  echo "   ✅ Найден: ${PAT_KEY:0:8}..."
else
  echo "   ❌ НЕ найден: $PAT_KEY"
fi

echo ""
echo "2. ~/.github_pat файл:"
if [ -f ~/.github_pat ]; then
  PAT_FILE=$(cat ~/.github_pat)
  echo "   ✅ Найден: ${PAT_FILE:0:8}..."
else
  echo "   ❌ НЕ найден"
fi

echo ""
echo "3. Тест соединения с GitHub API:"
CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 https://api.github.com/zen)
if [ "$CODE" = "200" ]; then
  echo "   ✅ Доступен (HTTP $CODE)"
else
  echo "   ❌ Недоступен (HTTP $CODE)"
fi

echo ""
echo "=== Решение ==="
echo "Чтобы настроить PAT для агентов:"
echo "  bash ~/Documents/SPA_Claude/setup_github_pat.sh ghp_ТВОЙ_ТОКЕН"
echo "Чтобы запустить все pending пуши:"
echo "  bash ~/Documents/SPA_Claude/scripts/push_v495.sh && \\"
echo "  bash ~/Documents/SPA_Claude/scripts/push_v496.sh && \\"
echo "  bash ~/Documents/SPA_Claude/scripts/push_v489.sh"
