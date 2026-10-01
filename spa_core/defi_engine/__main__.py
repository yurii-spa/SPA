"""CLI: ``python3 -m spa_core.defi_engine [--run] [--data-dir DIR]`` (ADR-532). LLM_FORBIDDEN."""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spa_core.defi_engine.engine import DEFAULT_DATA_DIR, build, publish


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DeFi engine Phase 1: derived status + Position Passports")
    ap.add_argument("--run", action="store_true", help="atomic write to <data-dir>/defi_engine/")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--json", action="store_true", help="print the full status document")
    a = ap.parse_args(argv)
    status = publish(Path(a.data_dir)) if a.run else build(Path(a.data_dir))[0]
    if a.json:
        print(json.dumps(status, indent=2, ensure_ascii=False, default=str))
        return 0
    print(f"defi_engine {status['schema']} @ {status['generated_at']} — passports {status['n_passports']}, "
          f"findings {len(status['findings'])}, tier disagreements "
          f"{status['tier_authority']['n_disagreements']}")
    for bid, b in status["books"].items():
        apy = b["apy"]
        print(f"  {bid:12s} measured={b['measured']} nav={b['nav_usd']} "
              f"spot_net={apy['book_spot_apy_net']['value']} track_net={apy['track_realized_apy_net']['value']} "
              f"illiquid={b['exit'].get('share_illiquid')} budget={b['loss_budget'].get('status')}")
    for f in status["findings"]:
        print("  finding:", json.dumps(f, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
