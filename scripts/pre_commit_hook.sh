#!/usr/bin/env bash
# scripts/pre_commit_hook.sh — то, что ставится в каталог хуков как `pre-commit`.
#
# Тонкая обёртка, а не копия гейтов. Копия `pre_commit_check.sh` в общем
# каталоге хуков (`<главное дерево>/.git/hooks/`) не знает, какое дерево
# коммитят: её `dirname "$0"` — каталог git ГЛАВНОГО дерева даже при коммите
# из worktree (замер 22.10: `$0` = `<main>/.git/hooks/pre-commit` в обоих
# случаях). Знает это только git: он запускает хук из КОРНЯ той рабочей копии,
# которую коммитят (githooks(5)). Поэтому обёртка зовёт гейты по пути от
# каталога запуска — и исполняется файл ТОЙ копии, на ЕЁ ревизии, а сам
# `pre_commit_check.sh` выводит корень из своего места.
#
# Ставят: scripts/install_git_hooks.sh, scripts/install_pre_commit.sh.
set -euo pipefail

if [ ! -f scripts/pre_commit_check.sh ]; then
  # Не измерено — не «чисто»: гейтов в этой рабочей копии нет, коммит не идёт.
  echo "❌ pre-commit: в $(pwd) нет scripts/pre_commit_check.sh — гейты не измерены"
  echo "   осознанный обход: git commit --no-verify"
  exit 1
fi
exec bash scripts/pre_commit_check.sh "$@"
