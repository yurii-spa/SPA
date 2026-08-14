"""
Generates test fixtures for SPA paper trading pipeline.
Writes to the directory it is given (default `tests/fixtures/`) — never to `data/`.

MP-445: seed test fixtures for 7-day paper trading evidence pipeline.

**Штамп `generated_at` — детерминированный, а НЕ «сегодня» (цикл #225).** Раньше все три
фикстуры получали `date.today()`, и это давало два разных дефекта сразу:

1. **Самообновляющаяся фикстура протухнуть не может.** Любая проверка свежести, построенная
   на этих файлах, зелена по построению: она измеряет не систему, а собственный прогон.
   Это тот же класс, что «сторож отвечает не на тот вопрос».
2. **Прогон тестов пачкал git-tracked файлы** — `git status` после любого прогона показывал
   три изменённые фикстуры, и сверка «что я собрал ↔ что уехало на origin» вынуждена была
   глазами отделять свои правки от следа тестов.

Теперь штамп равен последнему смоделированному дню (`SNAPSHOT_DATE`), поэтому повторный
запуск байт-в-байт идемпотентен, а фикстура стареет честно — как и положено снимку.
Нужен другой штамп — передать его явно (`--generated-at`), время здесь ВХОД, а не окружение
(`.claude/rules/deployment.md`, предпочтение #1).
"""
import argparse
import json
import os
import pathlib
import random
import sys
from datetime import date, timedelta

START_DATE = date(2026, 6, 12)
DAYS = 7
# Последний смоделированный день. Снимок описывает книгу ПО эту дату — значит и штамп
# у него этот, а не дата прогона (см. докстринг модуля).
SNAPSHOT_DATE = START_DATE + timedelta(days=DAYS - 1)
FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "tests" / "fixtures"

FIXTURE_NAMES = (
    "paper_evidence_7d.json",
    "tournament_ranking_7d.json",
    "golive_status.json",
)

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


def generate_7day_evidence(generated_at: date = SNAPSHOT_DATE) -> dict:
    """Simulate 7 days of paper trading: APY ~10-12%, drawdown < 2%."""
    rng = random.Random(42)  # deterministic seed for reproducibility
    days = []
    equity = 100_000.0
    for i in range(DAYS):
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
        "total_days": DAYS,
        "generated_at": str(generated_at),
    }


def generate_tournament_ranking(generated_at: date = SNAPSHOT_DATE) -> dict:
    """7-day tournament snapshot."""
    return {
        "generated_at": str(generated_at),
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


def generate_golive_status(generated_at: date = SNAPSHOT_DATE) -> dict:
    """Simulated go-live status fixture (all checks pass for test purposes)."""
    return {
        "ready": True,
        "checks_passed": 18,
        "total_checks": 18,
        "blockers": [],
        "generated_at": str(generated_at),
    }


def build_fixtures(generated_at: date = SNAPSHOT_DATE) -> dict:
    """All fixtures as {filename: payload} — same content for the same stamp."""
    return {
        "paper_evidence_7d.json": generate_7day_evidence(generated_at),
        "tournament_ranking_7d.json": generate_tournament_ranking(generated_at),
        "golive_status.json": generate_golive_status(generated_at),
    }


def _atomic_write(path: pathlib.Path, data: dict) -> None:
    """Write JSON atomically via tmp + os.replace."""
    _assert_not_production(path)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, str(path))


def write_fixtures(out_dir, generated_at: date = SNAPSHOT_DATE) -> list:
    """Write every fixture into `out_dir`; returns the written paths."""
    out_dir = pathlib.Path(out_dir)
    _assert_not_production(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for filename, data in build_fixtures(generated_at).items():
        path = out_dir / filename
        _atomic_write(path, data)
        written.append(path)
    return written


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out-dir", default=str(FIXTURES_DIR),
                   help="куда писать фикстуры (по умолчанию tests/fixtures/); "
                        "тесты передают сюда временный каталог")
    p.add_argument("--generated-at", default=str(SNAPSHOT_DATE),
                   help="штамп ISO YYYY-MM-DD; по умолчанию последний смоделированный день "
                        "(детерминированно — не дата прогона)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    try:
        stamp = date.fromisoformat(args.generated_at)
    except ValueError as exc:
        print(f"bad --generated-at {args.generated_at!r}: {exc}", file=sys.stderr)
        return 2

    written = write_fixtures(args.out_dir, stamp)
    for path in written:
        print(f"Created: {path}")

    print(f"\nAll fixtures written to: {pathlib.Path(args.out_dir).resolve()}")
    print("Production data/paper_evidence.json — NOT touched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
