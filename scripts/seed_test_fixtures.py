"""
Generates test fixtures for SPA paper trading pipeline.
Writes to tests/fixtures/ ONLY — never touches data/*.json production files.

MP-445: seed test fixtures for 7-day paper trading evidence pipeline.
"""
import json
import os
import pathlib
import random
from datetime import date, timedelta

START_DATE = date(2026, 6, 12)
FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "tests" / "fixtures"

# Sanity guard: production data directory must never be touched
_PRODUCTION_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"


def _assert_not_production(path: pathlib.Path) -> None:
    """Raise if path resolves inside the production data directory."""
    try:
        path.resolve().relative_to(_PRODUCTION_DATA_DIR.resolve())
        raise RuntimeError(
            f"SAFETY VIOLATION: attempted write to production data path: {path}"
        )
    except ValueError:
        pass  # not relative → safe


def generate_7day_evidence() -> dict:
    """Simulate 7 days of paper trading: APY ~10-12%, drawdown < 2%."""
    rng = random.Random(42)  # deterministic seed for reproducibility
    days = []
    equity = 100_000.0
    for i in range(7):
        d = START_DATE + timedelta(days=i)
        apy = 10.0 + rng.uniform(-1.0, 2.0)  # 9-12%
        daily_return = (apy / 100) / 365
        equity *= (1 + daily_return)
        days.append(
            {
                "date": str(d),
                "apy_pct": round(apy, 4),
                "equity_usd": round(equity, 2),
                "cycle_ok": True,
            }
        )
    return {
        "paper_start": str(START_DATE),
        "days": days,
        "total_days": 7,
        "generated_at": str(date.today()),
    }


def generate_tournament_ranking() -> dict:
    """7-day tournament snapshot."""
    return {
        "generated_at": str(date.today()),
        "rankings": [
            {
                "rank": 1,
                "strategy_id": "s7",
                "name": "Pendle YT+PT Aggressive",
                "target_apy": 10.115,
                "status": "paper",
                "days": 7,
            },
            {
                "rank": 2,
                "strategy_id": "s11",
                "name": "Hybrid Yield Max",
                "target_apy": 15.6,
                "status": "research",
                "days": 7,
            },
            {
                "rank": 3,
                "strategy_id": "s5",
                "name": "Pendle PT Enhanced",
                "target_apy": 8.5,
                "status": "paper",
                "days": 7,
            },
        ],
    }


def generate_golive_status() -> dict:
    """Simulated go-live status fixture (all checks pass for test purposes)."""
    return {
        "ready": True,
        "checks_passed": 18,
        "total_checks": 18,
        "blockers": [],
        "generated_at": str(date.today()),
    }


def _atomic_write(path: pathlib.Path, data: dict) -> None:
    """Write JSON atomically via tmp + os.replace."""
    _assert_not_production(path)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, str(path))


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    fixtures = {
        "paper_evidence_7d.json": generate_7day_evidence(),
        "tournament_ranking_7d.json": generate_tournament_ranking(),
        "golive_status.json": generate_golive_status(),
    }

    for filename, data in fixtures.items():
        path = FIXTURES_DIR / filename
        _atomic_write(path, data)
        print(f"Created: {path}")

    print(f"\nAll fixtures written to: {FIXTURES_DIR.resolve()}")
    print("Production data/paper_evidence.json — NOT touched.")


if __name__ == "__main__":
    main()
