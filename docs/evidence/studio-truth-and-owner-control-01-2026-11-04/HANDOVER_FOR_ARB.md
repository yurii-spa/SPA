# HANDOVER FOR ARB · STUDIO-TRUTH-AND-OWNER-CONTROL-01 (04.11)

Вход: [QA_FINDINGS_MATRIX](QA_FINDINGS_MATRIX.md) · [OWNER_TRUTH_CONTRACT](OWNER_TRUTH_CONTRACT.md) ·
[RELEASE_READINESS](RELEASE_READINESS.md) · [IPHONE_ACCEPTANCE](IPHONE_ACCEPTANCE.md) · ADR-917.

## Кандидат
| Репо | Ветка | SHA | База |
|---|---|---|---|
| SPA | `truth/owner-control-01` (на origin; PR не создан — у токена нет права `createPullRequest`) | `0271cf33b` | `main` `bc2b1b322` (код = `50558c956`) |
| earn-defi | `truth01/alert-state-change` (ЛОКАЛЬНО: токен не видит приватный репо) | `fc538c2` | `main` `21c125e` |
| Studio Bridge | `b19.7-truth-owner-control` (локальный репо без remote) | `906f2de` | `main` `2ff10bc` |

## Проверки
* SPA, дифференциально, 131 файл, затронутый правкой (+2 новых): база `71498dc26` — 5 failed / 3230 passed; ветка —
  те же 5 failed, причины тождественны, +32 новых теста зелёные. Первая итерация дала 31 новое падение — все устранены
  КОДОМ, существующие тесты не менялись.
* Мутации: 13 целевых мутантов по ключевым инвариантам — 13 убиты (один выживший в первом заходе закрыт тестом).
* Независимое ревью: 6 дефектов в коде программы — исправлены (матрица, раздел «Независимое ревью»).
* ci-control кандидат-1 `1633895ab` (41821704884) против базы `50558c956` (41802006336): нашёл 2 класса регрессий
  ветки — храповик инв. #17 (`rec.get(...) or []`) и доска трекера без новой карточки; оба исправлены в `0271cf33b`.
  Остальные новые имена — `list_identity_census` (таймаут 180 с на раннере, известен с 03.11).
* ci-control финальный `0271cf33b`: 41828977029 · 12/12 шардов · 52 failed + 1 error против 51 + 1 у базы 41802006336 · единственное новое имя — `list_identity_census…candidate_outside` (таймаут 180 с в `ast.parse` на раннере; тот же тест так же падал на r1 03.11, локально 66–68 с на базе и ветке) · ушедших 0 · +32 новых теста, все зелёные · skipped 720 = 720 · `tracked_write_guard`: новых 0 · E-строки «frozen-date» — чужой `test_edge_crisis_recovery_profile.py`, красен и на `main`. **Регрессий состава нет.**
* earn-defi: 224 passed. Bridge: 1010 passed, 1 failed — тот же `test_launch_catalogue` красен на чистом `main` Bridge (`.DS_Store`).
* Вёрстка (существующий headless-контур `_mission_trading_layout`): 16/16 сцен OK на 390 и 430 px. 296 px — не
  измерялось (контура нет); iPhone — ручная проверка владельца.

## Безопасность
Реальный капитал $0 · KC-1 не снят, NAV не пересчитан, порог 2 % не тронут · RiskPolicy/RiskConfig, kill switch, allocator,
cycle_runner, стратегии, ставки, позиции, `landing/`, расписания — не тронуты · ADR-762 OFF · decision_loop/aggregate/E6.6/
push сигналов не включались · прод-службы не перезапускались · тесты — с заглушённым Keychain и трекером-ловушкой,
ни одной отправки в Telegram · история чатов и карточек не удалялась · в `main` ничего не влито.

## Решения владельца
1. Слияние SPA PR (создать PR владельцем или дать токену право Pull requests: write).
2. earn-defi: слить ветку (или дать токену доступ к репо earn-defi, чтобы агент запушил её).
3. Bridge: переключить основной репо на `b19.7-truth-owner-control` (там 4 чужие незакоммиченные правки) и перезапустить
   `com.studiobridge.telegram`.
4. KC-1: снять блокировку (карточка `owner-decision-snyat-li-blokirovku-earn-defi-kc-1`).
5. Сторож сайта в GitHub Actions: хранить отпечаток (actions/cache) или не слать из CI.
6. Push сигналов BUY/SELL — по RFC, отдельно (сейчас OFF).
