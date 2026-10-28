# ADR-849 · Пакет эксплуатации 28.10: синхронизация launchd, изоляция тестов от рабочих данных, ускорение decision_loop

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
