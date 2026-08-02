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
