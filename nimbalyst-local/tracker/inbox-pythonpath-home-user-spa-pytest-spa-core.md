---
trackerStatus:
  type: inbox
title: "PYTHONPATH=/home/user/SPA pytest spa_core/tests/test_s{76,41,73,77,22}*.py -q →…"
status: done
source: telegram
created: 2026-08-05
---

## Задание (из Telegram)

PYTHONPATH=/home/user/SPA pytest spa_core/tests/test_s{76,41,73,77,22}*.py -q → 0 failed.
 • compileall чисто.
 • Регресс-проверка: полный прогон до/после даёт идентичный набор предсуществующих падений (методология «git stash → diff», ноль регрессий).
 • Каждая стратегия покрыта минимум по: allocate/get_allocation, порог/режим, инвариант суммы весов, депег/eligibility-гейт, детерминизм.

Файлы

 • Новые: spa_core/tests/test_s76_concentrated_lp.py, …_s41_…, …_s73_…, …_s77_…, …_s22_ethena_yield_max.py.
 • Эталон: spa_core/tests/test_s2_lp_stable.py, test_s7_pendle_yt_aggressive.py.
 • Читать (не менять): соответствующие spa_core/strategies/s*.py.

Риски / примечания

 • s22 тянет адаптеры Ethena — обязательно мокать, иначе сетевые 403.
 • Пороговые сравнения (> vs ≥ у 6%) — вероятный источник off-by-one; фиксируем текущее поведение тестом, а не «правим» без ADR.
 • Задача не меняет логику стратегий — только фиксирует контракт тестами.

ЗАДАЧА 2 — AUD-19 / ADR-027: Volatile CLMM (ETH/stable) как новый класс дохода — research + гейт

Тип / приоритет

🟠 MEDIUM (архитектурная, требует решения Owner) · research + код-гейт + тесты · оценка ~2–3 дня · нужен ADR

Проблема

На скриншоте (Revert, Uniswap V4 ETH/USDG 0.05%, fee APR ~79%) — это волатильный concentrated-LP маркетмейкинг с направленной ETH-ногой и impermanent/divergence loss. У нас:

 • policy_lp.py (Engine C) принимает только delta-neutral стейбл-пары (require_delta_neutral=True), TVL пула ≥ $50M.
 • Все LP-стратегии (s2/s41/s76) — стейбл/стейбл, T2, ~6%.
 • Волатильного ETH/stable CLMM нет ни как адаптера, ни как стратегии, ни в турнире; USDG не в whitelist.
 • Прогон политики на числах скриншота → approved:False (не delta-neutral / fail-closed по TVL).

Вопрос Owner-решения: вводим ли мы этот класс (ожидание ~20% на споте), и если да — как ограничиваем риск IL/range-exit/направленности.

Область работ (scope)

Часть A — Research-заметка (docs/research/RS-volatile-clmm.md)

 • Декомпозиция дохода: fee APR = f(объём, ширина диапазона, доля ликвидности) − divergence loss − газ/ре-рейндж.
 • Модель impermanent/divergence loss для CLMM: взять готовую квадратичную аппроксимацию из s21_cashflow_research.py (_IL_AMPLIFIER=2.0, «concentration factor vs full-range v2») и переиспользовать/сослаться.
 • Оценка range-exit probability: при ширине ±10–20% и волатильности ETH — доля времени out-of-range, частота ре-рейнджа, реализованный IL за цикл.
 • Честный net-APY на споте после IL и газа (не 79%, а сколько реально остаётся; проверить гипотезу «~20%»).
 • Вывод: класс сохраняем только в двух формах — (a) delta-neutral (хедж ETH-ноги перп-шортом, как S8) либо (b) строго advisory T3-SPEC без авто-открытия.

Часть B — Классификация в модели

 • Отнести к T3-SPEC (advisory-only, аналогично Pendle YT / ADR-021): не открывает позиции автоматически, approved=False не переопределяется.
 • В yield_classifier_agent: источник — real_cashflow (fee revenue), но с флагом направленного риска. Добавить в BOOTSTRAP_CLASSIFICATIONS при вводе.
 • Обновить protocol_risk_map.py: risk_score > 0.60 (T3), заметка «volatile CLMM: IL + range-exit + directional».

Часть C — Гейт (детерминированный, LLM-forbidden)

 • Расширить policy_lp.py (или отдельный подблок) для directional-CLMM: новые лимиты (kill по IL-drawdown, max range width под волатильность, обязательный хедж-флаг для допуска, min pool TVL, min fee-volatility CV).
 • Правило: directional CLMM approved=True только если is_delta_neutral=True (т.е. ETH-нога захеджирована) или позиция помечена advisory и не идёт в исполнение.
 • Любое изменение лимитов → новый ADR + snapshot в spa_core/risk/versions/ (версия policy.py остаётся v1.0, LP-политика — свой version-bump по ADR).

Часть D — (опционально, если Owner одобрит форму delta-neutral) стратегия-скелет

 • s78_dn_volatile_clmm.py (advisory, read-only, stdlib): LP fee-нога + перп-шорт ETH-хедж, get_allocation, get_expected_apy, get_risk_summary, самолог IL. Регистрация в турнире как T3-SPEC advisory.

Часть E — Тесты

 • test_policy_lp_directional.

---
_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку со ссылкой на порождённую работу (§6.4)._

---

## Разобрано циклом #121 (2026-08-05)

Одно твоё сообщение бот разбил на три карточки — это три части ОДНОГО задания
(AUD-18 + AUD-19). Разобраны вместе, чтобы не плодить дубли.

- **AUD-18 (тесты на пять стратегий) — СДЕЛАНО:** `agent-aud18-strategy-unit-tests.md`.
  Пять файлов в `spa_core/tests/`. По дороге замерено, что покрытие было не таким,
  как в задании: тесты у этих стратегий есть (в `tests/`), но расчёт доходности
  `compute_weighted_apy` у s76 и s73 **не исполнялся ни разу** — именно он и течёт
  в турнир. Подробности и таблица замера — в карточке.
- **AUD-19 (волатильный CLMM ETH/стейбл) — НЕ БЕРУ САМ, ждёт тебя:**
  `own-aud19-volatile-clmm-vvodim-li-klass.md`. Он меняет правила допуска
  (`spa_core/risk/policy_lp.py`), а это можно только с твоего решения — ты и сам
  написал, что задача упирается в него. Там же три варианта и рекомендация.
- Найденный по дороге дефект (s76 угадывает единицу измерения доходности по величине
  числа) молча не чинится — карточка `agent-s76-apy-unit-guess.md`.
