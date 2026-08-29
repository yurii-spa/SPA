#!/bin/bash
# pre-push hook: пуш НЕ ИМЕЕТ ПРАВА терять коммиты.
#
# Написан по аварии 2026-08-29: сессия сделала `git commit` в прод-дереве и
# запушила его форсом. Родителем коммита оказалась УСТАРЕВШАЯ локальная голова
# (449d2818) — та самая, про которую хук начала сессии честно писал «локальный
# индекс отстаёт от origin/main на 1235 коммитов» (ADR-152, это ШТАТНО). Ветка
# откатилась на **1249 коммитов**: работа нескольких сессий за день плюс вся
# история, на которую индекс отставал.
#
# Правило проекта «пушить только через push_to_github.py» существовало и было
# написано в CLAUDE.md. Оно не сработало, потому что у него не было исполнителя:
# правило жило в тексте, а `git push` — в руках. Этот хук и есть исполнитель.
#
# Отказ fail-CLOSED: если измерить нечем (нет сети, объект не скачан) — отказ,
# а не молчаливый пропуск. «Не измерено» никогда не равно «безопасно».
#
# Осознанный обход:  SPA_ALLOW_HISTORY_REWRITE=1 git push ...
# Снять хук:         rm .git/hooks/pre-push

set -uo pipefail

GUARDED_BRANCH="refs/heads/main"
REMOTE_NAME="${1:-origin}"
ZERO="0000000000000000000000000000000000000000"

fail() {
    echo ""
    echo "❌ ПУШ ОСТАНОВЛЕН: $1"
    echo ""
    echo "   $2"
    echo ""
    echo "   Правильный путь доставки (CLAUDE.md):"
    echo "     python3 /abs/path/<твоё-дерево>/push_to_github.py --files ... --message ..."
    echo "   Он берёт базу с УДАЛЁННОЙ ветки, а не с локальной головы, и не форсит."
    echo ""
    echo "   Осознанный обход (только если ты ТОЧНО знаешь, что теряешь):"
    echo "     SPA_ALLOW_HISTORY_REWRITE=1 git push ..."
    echo ""
    exit 1
}

while read -r local_ref local_sha remote_ref remote_sha; do
    [ "$remote_ref" = "$GUARDED_BRANCH" ] || continue
    [ "$local_sha" = "$ZERO" ] && fail "удаление ветки main" "Ветка main не удаляется этим путём."

    if [ "${SPA_ALLOW_HISTORY_REWRITE:-0}" = "1" ]; then
        echo "⚠️  pre-push: проверка потери коммитов ОТКЛЮЧЕНА (SPA_ALLOW_HISTORY_REWRITE=1)"
        continue
    fi

    # Истину спрашиваем у СЕРВЕРА, а не у remote-tracking ссылки: она сама
    # бывает устаревшей, и именно на устаревшей ссылке авария и произошла.
    true_remote=$(git ls-remote "$REMOTE_NAME" "$GUARDED_BRANCH" 2>/dev/null | awk '{print $1}' | head -1)
    if [ -z "$true_remote" ]; then
        fail "не удалось спросить сервер о состоянии main" \
             "Сказать, не теряем ли мы чужие коммиты, НЕЧЕМ. Проверь сеть и повтори."
    fi

    # Уже совпадает — пушить нечего, это не потеря.
    [ "$true_remote" = "$local_sha" ] && continue

    if ! git cat-file -e "${true_remote}^{commit}" 2>/dev/null; then
        fail "серверная голова ${true_remote:0:12} не скачана локально" \
             "Без неё родство не проверить. Выполни: git fetch $REMOTE_NAME main"
    fi

    # Единственный безопасный случай: серверная голова — предок того, что пушим.
    if git merge-base --is-ancestor "$true_remote" "$local_sha" 2>/dev/null; then
        continue
    fi

    lost=$(git rev-list --count "${local_sha}..${true_remote}" 2>/dev/null || echo "?")
    behind_note=""
    if git merge-base --is-ancestor "$local_sha" "$true_remote" 2>/dev/null; then
        behind_note="Локальная ветка ПОЗАДИ сервера на $lost коммит(ов) — это ШТАТНО (ADR-152): пуши идут в origin через API мимо индекса."
    else
        behind_note="Ветки разошлись: на сервере есть $lost коммит(ов), которых нет в том, что ты пушишь."
    fi

    fail "этот пуш стёр бы $lost коммит(ов) с main" "$behind_note"
done

exit 0
