# STUDIO-OS-NEXT-01 — доказательства (2026-10-16)

Директива владельца 16.10 (ADR-763) и замечания ARB 16.10. Всё здесь — копии из временных папок сессии,
чтобы доказательства пережили перезагрузку. Большие журналы не копировались: указан их sha256 и размер.

| Файл | Что доказывает |
|---|---|
| `aborted_run_87605.md` | ошибочный полный прогон: команда, версия кода, промежуточная сводка, причина остановки — ПРЕРВАН |
| `frozen_equivalence.txt`, `frozen_eq.py`, `model_diff.py` | сборка пульта с кэшем/без на замороженных данных: 0 различий, 11,4 с против 992 с |
| `resource_targeted_tests.txt`, `resource_targeted_test_files.txt` | окончательный набор пакета ресурсов (27 файлов): 1055 passed |
| `ranking_tie_*.summary.json`, `ranking_tie_logs.txt`, `ranking_tie_before_distinct_messages.txt` | ranking_tie до/после на одинаковых входах |
| `cockpit_e2e_run.mjs` | песочница: настоящий mission_build + mission_server + headless Chrome, 17/17 |
| `mission_server_restarts.txt` | два перезапуска по разрешению владельца и проверки |
| `live_checks.md` | что проверено в работающей системе и что ещё нет |
| `ci_status_2026-10-16T0430Z.txt` | CI по каждому коммиту; отменённое и упавшее — не успех |
