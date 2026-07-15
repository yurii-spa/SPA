# ADR-048 · Two-tier kill-switch (SOFT −5% / HARD −10% inclusive)

- **Статус:** Accepted (owner-approved 2026-06-27; backfilled в реестр 2026-07-15). Уточняет ADR-034.
- **Дата:** 2026-06-27
- **Автор/утвердил:** владелец

## Контекст

Ранее HARD-kill стоял на −15% и оставлял зазор с DL-02 (10%-peak) — двусмысленность на границе.
Нужна одна согласованная лестница ответа на drawdown, без «теневых» порогов.

## Решение

Одна лестница над evidenced peak-to-current drawdown (`spa_core/governance/kill_switch.py`):

| Tier | Порог | Эффект |
|---|---|---|
| **SOFT_DERISK** | drawdown ∈ [5%, 10%) | halt new / no INCREASE (hold+reduce OK); НЕ ликвидирует. Гейт `cycle_gates.apply_soft_derisk_gate` |
| **HARD_KILL** | drawdown ≥ 10% (inclusive) | full kill → all-cash `{"cash":1.0,…:0.0}` |

- HARD снижен 15→10, граница `>=` (`check_drawdown_trigger` согласован с `drawdown_tier` — ровно
  10.0% срабатывает).
- DL-02 (10%-peak) больше не шедоуит kill — **DEFERS** к нему (`run_cycle` идёт all-cash, не HOLD).
  DL-01 (2% single-day HALT) intact, никогда не deferred.
- RiskPolicy version остаётся `v1.0` — two-tier живёт в governance-слое, `RiskConfig` не тронут.

## Последствия

- ✅ Единая, согласованная drawdown-реакция; закрыт boundary-gap на 10%.
- Инвариант «RiskPolicy v1.0 неизменен весь paper-период» соблюдён (изменение в governance, не в policy).
- Money-path защиты доказуемо срабатывают — верифицируется `pre_cutover_gate.py`.
