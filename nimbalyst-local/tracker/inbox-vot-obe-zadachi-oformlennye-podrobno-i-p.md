---
trackerStatus:
  type: inbox
title: Вот обе задачи, оформленные подробно и по отдельности — в стиле карточек проект…
status: done
source: telegram
created: 2026-08-05
---

## Задание (из Telegram)

Вот обе задачи, оформленные подробно и по отдельности — в стиле карточек проекта (MP-/AUD-), готовые к заведению в бэклог.

ЗАДАЧА 1 — AUD-18: Unit-тесты на непокрытые высокодоходные стратегии

Тип / приоритет

🟡 MEDIUM · read-only / advisory · безопасно (тесты не меняют рантайм) · оценка ~1–1.5 дня

Проблема

Из «доходных» стратегий турнира по-штучные unit-тесты есть только у s2_lp_stable и s7_pendle_yt_aggressive. Остальные — без собственных тестов, хотя они участвуют в турнире и влияют на аллокацию через multi_strategy_runner:

Стратегия ID Tier APY (min–max) Ключевой риск без теста
s76_concentrated_lp S76 T2 2–18% режимный свитч LP↔lending по порогу 6%; веса
s41_amm_stable_yield S41 T2 3–8% suspend+renorm пулов, эмиссии AERO/VELO
s73_leverage_loop S73 T3 4–12% effective_apy с плечом, is_eligible
s77_points_farming S77 T3 5–40% compute_points_adjusted_apy, активные кампании
s22_ethena_yield_max S22 T3-ish 6–14% ethena_depeg_active, get_allocation, депег-гейт

Без тестов любая регрессия в весах/порогах молча протекает в турнир и в advisory-аллокацию.

Область работ (scope)

Создать по одному тест-файлу на стратегию в spa_core/tests/, конвенция — как в test_s2_lp_stable.py (unittest, sys.path.insert(parents[2]), локальные хелперы-фикстуры _apy_data(...), без сети, без записи на диск).

Пофайлово — что покрыть (по фактическим сигнатурам):

test_s76_concentrated_lp.py — класс S76ConcentratedLP:

 • allocate(apy_data) при aerodrome_usdc_lp > 0.06 → режим LP: веса {aerodrome_usdc_lp:0.60, aave_v3:0.25, cash:0.15}.
 • allocate(apy_data) при lp_apy ≤ 0.06 → retreat: {aave_v3:0.50, compound_v3:0.35, cash:0.15}.
 • Инвариант: сумма весов == 1.0 (в обоих режимах, с толерансом 1e-9).
 • current_regime(apy_data) возвращает корректную метку на обеих сторонах порога (включая ровно 0.06 — проверить граничное поведение > vs ≥).
 • compute_weighted_apy() совпадает с ручным расчётом из docstring (LP active ≈ 5.97%, LP off ≈ 3.43%) в пределах допуска.
 • get_info() содержит STRATEGY_ID="S76", RISK_TIER="T2", границы APY.
 • Cash-буфер всегда ≥ 15% (соответствие RiskPolicy).

test_s41_amm_stable_yield.py — класс S41AmmStableYield:

 • _drop_suspended_and_renorm(...) — при выпадении пула веса ренормируются к 1.0, отсутствующий пул исключается.
 • get_allocation(...), get_expected_apy(...) в диапазоне 3–8%.
 • simulate(...), to_dict(...) — структура ключей, детерминизм (2 вызова → идентичный dict).

test_s73_leverage_loop.py — класс S73LeverageLoop:

 • effective_apy(...) — проверить формулу плеча на 2–3 числовых кейсах (в т.ч. отрицательный спред borrow>supply → APY падает/отрицателен).
 • is_eligible(...) — граничные условия (утилизация/LTV) True/False.
 • allocate(...) сумма == 1.0; compute_weighted_apy() в 4–12%.

test_s77_points_farming.py — класс S77PointsFarming:

 • compute_points_adjusted_apy(...) — базовый APY без поинтов == нижняя граница; с активной кампанией растёт к пику 40%.
 • active_campaigns() — тип/структура; allocate(...) сумма == 1.0.
 • Проверить, что «поинты» не оверрайдят approved=False (advisory-инвариант).

test_s22_ethena_yield_max.py — класс EthenaYieldMaxStrategy:

 • ethena_depeg_active() True → get_allocation(capital) уходит в защиту (доля sUSDe → 0 / cash растёт). Замокать источник цены (без сети).
 • _is_eligible(adapter_key) для депег-кейса.
 • get_expected_apy() в 6–14%; simulate/get_health/to_dict — ключи + детерминизм.
 • _load_adapters / _get_adapter_apy — замокать адаптеры, чтобы тест не ходил в сеть (иначе будет sandbox-403).

Общие инварианты (проверять в каждом файле)

 1. Read-only / advisory: IS_ADVISORY = True, стратегия не пишет в data/, не импортирует execution/.
 2. Детерминизм: два одинаковых вызова → идентичный результат.
 3. Сумма весов == 1.0 и cash-buffer ≥ 5% (где применимо ≥ 15%).
 4. approved=False от RiskPolicy не переопределяется стратегией.
 5. Никакой сети: все APY-данные через фикстуры/моки; ни один тест не должен падать в offline-sandbox.
 6. stdlib-only, unittest, без внешних зависимостей.

Acceptance criteria

 • 5 новых файлов, все зелёные в offline-режиме:

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
