"""cio_g4_repro — воспроизведение гэпа G4 из RS-portfolio-cio-diagnosis на текущем коде.

Замер cloud-сессии 2026-08-19 (мандат владельца). Детерминированно, offline,
read-only: пишет только во временный каталог. Запуск из корня репо:

    python3 docs/research/cio_g4_repro.py

Мир — замер 08.08 (карточка ADR-072): 7 адаптеров, morpho_steakhouse на
static-TVL. Ожидание по карточке: compound_v3 = 0, кэш ~25%, freed = 0.

ФАКТ на origin/main 2026-08-19 (серия ADR-072/072.1/073 уже в проде):
  шаг 1  аллокатор раскладывает 100%, compound_v3 = $27,500 (НЕ ноль);
  шаг 2  гейт морозит morpho fail-closed (ADR-053) → deployed $91,532;
  шаг 3  redistribute: freed = $3,468, разместить некуда — cap-bound
         (сеть ethereum 90%), причина названа в notes.

⇒ G4 в формулировке 08.08 НЕ воспроизводится — закрыт предыдущими починками.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# spa_core импортируется ВНУТРИ main(): файл живёт вне каталогов автосинка,
# и жёсткий верхнеуровневый импорт spa_core запрещён сторожем
# test_unsynced_hard_imports (протухание молча, авария 2026-08-17).

CAPITAL = 100_000.0

ADAPTERS = [
    {"protocol": "aave_v3", "apy_pct": 2.7, "tvl_usd": 12e9, "tier": "T1", "tvl_source": "live"},
    {"protocol": "compound_v3", "apy_pct": 3.3, "tvl_usd": 37.6e6, "tier": "T1", "tvl_source": "live"},
    {"protocol": "pendle", "apy_pct": 8.0, "tvl_usd": 5e8, "tier": "T2", "tvl_source": "live"},
    {"protocol": "maple", "apy_pct": 5.11, "tvl_usd": 2e9, "tier": "T2", "tvl_source": "live"},
    {"protocol": "morpho_steakhouse", "apy_pct": 3.47, "tvl_usd": 3e8, "tier": "T2", "tvl_source": "static"},
    {"protocol": "yearn_v3", "apy_pct": 3.3, "tvl_usd": 5e7, "tier": "T2", "tvl_source": "live"},
    {"protocol": "euler_v2", "apy_pct": 3.1, "tvl_usd": 4e7, "tier": "T2", "tvl_source": "live"},
]

GRADES = [
    {"slug": "aave_v3", "grade": "A"}, {"slug": "compound_v3", "grade": "A"},
    {"slug": "pendle", "grade": "C"}, {"slug": "maple", "grade": "B"},
    {"slug": "morpho_steakhouse", "grade": "B"}, {"slug": "yearn_v3", "grade": "B"},
    {"slug": "euler_v2", "grade": "B"},
]


def main() -> None:
    from spa_core.allocator.allocator import StrategyAllocator
    from spa_core.paper_trading.risk_gate import (
        _apply_risk_policy_gate,
        redistribute_freed_budget,
    )

    tmp = Path(tempfile.mkdtemp(prefix="cio_g4_repro_"))
    (tmp / "status.json").write_text(json.dumps({"adapters": ADAPTERS}))
    (tmp / "risk_scores.json").write_text(json.dumps({"scores": GRADES}))

    allocator = StrategyAllocator(
        status_path=tmp / "status.json",
        risk_scores_path=tmp / "risk_scores.json",
        registry_path=tmp / "__no_registry__.json",
        live_apy_provider=False,
    )
    res = allocator.allocate(model="risk_adjusted")
    print("── шаг 1: аллокатор ──")
    for proto, usd in sorted(res.target_usd.items(), key=lambda kv: -kv[1]):
        if usd > 0:
            print(f"  {proto:18} ${usd:>9,.0f}")
    print(f"  cash: {res.cash_pct * 100:.1f}%")
    assert res.target_usd.get("compound_v3", 0.0) > 0, "G4-репро: compound_v3 не должен быть нулём"

    gate = _apply_risk_policy_gate(dict(res.target_usd), CAPITAL, ADAPTERS,
                                   ddir=tmp, current_positions={})
    deployed = sum(gate["target_usd"].values())
    print("── шаг 2: гейт ──")
    print(f"  deployed ${deployed:,.0f} | tvl_unverified: {gate['tvl_unverified']}")

    redis = redistribute_freed_budget(gate["target_usd"], dict(res.target_usd),
                                      CAPITAL, ADAPTERS, gate)
    final_deployed = sum(redis["target_usd"].values())
    print("── шаг 3: redistribute (ADR-072) ──")
    print(f"  freed ${redis['freed_usd']:,.0f} | added: {redis['added']}")
    print(f"  итог deployed ${final_deployed:,.0f} | cash {100 - final_deployed / CAPITAL * 100:.1f}%")
    for note in redis["notes"]:
        print("  note:", note)
    print("\nВЕРДИКТ: G4 (compound=0 / кэш 25% / freed=0) НЕ воспроизводится на этом коде.")


if __name__ == "__main__":
    main()
