"""Protection Lab CLI.

# LLM_FORBIDDEN

Примеры:
    python3 -m spa_core.stress.protection_lab --list
    python3 -m spa_core.stress.protection_lab --scenario H05_terra_ust_luna_2022
    python3 -m spa_core.stress.protection_lab --all
    python3 -m spa_core.stress.protection_lab --adversarial
    python3 -m spa_core.stress.protection_lab --all --out data/protection_lab/report.json

Запись отчёта — только через atomic_save и только в data/protection_lab/.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from .replay import DEFAULT_BOOK, run_replay
from .report import format_report, format_summary_table
from .schema import load_all_scenarios
from .synthetic import ADVERSARIAL_SPECS, build_synthetic_scenario


def _report_to_dict(r) -> dict:
    return dataclasses.asdict(r)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="protection_lab")
    parser.add_argument("--list", action="store_true", help="список сценариев")
    parser.add_argument("--scenario", help="прогнать один сценарий по id")
    parser.add_argument("--all", action="store_true",
                        help="прогнать все исторические сценарии с replay-спекой")
    parser.add_argument("--adversarial", action="store_true",
                        help="прогнать adversarial-набор синтетики")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--out", help="путь JSON-отчёта (data/protection_lab/...)")
    args = parser.parse_args(argv)

    scenarios = load_all_scenarios()

    if args.list:
        for sid, sc in scenarios.items():
            mark = "replay" if sc.has_replay else "dataset-only"
            print(f"{sid:<40} {mark:<13} {sc.name}")
        for spec in ADVERSARIAL_SPECS:
            print(f"{spec.name:<40} {'synthetic':<13} {spec.description[:60]}")
        return 0

    to_run = []
    if args.scenario:
        if args.scenario in scenarios:
            to_run.append(scenarios[args.scenario])
        else:
            match = [s for s in ADVERSARIAL_SPECS if s.name == args.scenario]
            if not match:
                print(f"нет сценария {args.scenario!r}; --list покажет доступные",
                      file=sys.stderr)
                return 2
            to_run.append(build_synthetic_scenario(match[0]))
    if args.all:
        to_run.extend(sc for sc in scenarios.values() if sc.has_replay)
    if args.adversarial:
        to_run.extend(build_synthetic_scenario(s) for s in ADVERSARIAL_SPECS)
    if not to_run:
        parser.print_help()
        return 2

    reports = []
    for sc in to_run:
        rep = run_replay(sc, book=DEFAULT_BOOK, capital_usd=args.capital)
        reports.append(rep)
        print(format_report(rep))

    if len(reports) > 1:
        print(format_summary_table(reports))

    if args.out:
        out = Path(args.out)
        if "data/protection_lab" not in str(out):
            print("отчёты пишутся только в data/protection_lab/", file=sys.stderr)
            return 2
        from spa_core.utils.atomic import atomic_save
        atomic_save({"reports": [_report_to_dict(r) for r in reports]}, str(out),
                    indent=1)
        print(f"отчёт записан: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
