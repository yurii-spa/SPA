#!/usr/bin/env python3
"""Y3 (ADR-055/ADR-060): сверка «что сказала тень vs что было по факту».

CLI-обёртка над ``spa_core.paper_trading.shadow_trigger_eval``: читает
append-only историю вердиктов (``data/allocation_rationale_history.jsonl``),
считает контрфакт по живым evidenced-APY следующих дней, пишет
``data/shadow_trigger_evaluation.json`` (атомарно) и печатает сводку.

СТРОГО ADVISORY: капитал не двигает; включение yield-триггера — отдельное
owner-решение через pre_cutover_gate + ADR.

Запуск:
    python3 scripts/evaluate_shadow_trigger.py [--data-dir data] \
        [--window-days N] [--horizon-days N] [--no-write] [--json]
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spa_core.paper_trading.shadow_trigger_eval import (  # noqa: E402
    DEFAULT_HORIZON_DAYS,
    evaluate_window,
    format_summary,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=str(REPO_ROOT / "data"),
                    help="каталог data/ (default: data/ корня репо)")
    ap.add_argument("--window-days", type=int, default=None,
                    help="оценивать только последние N дней вердиктов")
    ap.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON_DAYS,
                    help="горизонт контрфакта, дней вперёд на вердикт")
    ap.add_argument("--no-write", action="store_true",
                    help="не писать shadow_trigger_evaluation.json")
    ap.add_argument("--json", action="store_true",
                    help="печатать полный JSON вместо сводки")
    args = ap.parse_args(argv)

    doc = evaluate_window(
        Path(args.data_dir),
        window_days=args.window_days,
        horizon_days=args.horizon_days,
        write=not args.no_write,
    )
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_summary(doc))
    # Наблюдатель: и READY, и NOT_READY — валидные ответы, оба exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
