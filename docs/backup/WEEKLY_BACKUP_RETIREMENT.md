# Вывод `com.spa.weekly_backup` из работы — ПОДГОТОВЛЕННОЕ решение (не выполнено)

> ADR-763, пакет 3 (директива владельца 16.10). Отключение агента — изменение прод-дерева
> (`.claude/rules/deployment.md` п. 6): выполняется только с разрешения владельца. Старые архивы
> в `~/Documents/SPA_Backups/` НЕ удаляются — ни целые, ни обрезанные.

## Почему еженедельный архив можно снять, но не раньше времени

Еженедельный скрипт (`scripts/weekly_backup.sh`, суббота 10:00) кладёт почти всё рабочее дерево
(без `.git`) в `~/Documents/SPA_Backups/` — **на тот же Mac**. Замер 16.10: архивы 09-26
(1 659 197 440 Б) и 10-03 (2 638 264 320 Б) **обрезаны** (`gzip -t`), 09-19 и 10-10 целы; лог причины
exit 1 стёрт перезагрузкой 15.10 — НЕ ИЗМЕРЕНО. Мониторинг уже числит агента выведенным
(`agent_health_monitor` RETIRED_LABELS), а `architecture/manifest.json` — `intent: "active"`.

До 16.10 только он нёс: карточки и решения владельца (`nimbalyst-local/`, ~47 файлов не на origin),
локальные документы `docs/`, `data/spa.db`, plist агентов. Неотправленные ветки (64) и stash не нёс
никто — `.git` исключён и из него.

## Что закрыто кандидатом пакета 3 (доставлено вместе с этим файлом)

| Что | Чем теперь покрыто | Куда |
|---|---|---|
| `nimbalyst-local/`, `docs/` | `memory_backup.py` набор `spa_owner_files` (проверка на секреты как у остальных) | iCloud `SPA_backups/memory/<дата>/`, 14 дней |
| plist `com.spa.*`, указатели пульта (`~/studio-os-serve/*.json`, `*/current.json`) | набор `host_settings` | то же |
| локальные ветки + верхний stash, которых нет на origin | git-бандл `spa_local_branches` (`--branches refs/stash --not --remotes=origin`) | iCloud `SPA_backups/memory/bundles/` |
| `data/spa.db` | ежедневный FULL (`_SQLITE_FILES`) + обязателен в `full_archive_verify` | `data/backups/` + iCloud `dr_offsite/` |

Проба 16.10 на живых источниках в отдельную папку: 1224/1224 файла `nimbalyst-local`+`docs` побайтно
совпали, 97/97 plist, 65/65 голов бандла совпали с живыми вершинами, `git bundle verify` ok; FULL —
856 файлов, `full_archive_verify` ok, 5 баз `integrity_check` ok.

Не покрыто и названо: старые записи stash (`stash@{1..}` — бандл несёт только верхний ref),
`~/studio-os-serve/work` (8,7 ГБ, рабочие копии), содержимое Keychain (только имена известны,
синхронизация iCloud Keychain — НЕ ИЗМЕРЕНО), загрузка iCloud на серверы Apple — НЕ ИЗМЕРЕНО
(файл в папке iCloud не доказательство загрузки).

## Условия (все сразу), после которых владельцу предлагается отключение

1. Ночной `memory_backup` после доставки — **3 ночи подряд** `ok=true`, и в `MANIFEST.json` есть
   `spa_owner_files`, `host_settings`, `spa_local_branches` (проверка:
   `python3 -c "import json,glob; …"` по `~/Library/Mobile Documents/com~apple~CloudDocs/SPA_backups/memory/*/MANIFEST.json`).
2. Хотя бы одна проба восстановления **из копии в iCloud** в отдельную папку зелёная: FULL — 0 расхождений
   sha256 с манифестом и `integrity_check=ok`; `spa_owner_files` — 0 отсутствующих файлов против живого
   `nimbalyst-local/tracker`; бандл — число голов = числу локальных веток не на origin.
3. Последний целый еженедельный архив `SPA_Claude_backup_2026-10-10.tar.gz` (`gzip -t` ok) на месте.

## Выполнение (действие владельца на Mac — только по его разрешению)

```bash
launchctl bootout gui/$(id -u)/com.spa.weekly_backup
mv ~/Library/LaunchAgents/com.spa.weekly_backup.plist ~/Library/LaunchAgents/com.spa.weekly_backup.plist.disabled
/Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.monitoring.deployment_acceptance; echo "код: $?"   # 0
```
плюс правка кода через обычную доставку: `architecture/manifest.json` → `"intent": "retired"` у
`com.spa.weekly_backup` (снимает нынешнее противоречие с RETIRED_LABELS).

## Откат

```bash
mv ~/Library/LaunchAgents/com.spa.weekly_backup.plist.disabled ~/Library/LaunchAgents/com.spa.weekly_backup.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.spa.weekly_backup.plist
/Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.monitoring.deployment_acceptance; echo "код: $?"
```
и `"intent": "active"` обратно. Копия plist также лежит в `data/retired_plists_backup/`.
