# START HERE — хендовер 28.10.2026 → новое окно Claude Code: TELEGRAM-OWNER-UX-01

Составлен в конце окна, которое закрыло R1/R2 (ADR-839) и пакет эксплуатации (ADR-849).
Владелец: Юрий. Приёмка: ARB. Повторный общий аудит НЕ нужен: всё ниже — факты с SHA и замерами.

## 1. Что фактически доставлено на `main` 27–28.10

| SHA | что | приёмка |
|---|---|---|
| `a5c871eb1` | ARB R1/R2 (ADR-839): ответ из сессии — только по точной записи реестра `docs/decisions/owner-answers-2026-10-27-session.json` (импорт оператора ≠ подтверждение личности); work packet: одобрение = задача·версия·предмет·проба, итог — только фактический запуск `card_acceptance.run_probe`; диспетчер пульта не берёт запись с предметом владельца без одобрения | прод `IN_SYNC` 28.10 03:48Z; `deployment_acceptance` OK; CI кандидата против базы: новых 0, прежних 56 (CI красный) |
| `5789d4fa3` | документы: запись поставки ADR-839; TELEGRAM-OWNER-UX-01 и TRADING-PROCESS-01 в `docs/ROADMAP.md` | документационная |
| `1032d7414` | ADR-849: §1 синхронизация кода возит `launchd/` (только копии в репо, без `launchctl`); §2 тесты не пишут в рабочие данные (18 побочных писателей цикла + `regime_gate` уважают `SPA_DATA_DIR` для УМОЛЧАНИЯ; база сторожа записи 7→0); §3 стенды переписей decision_loop — клон APFS | прод `SYNCED` 19:38Z и 19:48Z (первая синхронизация с `launchd/`: plist = origin); `deployment_acceptance` OK (92 entrypoints, 0 broken; 75 агентов импортируют цель); `fleet_parity` OK (было DRIFT); мутации 19: 17 убито, 1 эквивалентный, 1 дыра закрыта тестом |
| этот коммит | MAC-STORAGE-AUDIT-01 в бэклог (не начато); итог поставки ADR-849; этот хендовер | документационная |

Подробности и цифры: `docs/decisions/ADR-839-…`, `docs/decisions/ADR-849-ops-launchd-sync-test-isolation-decision-loop.md`,
доказательства `docs/evidence/arb-r1r2-2026-10-28/`, `docs/evidence/adr849-2026-10-28/`.

## 2. Что остаётся (не объявлено исправленным)

**Граница R1/R2:**
- Граница исполнения — только в диспетчере пульта. Сессия цикла, ручной запуск и записи без объявленного
  предмета не защищены.
- Подтверждённого канала одобрения плана нет — все одобрения сейчас `operator-import`.

**decision_loop (ADR-849 §3):**
- Одна пара стендовых прогонов: 92,6 → 74,0 мин. Повторяемое ускорение production НЕ подтверждено; расписание
  прежнее, такт > 6 ч.
- Сравнение выходов: 2 файла остаются различиями, 2 не подтверждены.
- Форма исхода `test_run_identity_key_price::…guard_is_lowered_again_after_a_sweep` failed→error на CI не
  атрибутирована; сам тест не укладывается в 180 с на CI.

**Найденные и НЕ исправленные дефекты:**
- `asset_registry_gap_price` зависит от `PYTHONHASHSEED` (21↔22 координаты при одних данных и часах).
- `run_identity_key_price` про читателя `/api/agents/registry` судит по живому флоту, а не по стенду.
- `test_adapter_repair_price::OrderOfEveryDayListIsPinned` падает при seed 1 и 4.
- Карточка «купить зонт в пятницу» висит в трекере как вопрос владельцу — похоже, тестовая заметка, попавшая
  в настоящий трекер; не тронута.

**Отдельные задачи:**
- `nimbalyst-local/tracker/agent-kartochka-diska-razoshlas-s-origin-sverka-17-iz-18.md` — 17/18.
- MAC-STORAGE-AUDIT-01 — бэклог, не начато.
- Денежный пакет ADR-836 — через `pre_cutover_gate`, отдельной поставкой.

**Состояние CI и машины:**
- CI `main` красный (63–72 failed в зависимости от коммита); `pytest==9.1.1` закреплён (ADR-841).
- Диск Mac: свободно колебалось 9–22 ГБ. Предохранитель ADR-551 не пускает «тяжёлые» прогоны при < 20 ГБ.
  Владелец 28.10 разрешил обход (`SPA_HEAVY_ADMISSION=off`) только для целевых тестов того окна — это не
  постоянное разрешение.

## 3. Следующий пакет — TELEGRAM-OWNER-UX-01 (готово к работе)

- **Каноническое задание (читать целиком, это ТЗ и критерии приёмки):** `docs/tasks/telegram-owner-alerts-2026-10-28.md`.
  Решение: `docs/decisions/ADR-OWN-2026-10-28-telegram-owner-ux.md`. Связь: TRP-06 в
  `docs/tasks/trader-patterns-backlog-2026-10-27.md`.
- **Доказательства ARB (вне репозитория, только чтение):**
  - `/Users/yuriikulieshov/.codex/.chatgpt-projects/g-p-6a59f58a0c008191bc21471feb38cbba/arb_2026-10-28/telegram_review/evidence.json`
    и `pdf_review_evidence.json` (хеши источников, чистые рендеры);
  - пользовательский PDF и извлечение: `…/attachment-review/telegram-noise-20261028/spa_monitor_noise_20261014_28.pdf`,
    `extracted.txt`, `page-3..5.png` (SHA256 PDF `a9cc7dba366fac6ff734c78cf807ba4592e72e84b61b0e64ebdb9d2663ae57f7`).
    Личные сообщения в GitHub не публиковать.
- **Код SPA (точки входа, проверено на `main`):**
  - `spa_core/monitoring/dashboard_watcher.py` — `check_agent_health`, все `healthy=False` → `down`;
  - `spa_core/telegram/reports/daily.py` — `_format_digest_section`: < 3 тел — сырые `event_key`;
  - `spa_core/telegram/humanize.py`, `spa_core/telegram/push_policy.py`, `spa_core/reporting/daily_telegram_report.py`.
- **Второй репозиторий:** `/Users/yuriikulieshov/Documents/earn-defi`.
  - `earn_defi/monitoring.py::_due`, `run`; `earn_defi/commit_reveal.py::_publish`.
  - Доказательства поставки раздельные. Секреты не читать и не выводить.
- **Порядок из задания:**
  1. сверить только затронутые пути;
  2. в изолированных деревьях — семантика состояния и рендер SPA, затем earn-defi;
  3. девять случаев PDF на временных фикстурах с фиктивным отправителем;
  4. целевые тесты, затем один полный CI на законченном кандидате;
  5. отчёт «было → стало».

  Без LLM в доставке и классификации, без новой системы уведомлений, без глушения CRITICAL. Kill-switch остаётся
  вне дневного лимита.

## 4. Как здесь работают (проверено в этом окне)

**Деревья и доставка:**
- Работать в worktree ПРОД-клона от `origin/main` (не в самом `~/Documents/SPA_Claude`, не от зеркала).
- Длинные прогоны — в отдельном дереве: два процесса в одном дереве делят `data/`.
- Доставка: дерево доставки на `origin/main`; `git checkout <кандидат> -- <файлы>`; `git reset --mixed origin/main`;
  `python3 push_to_github.py --dry-run --files <АБС. пути> --message … --expected-base <полный sha>`, затем без
  `--dry-run`. Затем `data/code_sync_status.json` → `SYNCED`/`IN_SYNC` с новым `origin_main`;
  `python3 -m spa_core.monitoring.deployment_acceptance`. Перед пушем — резерв прод-копий в
  `~/studio-os-serve/backups/<имя>_<ts>`.

**Номера ADR:**
- Только `python3 scripts/adr_number.py --base origin/main next`. Параллельные циклы занимали 843 и 846 в этом окне.
- Проверка: `… check --files <ADR> <mutations> docs/decisions/INDEX.md`.
- Строки `INDEX.md` — без пустых строк внутри таблицы, заголовок ≤ 200 символов (ADR-838).

**CI:**
- Запуск: `POST …/actions/workflows/ci-control.yml/dispatches` `{"ref":<ветка>,"inputs":{"sha":<полный sha>}}`.
  Токен: Keychain `GITHUB_PAT_SPA`.
- Скачивание: `fetch_ci_record(dest, run_id=)` (модуль есть в ветке integ:
  `/private/tmp/spa_wt_taskprep_20261025T234122Z`).
- Сравнение: `python3 scripts/ci_control.py compare base/report.json head/report.json`, плюс отдельно исходы
  failed/error и ТЕКСТЫ причин.
- Сверять `report.sha` и фактический checkout. Базу для точного сравнения пускать на пробной ветке с тем же sha.

**Прочее:**
- Мутации — только штатным `scripts/delta_mutation_run.py --spec docs/mutations/<ADR>.json`; после окна сверять
  байты (md5) и `--window-check`.
- Не делать: force-push, удаления, массовые перезапуски, правку `CLAUDE.md` (классификатор отказывает — текст
  отдать владельцу), денежный путь вне `pre_cutover_gate`.

## 5. Запуск нового окна

```
cd /Users/yuriikulieshov/Documents/SPA_Claude && claude
```

Первое сообщение в новом окне (скопировать целиком):

```
Продолжаем со следующего пакета: TELEGRAM-OWNER-UX-01. Прочитай хендовер
docs/evidence/telegram-owner-ux-01-2026-10-28/START_HERE.md и каноническое задание
docs/tasks/telegram-owner-alerts-2026-10-28.md (на origin/main), затем доказательства ARB по путям из хендовера.
Повторный общий аудит не делай. Работай в изолированном worktree от origin/main (SPA) и отдельно в
/Users/yuriikulieshov/Documents/earn-defi. Сначала сверь только затронутые пути с текущим кодом и назови план
по пяти пунктам задания; затем реализуй с тестами на временных фикстурах и фиктивном отправителе.
Ничего не удаляй, force-push и массовые перезапуски запрещены, денежный пакет не включай.
```
