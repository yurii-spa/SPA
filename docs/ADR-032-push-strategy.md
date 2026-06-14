# ADR-032: Consolidation of GitHub push mechanisms
*Дата: 2026-06-14 | Статус: ACCEPTED | Автор: SPA infra*

## Контекст

В репозитории `~/Documents/SPA_Claude` исторически накопилось несколько параллельных
механизмов пуша в GitHub (`yurii-spa/SPA`). Это создаёт неоднозначность ("каким
скриптом пушить?"), риск дублирующей логики и расхождение в способе чтения PAT.
ADR фиксирует единый canonical путь и помечает остальное как deprecated.

## Существующие механизмы

### 1. `scripts/auto_push.sh` — orchestrator (CANONICAL)
- **Что делает:** последовательно прогоняет все ожидающие `scripts/push_v*.sh`,
  отмечая выполненные в `scripts/.push_log`, чтобы каждый скрипт запускался один раз.
- **Защита:** singleton-lock (`scripts/.push.lock` + проверка PID) — нет перекрытия запусков.
- **Запуск:** launchd `com.spa.autopush` каждые 90 минут; вручную — `bash scripts/auto_push.sh`.
- **Статус:** ✅ ACTIVE / CANONICAL. Это точка входа для автоматического пуша.

### 2. `push_to_github.py` — низкоуровневый пушер (CANONICAL)
- **Что делает:** заливает указанные файлы в GitHub через Contents API.
- **PAT:** читает строго безопасно (порядок: macOS Keychain `GITHUB_PAT_SPA` →
  env `GITHUB_PAT_SPA` → env `SPA_GITHUB_PAT` → файл `~/.github_pat`). **Без hardcode.**
- **Интерфейс:** `python3 push_to_github.py --files <files> --message "<msg>" [--pat <PAT>] [--repo owner/repo]`.
- **Как используется:** каждый `push_v*.sh` резолвит PAT (Keychain → env → `~/.github_pat`)
  и вызывает `push_to_github.py --files ... --pat "$PAT"`.
- **Статус:** ✅ ACTIVE / CANONICAL. Единственный модуль, реально пишущий в GitHub.

### 3. `auto_push.py` (в корне репо) — DEPRECATED
- **Что делает:** сканирует изменённые по mtime файлы и пушит их автоматически.
- **Проблемы:**
  - Хардкодит абсолютный путь пользователя (`SPA_DIR = /Users/yuriikulieshov/...`) —
    ломается на новой машине / другом имени пользователя.
  - Дублирует ответственность с `auto_push.sh` (оба претендуют на роль "автопушера"),
    что вызывает путаницу "каким механизмом запущен пуш".
  - Отдельная mtime-логика и ALWAYS_INCLUDE_FILES — ещё одна поверхность для багов
    рядом с уже работающим `.push_log`-механизмом `auto_push.sh`.
- **Статус:** ❌ DEPRECATED. Не использовать в новых сценариях.

## Решение

1. **Canonical механизм пуша = `scripts/auto_push.sh` + `push_to_github.py`.**
   - `auto_push.sh` — orchestrator (что и когда пушить).
   - `push_to_github.py` — transport (как пушить + безопасное чтение PAT).
   - Все спринтовые пуши идут через `scripts/push_v*.sh`, которые вызывают `push_to_github.py`.
2. **`auto_push.py` помечается DEPRECATED.** Из launchd используется только
   `com.spa.autopush` → `scripts/auto_push.sh`. `auto_push.py` остаётся в репо как
   исторический артефакт, но новые задачи на него не опираются и в plist не ссылаются.
3. **PAT — только безопасные источники** (Keychain / env / `~/.github_pat`),
   никогда не в файлах (RULE из RULES.md, инцидент 2026-06-10).

## Последствия

- Один очевидный путь для немедленного пуша: `bash scripts/auto_push.sh`.
- Один транспорт с единой PAT-логикой: `push_to_github.py`.
- Снижение риска расхождений и дублирующих автопушеров.
- Документация (`CURRENT_STATE.md`, `RULES.md`, `DISASTER_RECOVERY.md`) ссылается
  только на canonical путь.

## Миграция / действия

- Убедиться, что launchd `com.spa.autopush` указывает на `scripts/auto_push.sh` (подтверждено в CURRENT_STATE.md).
- Не создавать новые plist/cron, ссылающиеся на `auto_push.py`.
- При обнаружении вызовов `auto_push.py` в скриптах — заменить на `auto_push.sh` / прямой `push_to_github.py`.

## Связанные документы

- `scripts/auto_push.sh`, `push_to_github.py`, `auto_push.py`
- `RULES.md` (запрет hardcode PAT, autopush 90 мин)
- `CURRENT_STATE.md` (push_method: autopush)
- `docs/DISASTER_RECOVERY.md` (Сценарий 4: PAT истёк)
