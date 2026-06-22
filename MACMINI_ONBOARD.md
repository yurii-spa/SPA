# Запуск Claude на Mac mini — онбординг

Цель: дать Claude **реальный** доступ к Mac mini. Облачная веб-сессия к машине
дотянуться не может (другой дата-центр, изолированная песочница, видит только
копию репо). Доступ возникает только когда Claude запущен **на самом Mac mini**.

## Шаги (на Mac mini)

```bash
cd ~/Documents/SPA_Claude        # каталог проекта на Mac mini
git pull origin claude/project-overview-hcvh2k   # подтянуть этот скрипт
chmod +x start_claude_on_macmini.command          # один раз
open start_claude_on_macmini.command              # или двойной клик в Finder
```

Скрипт:
1. проверит Node 18+ (поставит через brew при отсутствии);
2. поставит Claude Code CLI, если его нет (`npm i -g @anthropic-ai/claude-code`);
3. запустит `claude` в каталоге проекта.

При первом запуске — вход через браузер (OAuth в Anthropic-аккаунт). **Никаких
ключей в файлы** — PAT остаётся в Keychain, логин в браузере.

## Что я сделаю, оказавшись на Mac mini (с живым launchctl)

Это безопаснее делать интерактивно на месте, а не слепым скриптом из облака:

1. **Снять реальную картину:** `launchctl list | grep com.spa`, `bash scripts/agent_status.sh`.
2. **Разрулить дубли plist'ов** (важно): plist'ы лежат в двух местах и конфликтуют —
   - корень: 8 файлов (`com.spa.cyclerunner`, `apiserver`, `analytics_tier_b`, `system_health_*`, …)
   - `scripts/`: 25 файлов (канонический набор, `com.spa.daily_cycle` и пр.)
   - Риск: `cyclerunner` (корень) и `daily_cycle` (scripts) оба гоняют цикл → двойные прогоны.
   - Решу, какой набор канонический, выгружу лишнее, оставлю один.
3. **Доустановить недостающее:** `com.spa.bot_commands` (интерактивный Telegram-бот без plist).
4. **Проверить autopush / туннель / сайт 8765** вживую.
5. **Сверить CURRENT_STATE.md** с фактическим статусом и обновить.

## Уже сделано из облака (ветка `claude/project-overview-hcvh2k`)

- `e2e4a07` — синхронизация конституции `LLM_FORBIDDEN_AGENTS` (добавлен `monitoring`).
- `d81bac6` — фикс устаревшего allow-list в `test_data_integrity`.
- этот онбординг + `start_claude_on_macmini.command`.
