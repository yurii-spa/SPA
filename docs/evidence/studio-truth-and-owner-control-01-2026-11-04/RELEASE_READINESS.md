# STUDIO-TRUTH-AND-OWNER-CONTROL-01 · план релиза и отката (ревизия ARB 04.11)

**Ничего не влито.** Слияние в `main` — production change: агенты сами синхронизируют прод-дерево с `origin/main`
(`scripts/code_sync_from_origin.sh`, ≤10 мин). Поставка — только через PR (`freeze-main-phase0`: PR обязателен,
0 одобрений, обход админом существует, но НЕ используется). Без force push.

Неизменно на всех стадиях: KC-1 не снимается · капитал $0 · RiskPolicy/RiskConfig не тронуты · ADR-762 OFF ·
decision_loop OFF · E6.6 OFF · push BUY/SELL OFF · без root/sudo.

## Стадия A — SPA (Director OS + SPA Monitor)

| | |
|---|---|
| PR | `truth/owner-control-01` → `main`: https://github.com/yurii-spa/SPA/compare/main...truth/owner-control-01 (токен не умеет создавать PR — создаёт владелец кнопкой «Create pull request») |
| Измеренный код | `6f902ebed` = вершина `main` `01b144031` + ветка; CI 41923432402 (NEW 0) — см. HANDOVER, ревизия 3. Всё после `6f902ebed` — только `docs/` |
| Способ слияния | **«Create a merge commit»** (не squash/rebase): дерево merge-коммита = дереву измеренного кандидата, если `main` не ушёл; если ушёл — сначала обновить ветку и повторить CI |
| Production-компоненты | read models пульта (`mission_control`, `company_truth`, `owner_view`, `trading_engines`, `director_report`, `mission_ui`), экраны SPA-бота (`views/home`, `views/golive`, `views/_base`), досылка кнопок (`owner_decisions`, `bot.py`), сторож сайта (`scripts/site_freshness_monitor.py`), `investment_cio/sources_summary`, `trading_research/read_model`, `utils/presentation` |
| Рестарты | `mission_control` пересоберёт пульт сам (5 мин), `mission_server` не меняется; `telegram_bot` — долгожитель: сторож `telegram_health` сам перезапускает его при устаревшем коде (наблюдалось 03.11, ADR-117). Ручной рестарт не нужен |
| Один poller | после рестарта: `ps -axo pid,command \| grep "[-]m spa_core.telegram.bot"` — ровно 1 строка; `/tmp/spa_telegram_health.log` — «поллеры: ровно один»; 0 строк `409` в `/tmp/spa_telegram_bot.log` |
| Источники финансовых статусов | пульт: `overview.investment` = `earn_defi.db#system_state` (INCIDENT, KC-1 с 19.09); бот «Движки» — та же функция `trading_engines.investment_engine_modes`; книги — `last_cycle_at` из `data/*_paper_trading.json` |
| Проверка после доставки | `data/code_sync_status.json` = merge-SHA, байты 19 файлов кода = origin; `deployment_acceptance` OK; коды `launchctl` = до; новая сборка `~/studio-os-serve/mission/current.json` после синка; в ней `overview.investment.state=CRITICAL`, `owner_view…questions.count=0`, `subject_undeclared=2`; бот `/start` — строка «Движки ⛔» |
| Стоп | `deployment_acceptance` ≠ OK · `mission_control` код ≠ 0 два раза подряд · бот молчит > 5 мин или 2 поллера · пульт показывает «система OK» при INCIDENT |
| Откат | revert-PR на GitHub (кнопка «Revert» у слитого PR) ⇒ для merge-коммита это `git revert -m 1 <merge>`; синк вернёт изменённые файлы за ≤10 мин. Добавленные тест-файлы (`test_truth_owner_control_01.py`, `test_company_truth_open_questions.py`) синк НЕ удаляет (называет в `retired_code`) — безвредно, их не импортирует ни один агент. Бот получит старый код через `telegram_health` |

## Стадия B — earn-defi (дедуп уведомлений)

| | |
|---|---|
| Ветка | `truth01/alert-state-change` `97ca68d` (2 коммита над `main` `21c125e`); лежит в локальном репо `~/Documents/earn-defi` |
| Проверки | 225 passed (полный набор), в т.ч. первое уведомление, повтор, эскалация, напоминание 72 ч, выживание после рестарта процесса |
| Доставка на GitHub | токен агента не видит приватный репо ⇒ владелец одной командой в своём терминале: `git -C ~/Documents/earn-defi push origin truth01/alert-state-change` (его учётные данные, секретов в чат не нужно); PR и слияние — в UI |
| Production | `com.earn-defi.daily` (12:10/22:10) и `com.earn-defi.monitor` читают рабочее дерево `~/Documents/earn-defi` (`main`) — **после слияния на GitHub код попадёт в прод только после `git -C ~/Documents/earn-defi pull --ff-only`** (синка у earn-defi нет; делает агент по разрешению) |
| Рестарты | не нужны (агенты по расписанию) |
| После доставки | следующий прогон: в `alerts` новая строка `system.mode` НЕ появляется (`delivered=1`), `run_log` — `suppressed` растёт; через 72 ч — одна строка «напоминание (без изменений с 2026-09-19…)» |
| Стоп | любой сбой `run_log` monitor/daily · пропала доставка НОВОГО CRIT (проверка — тест эскалации) |
| Откат | revert-PR на GitHub earn-defi → `git -C ~/Documents/earn-defi pull --ff-only`; таблица `alerts` только дописывается, история не теряется |

## Стадия C — Studio Bridge

| | |
|---|---|
| Ветка | `b19.7-integration` `3f63ad7` = `b19.7-truth-owner-control` `906f2de` + ПОБАЙТНО сохранённые 4 незакоммиченные правки MCP-сессии 10–11.10 (патч `release_evidence_2026-11-04/bridge_uncommitted_2026-10-11.patch`, sha256 `40cfd1d8…`) |
| Проверки | полный набор: `main` 46 failed / 1914 passed · `b19.7` 46 / 1921 · интеграция 46 / 1924 — имена упавших тождественны (43 `test_mandate_reactivation`, 2 `test_launch_catalogue`, 1 `test_mcp_server`) |
| Production | `com.studiobridge.telegram` (PID 1581) исполняет `~/Documents/studio_bridge` на `main` с этими же 4 незакоммиченными правками в рабочем дереве |
| Доставка (отрепетировано на клоне 04.11) | 1) `git -C ~/Documents/studio_bridge diff \| shasum -a 256` = `40cfd1d8…` (= патч в evidence и = правки в ветке); 2) `git checkout -- README.md bridge/mcp_server.py docs/handoffs/CURRENT-HANDOFF.md tests/test_mcp_server.py` (правки сохранены в ветке и патче); 3) `git checkout b19.7-integration`; 4) `git status` пуст, sha256 четырёх файлов = до; 5) рестарт `com.studiobridge.telegram` по разрешению. Простой `git checkout` без шага 2 ОТКАЗЫВАЕТ («local changes would be overwritten») — замер репетиции |
| Один poller | `ps -axo pid,command \| grep "[s]tudio_bridge/scripts/telegram_bot.py"` — ровно 1 |
| После | Bridge «Продукт» — 5 из 5; кнопки разделов правят сообщение; «🏛 Домой»; одобренные не «ждут решения» |
| Откат | `git -C ~/Documents/studio_bridge checkout main && git -C ~/Documents/studio_bridge apply <evidence>/bridge_uncommitted_2026-10-11.patch` — дерево ровно как до доставки (main + 4 незакоммиченные правки) + рестарт |

## Канарейка
A → наблюдение 24 ч (2 цикла earn-defi, 1 дневной цикл SPA, сторож бота) → B → наблюдение до следующего прогона
earn-defi → C. Между стадиями — проверка «один poller» и `deployment_acceptance`.

## Не сделано (честно)
296 px не измерялось (контура нет; 390/430 — 16/16 OK) · полная вычитка RU/EN · `resolve("cycle_failed")` в
`cycle_runner` (денежный путь) · сторож сайта в GitHub Actions: подавление повторов НЕ доказано (свежий checkout,
исход `dedup: not_measured`); единственный ли это канал — нет: тот же сторож на Mac (launchd, с дедупом) шлёт в тот
же чат, поэтому отключение CI-отправки не оставит критический сигнал без канала, но решение — владельца.
