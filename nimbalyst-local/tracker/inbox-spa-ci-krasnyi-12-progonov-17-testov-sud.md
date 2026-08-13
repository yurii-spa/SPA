---
trackerStatus:
  type: inbox
title: "SPA CI красный 12 прогонов: 17 тестов судят о ХОСТЕ (нет launchctl на Linux, cwd=spa_core), не о коде"
status: new
source: nimbalyst
created: 2026-08-13
---

## Что измерено (цикл #221, 2026-08-13)

Воркфлоу **`SPA CI`** на `main` красный подряд как минимум 12 прогонов (11:13Z→19:38Z),
**17 падений** — и это ДРУГАЯ причина, не та, что чинилась в цикле #221 (`SPA Tests`,
непереносимый `stat`, закрыто).

Измеренная разница сред: этот job гоняет тесты не от корня репозитория, а
`cd spa_core && python -m pytest tests/` (`.github/workflows/ci.yml`). Плюс раннер — Linux,
а не macOS. Падения делятся на два семейства:

**(1) `launchctl` нет на Linux — 12 падений**, все в
`spa_core/tests/test_deploy_gate_long_lived.py`: `FileNotFoundError: 'launchctl'`. Тесты приехали
циклом #185 (статический пробник агентов). Локально на Маке они зелёные, потому что `launchctl`
здесь есть — то есть тест проверяет ХОСТ, а не поведение кода.

**(2) относительные пути ломаются под `cd spa_core` — 5 падений:**
- `test_sleeve_seeding_lock.py::test_live_modules_use_this_condition` — `FileNotFoundError:
  'spa_core/paper_trading/hy_cycle.py'` (путь от корня, а cwd — `spa_core/`);
- `test_owner_gate_approval_scope.py` (2 теста) — scope прочитан как
  `['spa_core/landing/src/pages/packages.astro']` вместо `['landing/…']`;
- `test_telegram_flood_shared.py::test_the_rate_limit_state_lives_in_the_live_tree` —
  ожидает `<repo>/data`, получает `<repo>/spa_core/data`;
- `test_deploy_gate_long_lived.py::…::test_telegram_bot_target_module_resolves`.

Что здесь ГИПОТЕЗА, а не замер: связь семейства (2) именно с `cd spa_core` выведена из текста
ошибок и текста workflow, отдельным прогоном в этот цикл НЕ перепроверялась. Диагноз в карточке —
гипотеза, пока его не измерили (урок #175).

## Что сделать

1. Перепроверить (2) прогоном `cd spa_core && python -m pytest tests/<файл>` на Маке — это
   воспроизводимо локально, Linux для него не нужен.
2. Для каждого падения назвать, кто неправ: **тест**, который судит о хосте/cwd, или **код**,
   который зависит от cwd. Если код читает пути от cwd — это находка прода (агенты стартуют из
   разных каталогов), а не удобство теста.
3. `launchctl` НЕ обходить скипом (инв. #16): поведение обязано проверяться и на Linux —
   подставлять заглушку на PATH, а не выключать проверку. Скип = потеря 12 проверок гейта деплоя,
   который и так недавно ловил настоящую аварию.
4. Закрепить положительным контролем в обе стороны.

## Границы

Прод-дерево, права и деплой агентов не трогать (`.claude/rules/deployment.md`). Пороги RiskPolicy,
kill-switch и живой трек — не сюда.

Родитель: `inbox-test-agent-template-code-sync-krasneet-t` (цикл #221).
