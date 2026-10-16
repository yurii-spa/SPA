# Прерванный прогон pytest PID 87605 — ПРЕРВАН, НЕ ПРОЙДЕН

- Остановлен: 2026-10-16T00:07:35Z по указанию ARB (ошибочный состав).
- Запущен: около 22:21Z 2026-10-15 сессией Claude (STUDIO-OS-NEXT-01 пакет 2), из рабочей копии /tmp/spa_wt_res.
- Родитель: 87597 (/bin/zsh -c source /Users/yuriikulieshov/.claude/shell-snaps…), длительность 01:39:13.
- Рабочая папка: /private/tmp/spa_wt_res
- Дочерние процессы: нет
- Команда:
```
/Users/yuriikulieshov/miniconda3/bin/python3 -m pytest spa_core/tests/test_agent_research_factory_wrapper.py spa_core/tests/test_capital_shadow_failures.py spa_core/tests/test_capital_shadow_guards.py spa_core/tests/test_capital_shadow_keccak.py spa_core/tests/test_capital_shadow_lifecycle.py spa_core/tests/test_capital_shadow_owner_boundary.py spa_core/tests/test_capital_shadow_research_universe_reason.py spa_core/tests/test_capital_shadow_simulation.py spa_core/tests/test_hash_ledger_read_cache.py spa_core/tests/test_hash_ledger.py spa_core/tests/test_investment_cio_guards.py spa_core/tests/test_investment_cio_ledger.py spa_core/tests/test_investment_cio_parity.py spa_core/tests/test_investment_cio_policy.py spa_core/tests/test_investment_cio_research_universe.py spa_core/tests/test_investment_cio_sleeves.py spa_core/tests/test_investment_cio_susde_freshness.py spa_core/tests/test_mission_control_contract.py spa_core/tests/test_research_factory_core.py spa_core/tests/test_research_factory_failures.py spa_core/tests/test_research_factory_rework.py spa_core/tests/test_research_factory_rework2.py spa_core/tests/test_research_factory_scanners.py spa_core/tests/ -q -p no:randomly
```
- Ошибка состава: список собран из `ls spa_core/tests | grep … | tr '
' ' '` и `sed`; хвостовой пустой токен превратился в `spa_core/tests/` ⇒ в команду попал ВЕСЬ каталог: собрано 119 153 теста вместо выборки из 23 файлов.
- Версия проверяемого кода: база 2e1733136 + незакоммиченные правки на момент старта (кэш чтения hash_ledger БЕЗ заморозки строк; verify в обход кэша; judge_alone_price потоковый обход; mission_build включает кэш). Правки ПОСЛЕ старта (в прогоне не участвовали): заморозка строк кэша, часы чтения в company_truth, текст resource_guard, resource_policy.
- Промежуточный результат: вердиктов по тестам НЕТ — вывод шёл в конвейер `| tail -4` и до конца прогона не сохраняется. Косвенный прогресс: 52428 песочниц spa_isolated_data в /private/var/folders/6q/78j7h2557tx6hkbkw3cmrsc00000gn/T/pytest-of-yuriikulieshov/pytest-80 (≈ число начатых тестов с песочницей). Итог: НЕ ИЗМЕРЕНО.
- Временные каталоги (/private/var/folders/6q/78j7h2557tx6hkbkw3cmrsc00000gn/T/pytest-of-yuriikulieshov/pytest-80) НЕ удалялись.
- Остановка: SIGINT собственному процессу после проверки родителя (87597) и рабочей папки (/private/tmp/spa_wt_res); дочерних процессов не было. Прогон оркестратора PID 35918 и службы не тронуты. Ожидавшая цепочка сравнения (PID 21669) снята ДО остановки — ни одна сборка не стартовала.
- Сводка pytest при прерывании: `5 failed, 52418 passed, 210 skipped, 863 subtests passed in 5955.10s (1:39:15)` — KeyboardInterrupt. Имена 5 падений НЕ сохранены (вывод через `| tail -5`) ⇒ отнесение к правкам или к базе origin НЕ ИЗМЕРЕНО. Вердикт прогона: ПРЕРВАН.
