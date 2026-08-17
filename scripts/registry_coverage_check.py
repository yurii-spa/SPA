#!/usr/bin/env python3
"""Проверка: нет ли в книге денег под протоколом, которого нет в реестре адаптеров.

Точка входа для сторожа ``spa_core.monitoring.registry_coverage_watch`` —
остаточная дыра ADR-062, названная им же самим: кэпы по цепочкам берут цепочку из
``data/adapter_registry.json``, а протокол, которого там нет, честно помечается
UNCHECKED — и незамеченным раздувает реальную экспозицию.

**Ничего не пишет.** Ни байта в ``data/``: домен read-only, карточка
``agent-funded-protocol-not-in-registry`` разрешает детекцию, но не запись и не
блокировку книги — блокировка осталась за RiskPolicy и не трогается.

Зовётся шагом дневного цикла (``scripts/run_daily_paper_cycle.sh``), а не своим
LaunchAgent'ом — по той же причине, что и ``fleet_parity_check.py`` рядом: флот не
должен расти на одного ради того, чтобы посмотреть на себя, а сторож внутри цикла
нельзя забыть при установке. Шаг НЕ фатальный: ненулевой код здесь — это НАХОДКА,
а не поломка цикла.

Коды возврата:

* ``0`` — реестр покрывает всё профинансированное (или книги нет — сторожить нечего);
* ``1`` — НАХОДКА: деньги под протоколом без записи о цепочке (CRITICAL);
* ``2`` — измерить не удалось (fail-CLOSED: «не измерено» ≠ «в порядке»).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spa_core.monitoring.registry_coverage_watch import (  # noqa: E402
    STATE_GAP,
    STATE_UNCHECKED,
    check_registry_coverage,
)

EXIT_OK = 0
EXIT_GAP = 1
EXIT_UNCHECKED = 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=str(Path(__file__).resolve().parents[1] / "data"),
                    help="каталог состояния (по умолчанию — data/ этого дерева)")
    ap.add_argument("--json", action="store_true", help="выдать вердикт машинно")
    args = ap.parse_args(argv)

    verdict = check_registry_coverage(args.data_dir)

    if args.json:
        print(json.dumps(verdict.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"[registry-coverage] {verdict.severity}: {verdict.detail}")
        if verdict.issue:
            print(f"[registry-coverage] {verdict.issue}")

    if verdict.state == STATE_GAP:
        return EXIT_GAP
    if verdict.state == STATE_UNCHECKED:
        return EXIT_UNCHECKED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
