# ADR-053 · RTMR — real-time monitoring sense-loop

- **Статус:** Accepted (backfilled в реестр 2026-07-15).
- **Дата:** 2026-07-02
- **Автор/утвердил:** владелец + monitoring sprint (S10)

## Контекст

Aggressive-тир и swarm-тезис (ADR-YL-012) держатся на утверждении «мы режем хвост скоростью
реакции»: carry держится, пока он зелёный, и де-рискуется за часы до того, как станет красным.
Это требует непрерывного, детерминированного зрения на риск — сенсоры пега / funding / TVL /
ликвидности выхода, — а не раз-в-цикл-снимка. При этом **LLM запрещён** в monitoring (инвариант #3),
а реакция обязана быть fail-closed: слепой/мёртвый сенсор должен всплывать как CRITICAL, никогда как
тишина (инвариант #2, refusal-first).

## Решение

RTMR (Real-Time Monitoring & Reaction) — двухслойный sense→react контур, детерминированный,
stdlib-only, LLM-forbidden:

1. **Sense-loop** (`spa_core/monitoring/sense_loop.py`): персистентный поллер (интервал из
   `monitoring_config.json`). Каждый тик прогоняет все зарегистрированные сенсоры → нормализует в
   `RiskSignal`, пишет `data/monitoring/signals/latest.json` + аппендит `signal_log.json`, ставит
   heartbeat. **Ничего не двигает и не решает** — только senses. Fail-closed: сенсор упал/пуст →
   синтезируется `stale_signal` (critical) для этого источника.
2. **Service + reaction ladder** (`rtmr_service.py`, launchd `com.spa.rtmr_sense`): после sense
   прогоняет детерминированную reaction-лестницу и применяет её **в PAPER-режиме** (posture +
   `reaction_log` + Telegram-алерт ON CHANGE only). **Никогда не двигает капитал** (§13.3). Posture
   исполняется rebalance-петлёй только после owner-gated wiring (S10.5b); до тех пор de-risk пишет
   dormant posture + early-warning alert.

Сенсоры регистрируются через `register_sensor` (peg / TVL / liquidity / funding, `sensors/build.py`).

## Последствия

- ✅ Даёт swarm/aggressive-тезису реальный sense→react контур с доказуемой скоростью реакции.
- ✅ Fail-closed по построению: мёртвый сенсор = CRITICAL, dead-man heartbeat детектит мёртвую петлю.
- Инвариант #3 соблюдён: LLM отсутствует в RTMR (детерминированные сенсоры + лестница).
- Инвариант #2 соблюдён: refusal-first — отсутствие данных → critical, не угадывание.
- ⚠️ **Owner-gate:** фактическое движение posture в rebalance (S10.5b) остаётся за владельцем;
  пока RTMR — advisory/early-warning, капитал не двигает.
- Затронутые файлы: `spa_core/monitoring/{sense_loop.py,rtmr_service.py,actions.py,sensors/*}`,
  тесты `spa_core/tests/test_rtmr_*.py`, `test_defenses_exercised_rtmr.py`. Связанные:
  ADR-YL-012 (swarm — RTMR даёт ему зрение), edge #13 (crisis-onset detection → RTMR-сенсоры).
