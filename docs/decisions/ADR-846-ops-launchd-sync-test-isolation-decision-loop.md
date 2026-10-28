# ADR-846 · Пакет эксплуатации 28.10: синхронизация launchd, изоляция тестов от рабочих данных, ускорение decision_loop

- **Статус:** Accepted (по пунктам — ниже)
- **Дата:** 2026-10-28
- **Основание:** ARB 27.10 (`docs/evidence/arb-r1r2-2026-10-28/ARB_REVIEW.md`: «независимо можно продолжать
  согласованные работы: синхронизация launchd без массовых перезапусков, изоляция семи тестовых модулей от
  runtime data и ускорение decision_loop с проверкой равенства решений») и задание 28.10. decision_loop —
  ответ владельца ADR-836 («расписание не менять; ускорить прогон»).
- **Не входит:** денежный пакет ADR-836, TELEGRAM-OWNER-UX-01. Службы не перезапускались, расписания не менялись.

## 1. launchd: plist агентов не доезжали до прод-дерева

**Дефект.** `scripts/code_sync_from_origin.sh` возит `spa_core scripts tests architecture` + пушеры + инструкции,
но не `launchd/`. Установщик (`install_all_agents.sh`) и сторож паритета флота читают plist ИЗ прод-дерева.
Замер 28.10 (прод-дерево против `origin/main`): нет четырёх plist (`btc_nav`, `director_build`, `director_server`,
`trading_research`), три отличаются (`orchestrator`, `source_discovery`, `tracker_status_sentinel`), два лишних
старых (`golive_freshness`, `resilience` — на origin их нет). `data/fleet_parity.json`: `DRIFT`,
`broken_declared_no_plist = [director_build, director_server]` — при том, что оба агента РАБОТАЮТ
(`live.declared_not_running = []`): постоянная ложная строка.

**Исправление.** `launchd` добавлен в `CODE_PATHS` третьим некодовым исключением; правило записано в шапке
скрипта. Синхронизация сводит только КОПИИ в репозитории: она не устанавливает, не загружает, не выгружает и не
перезапускает агентов, `~/Library/LaunchAgents` не трогает. Лишние старые plist не удаляются (checkout не
удаляет) — их называет `retired_code` статуса синхронизации.

**Критерий завершения.** После первой синхронизации с этим кодом: прод-копии plist, которые есть на origin,
побайтно равны origin; `fleet_parity` больше не называет `director_build`/`director_server` сломанными;
ни одного вызова `launchctl` синхронизацией.

**Проверки.** `scripts/tests/test_code_sync_from_origin.py` (синтетическая пара репозиториев, настоящий скрипт):
изменённый и новый plist с origin доезжают, подменный `launchctl` в PATH не вызван ни разу;
`spa_core/tests/test_code_sync_paths.py`: `launchd` в списке, исключение объяснено в скрипте.

## 2. Семь тестовых модулей писали в рабочее состояние

**Дефект (замер сторожем `tracked_write_guard` 28.10 в изолированном дереве).** База сторожа держала 7 модулей
`tests/`, и трое из них к 28.10 писали уже ШИРЕ базы. Причины:
- `test_hy_cycle` → `data/hy_regime_log.json`: тест подменял путь в `hy_cycle`, а писатель
  `regime_gate.log_regime_change` держал СВОЮ копию пути (третья копия константы).
- `test_market_regime` → `data/market_regime.json`: CLI всегда писал в `<repo>/data` и читал живой
  `adapter_status.json`.
- `test_tear_sheet` → `data/tear_sheet_summary.json`: два теста звали генератор на живом `data/`.
- `test_uptime_monitor` → `data/uptime_status.json`, `uptime_prev_state.json`: смоук `main()` на живом дереве.
- `test_e2e_seams`, `test_perf_budget`, `test_type_safety`: цикл с временным `data_dir`, но 18 побочных
  писателей брали путь от своего `__file__` (часть — относительно cwd). Под запись попадали трекер APY,
  gap_monitor (+ `risk_alerts`), генератор статуса адаптеров и 15 модулей сигналов (журналы через
  `signal_aggregator` в потоках, включая `spa_core/data/*`). Трассировка аудит-хуком: 19 файлов.

**Исправление.** Без ослабления утверждений и без skip:
- `spa_core/utils/data_dir.default_file(path, default)` — принятый механизм `SPA_DATA_DIR`, но только для
  УМОЛЧАНИЯ модуля: явно переданный или подменённый тестом путь не трогается. **Без переменной путь бит-в-бит
  прежний** (в т. ч. относительный).
- Через него идут 18 побочных писателей и `regime_gate` (путь журнала стал входом, `hy_cycle` передаёт свой).
- CLI `market_regime` и `uptime_monitor.main` получили `--data-dir`; без ключа — прежний `<repo>/data`.
- Тесты пишут во временные каталоги. `tear_sheet` читает git-tracked снимок
  `tests/fixtures/tear_sheet_full/` (data/ на 28.10, ряды обрезаны до 400 точек, все 12 разделов отчёта на
  месте) вместо живого `data/`. `test_e2e_seams` выставляет `SPA_DATA_DIR` на время цикла в фикстуре уровня
  модуля (она поднимается раньше пер-тестового заслона).

**Критерий и результат.**
- `tracked_write_baseline.json`: 7 модулей → 0.
- `data_dir_env_baseline.json`: 242 → 240 (`apy_milestone_tracker`, `gap_monitor` больше не обходят
  `SPA_DATA_DIR`; храповик сам потребовал убрать их).
- Трассировка записи по всем семи модулям: 0 записей в `data/` и `spa_core/data/`.
- Целевой прогон 95 файлов (изменённые модули и их тесты, `SPA_HEAVY_ADMISSION=off` по решению владельца при
  диске 18,7 ГБ < 20 ГБ): новых падений нет.
  - 7 падений воспроизводятся и на чистом `main`: `python_git_ref_provenance` ×4, `shell_git_cd_target_census`
    ×2, `unwired_scripts_ratchet` — окружение worktree.
  - `test_owner_briefing::…remote_url_or_a_raw_response` упал один раз в общем прогоне, отдельно проходит
    дважды. Причина не установлена; к правке не относится.

**Изменения тестового контракта (инв. #16)** — запись в `docs/journal/2026-W44.md`.

**Не сделано.** Чтение живого `data/` этими писателями вне песочницы не менялось (например, gap_monitor читает
`equity_curve_daily.json` по своему пути). Остальные ~238 модулей базы `data_dir_env` — прежний долг.
