---
trackerStatus:
  type: agent
title: Сделать турнир стратегий ДОВЕРЯЕМЫМ — ранжировать по net-of-cost APY на реальных исторических данных (не Sharpe на mock)
status: backlog
source: session-2026-07-23-owner-investigation
created: 2026-07-23
priority: high
domain: strategy evaluation (advisory; не двигает капитал; связано с ADR-055)
---

## Что нашли (2026-07-23)

Турнир САМ признаёт себя недоверяемым. В `data/strategy_tournament.json`:
- `trustworthy: false`;
- `trust_reason`: «Real DeFiLlama data but stablecoin yield is near-deterministic → Sharpe degenerate
  by asset class; a Sharpe leaderboard is not a trustworthy live ranking. Rank by net-of-cost APY instead.»;
- `data_quality: DEGENERATE` — median Sharpe **70.84** (>6.0), vol **0.066%** (<0.5%) → «near-constant
  (MOCK) data; metrics NOT trustworthy. P0 fix: backtest on real point-in-time historical APY series».
- Лидерборд показывает Sharpe 44/54/92 — бессмыслица (реальный Sharpe редко >3).

Т.е. турнир крутится ежедневно, но ранжирует по Sharpe на почти-константных/mock данных ⇒ рейтинги
НЕ отражают реальную доходность. Это тот же класс, что S23 mock-7%, но в масштабе всего лидерборда.

## Уточнение (разбор honesty-gate, 2026-07-23)

`trustworthy:false` — это НЕ поломка, а намеренный HONESTY GATE (`mass_tournament.py:650`,
`assess_tournament_trust`, fail-CLOSED): турнир сам ловит вырожденную Sharpe на near-const данных и
честно себя помечает. Ранжирование по net-of-cost APY УЖЕ сделано (OWNER DECISION 2026-06-27,
`rank_metric=net_annual_return_pct`, Sharpe понижен до вторичного). Значит п.1 ниже — уже готов.

## Что сделать (остаток P0)

1. ✅ (готово 2026-06-27) Ранжировать по net-of-cost APY, не по Sharpe.
2. **Кормить турнир реальными point-in-time историческими APY-сериями** (не mock/near-constant) — это
   и есть корень `trustworthy:false`; после него флаг честно станет true.
3. **Исключать/помечать mock-записи** (см. guard `agent-guard-no-silent-mock-in-tournament.md`).
4. Сохранить честный флаг `trustworthy` + **тест, что honesty-gate нельзя молча заглушить** (инвариант #16).

## Контекст структуры турнира (для истории)

Три ЖИВЫЕ подсистемы (не дубли):
- `mass_tournament` (06:00 UTC) — находит все стратегии, бэктестит → `mass_tournament_results.json`.
- `tournament_engine` (09:00 UTC) — paper-трек топ-N, PROMOTION_CRITERIA (Sharpe≥1.5/≥7d/APY≥3%/dd≥-15%),
  ре-ранк, Telegram → `strategy_tournament.json`. IS_ADVISORY.
- `promotion_engine` (в daily-cycle) — второй промоушен-чек (Sharpe>0.8/14d).

## Почему важно сейчас

Владелец (2026-07-23): оценивать МОИ и другие стратегии по РЕАЛЬНОЙ доходности (все 3 тира), не только
Conservative. Недоверяемый турнир этого не даёт. Это фундамент под слой Head of Investment (ADR-055).

## Как понять, что готово

Турнир ранжирует по net-of-cost APY на реальных исторических сериях; `trustworthy: true` честно
достижимо; mock-записи не в доверенном рейтинге; ДО/ПОСЛЕ по местам показано; ADR/journal.


---

## СВЕРКА 2026-08-17 — НЕ ЗАКРЫТА: п.2 (реальные PIT-ряды) не сделан

Проверено кодом производителя `spa_core/backtesting/mass_tournament.py`, не
коммит-сообщением.

| пункт карточки | вердикт | чем доказано |
|---|---|---|
| 1. ранжировать по net-of-cost APY | ✅ | мета `rank_metric = "net_annual_return_pct"`, Sharpe вторичный (`secondary_rank_metric`), стр. 736–740 |
| 2. **кормить реальными point-in-time рядами** | ❌ **НЕ сделан** | см. ниже |
| 3. исключать/помечать mock-записи | ✅ | `trusted_for_ranking` + `trusted_leaderboard` (стр. 665–671), `mock_tainted_*` в мете; закрыто карточкой `agent-guard-no-silent-mock-in-tournament` |
| 4. честный флаг + тест «gate нельзя заглушить» | ✅ | `assess_tournament_trust` fail-CLOSED (стр. 707–719) + `test_tournament_trust_honesty.py`, `test_honesty_gate_still_fires_on_degenerate_data` |

### Почему п.2 не сделан — дословно из кода

`MOCK_APY` жив и остаётся ЛИТЕРАЛЬНЫМ снимком в коде турнира
(`mass_tournament.py:136-157`, комментарий «Mock APY snapshot used when a
strategy's `get_allocation()` needs live rates»), и именно он подаётся стратегиям
во всех восьми пробуемых сигнатурах (стр. 443–458). Мета честно это признаёт:
`"mock_apy_snapshot_is_literal": True` (стр. 742).

Реальные PIT-ряды присутствуют лишь как ЯРЛЫК ИСТОЧНИКА бэктест-движка
(`defillama_pit_real` из `data/historical_apy/*.json`, стр. 690–692), а не как
вход аллокации стратегий. То есть корень `trustworthy:false` — «Sharpe на
почти-константных данных» — не устранён.

**Что сделала волна 16–17.08 и что она НЕ сделала.** Коммит `587e3c622`
(«Турнир ранжировал 63 стратегии, из которых 7 бежали на выдуманном APY и не были
помечены») закрыл п.3: мок НАЗВАН и вынесен из доверяемого лидерборда
(63 строки → 56 доверяемых). Это карточка-guard, а не эта. Числа, которыми турнир
кормит стратегии, остались литеральными.

### Что ещё не показано

* `trustworthy: true` честно достижимым не показано ни разу: git-committed
  артефакт `data/mass_tournament_results.json` — от **2026-06-22** и полей
  `trustworthy` / `rank_metric` / `mock_tainted_count` в нём вообще нет
  (`meta` пуст), то есть свежего доказательного прогона в репозитории нет.
* «ДО/ПОСЛЕ по местам» для замены источника данных не показано (показано
  ДО/ПОСЛЕ по пометке мока — это другой вопрос).

### Следующий шаг (по величине)

Подать стратегиям срез `data/historical_apy/` на дату бэктеста вместо `MOCK_APY`,
по одному семейству протоколов за итерацию, и на каждом шаге печатать, какие
места лидерборда сдвинулись. `MOCK_APY` не удалять, пока покрыты не все ключи
`KNOWN_PROTOCOLS`: непокрытый ключ обязан давать отказ, а не молчаливый ноль.
