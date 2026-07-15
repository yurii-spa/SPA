# Rule · Risk engine (`spa_core/risk/`, `spa_core/governance/`, gates)

**Читать перед любым изменением risk-логики.** Изменение правил → новый ADR в `docs/decisions/`.

- **RiskPolicy v1.0 — единственный hard-гейт.** `approved=False` не переопределяется никем и ничем.
  Version-строка остаётся `"v1.0"` весь paper-период. Не менять `RiskConfig` пороги без ADR.
- **LLM запрещён** в risk / kill / gates — ни одного вызова, ни advisory, ни «на подсказку».
- **Fail-CLOSED:** при нехватке данных / расхождении фидов / недоборе кворума — отказ или HOLD,
  никогда не угадывать в пользу входа.
- **Two-tier kill-switch** (`governance/kill_switch.py`, ADR-034/048): SOFT_DERISK при drawdown
  ∈ [5%,10%) (halt new / no INCREASE, НЕ ликвидирует); HARD_KILL при ≥10% inclusive (all-cash).
  `check_drawdown_trigger` и `drawdown_tier` должны оставаться согласованными (`>=` на 10%).
- **Пороги RiskPolicy:** TVL floor ≥ $5M/пул · per-protocol cap 40% T1 / 20% T2 · T2 total ≤ 50% ·
  APY-границы 1%…30% · min cash buffer ≥ 5%.
- **Advisory-слой (Risk Scoring v2, дески, рой) НИКОГДА не гейтит исполнение** и не двигает капитал.
- Тесты обязательны до закрытия любой risk-задачи; прогонять полный `spa_core/tests/`.
- Изменения money-path проверять через `spa_core/paper_trading/pre_cutover_gate.py` (inert readiness gate).
