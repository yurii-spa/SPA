"""python -m spa_core.trading_research {tick|backtest|verify|status} — research/paper only."""
from __future__ import annotations

import argparse
import json
import sys

from . import evidence as ev

#: Agent contract (ADR-154/158): what com.spa.trading_research produces.
PRODUCES = (
    "data/trading_research/status.json",
    "data/trading_research/evidence.db",
    "data/trading_research/market.db",
    "data/trading_research/backtest.json",
)
from . import forward


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="spa_core.trading_research")
    ap.add_argument("cmd", choices=("tick", "backtest", "verify", "status"))
    a = ap.parse_args(argv)
    if a.cmd == "tick":
        r = forward.tick()
    elif a.cmd == "backtest":
        r = forward.tick(do_backtest=True)
    elif a.cmd == "verify":
        r = ev.verify(ev.connect(forward.data_dir() / "evidence.db"))
    else:
        try:
            r = json.loads((forward.data_dir() / "status.json").read_text())
        except (OSError, ValueError) as e:
            r = {"ok": False, "error": f"status not readable: {e}"}
    print(json.dumps(r, ensure_ascii=False, sort_keys=True)[:4000])
    if r.get("skipped"):
        return 0                       # another tick is running; nothing was measured by THIS run
    return 0 if r.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
