#!/usr/bin/env python3
"""ОДНА команда владельцу: кого из долгожителей перезапустить и чем именно.

Сторож `agent_code_freshness` отвечает на четвёртый вопрос доставки — исполняет
ли ЖИВОЙ процесс тот код, что лежит в дереве, — и по правилу
(`.claude/rules/deployment.md`, п. 6) НИЧЕГО не перезапускает. До сих пор это
означало, что владелец, увидев «apiserver работает с кодом от 17 июля», должен
был сам собрать имена, вспомнить домен `gui/<uid>` и не забыть приёмку до и
после. Сегодняшний пример того же класса: жалоба на Телеграм упирается в
`com.spa.telegram_bot` — долгожитель, маячок ADR-069 не подтверждён, кнопки не
приезжают, и кодом это не чинится вообще.

Этот скрипт закрывает ровно этот разрыв и ничего больше: он **ПЕЧАТАЕТ** список
несвежих долгожителей и готовые команды. Запуск — действие владельца.

**Скрипт ничего не запускает и не может.** Он не вызывает `launchctl kickstart`,
`bootout`, `bootstrap`, `kill` — вообще ни одной мутирующей команды; сторож под
ним делает только read-only замеры (`launchctl list`, `ps`). Это закреплено
тестом (`scripts/tests/test_print_stale_agent_restarts.py`), а не обещанием в
шапке: «печатает» и «печатает и тихонько делает» отличаются только проверкой.

Почему НЕ через `scripts/check_agent_before_deploy.sh`: тот гейт на долгожителе
опасен — его пробный прогон поднимает ВТОРОЙ процесс (для Telegram-бота это
второй поллер на том же токене, 409-конфликты, нажатия владельца теряются), и
сам гейт не завершается никогда (замер 2026-08-08, правило доставки). Поэтому
печатается прямой `kickstart -k`, обрамлённый приёмкой.

«Не измерено» печатается ОТДЕЛЬНО и никогда не сливается с «перезапускать
некого»: пустой список команд рядом с непрочитанным plist'ом читался бы как
чистый счёт.

Коды возврата: 0 — несвежих нет и всё измерено · 1 — есть кого перезапустить ·
2 — что-то НЕ ИЗМЕРЕНО (счёт неполон).

LLM запрещён. Только stdlib. Ничего не пишет на диск.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Callable, List, Optional

from spa_core.monitoring.agent_code_freshness import (
    STALE_ALERT_HOURS,
    STATE_STALE,
    STATE_UNCHECKED,
    check_agent_code_freshness,
)

__all__ = ["build_report", "main"]


def _kickstart_command(label: str, uid: int) -> str:
    return "launchctl kickstart -k gui/{}/{}".format(uid, label)


def build_report(
    doc: dict,
    *,
    uid: int,
    min_gap_hours: float = STALE_ALERT_HOURS,
) -> tuple[List[str], List[str], int]:
    """(строки отчёта, команды к запуску, код возврата). Ничего не выполняет.

    ``min_gap_hours`` отсекает шум обычного окна доставки — тот же порог, по
    которому сторож повышает голос. Разрыв меньше порога остаётся ВИДЕН в
    отчёте отдельной строкой, он просто не попадает в список команд: иначе
    владелец получал бы наряд на перезапуск после каждого дневного пуша и
    перестал бы его читать.
    """
    agents = doc.get("agents", []) or []
    stale = [a for a in agents
             if a.get("state") == STATE_STALE
             and (a.get("gap_hours") or 0.0) >= min_gap_hours]
    quiet = [a for a in agents
             if a.get("state") == STATE_STALE and a not in stale]
    unchecked = [a for a in agents if a.get("state") == STATE_UNCHECKED]

    lines: List[str] = []
    lines.append("Долгожители, исполняющие код старше дерева "
                 "(порог {:.0f} ч)".format(min_gap_hours))
    lines.append("=" * 66)
    lines.append("проверено долгожителей: {} · несвежих: {} · НЕ ИЗМЕРЕНО: {}".format(
        doc.get("long_lived_total"), doc.get("stale_count"), doc.get("unchecked_count")))
    lines.append("")

    if stale:
        for a in stale:
            lines.append("  ✗ {}  разрыв {:.1f} сут  (pid {})".format(
                a.get("label"), (a.get("gap_hours") or 0.0) / 24.0, a.get("pid")))
            lines.append("      {}".format(a.get("detail")))
            for n in a.get("notes", []) or []:
                lines.append("      ⚠ {}".format(n))
    else:
        lines.append("  ✓ несвежих долгожителей выше порога нет")

    if quiet:
        lines.append("")
        lines.append("  Ниже порога (видно, но перезапуск не нужен):")
        for a in quiet:
            lines.append("    · {} — разрыв {:.1f} ч".format(
                a.get("label"), a.get("gap_hours") or 0.0))

    if unchecked:
        lines.append("")
        lines.append("  ⚠ НЕ ИЗМЕРЕНО — счёт несвежих НЕПОЛОН, "
                     "пустой список команд ниже не означает «всё свежо»:")
        for a in unchecked:
            lines.append("    ? {} — {}".format(a.get("label"), a.get("detail")))

    commands = [_kickstart_command(a.get("label", "?"), uid) for a in stale]

    lines.append("")
    lines.append("-" * 66)
    if commands:
        lines.append("ЧТО ЗАПУСТИТЬ (скрипт этого НЕ делает — перезапуск ваш, п. 6):")
        lines.append("")
        lines.append("  # 1. приёмка ДО — без OK ничего не трогать")
        lines.append("  python3 -m spa_core.monitoring.deployment_acceptance")
        lines.append("")
        lines.append("  # 2. перезапуск")
        for c in commands:
            lines.append("  {}".format(c))
        lines.append("")
        lines.append("  # 3. коды выхода, а не «вроде запустилось»")
        lines.append("  launchctl list | grep spa")
        lines.append("")
        lines.append("  # 4. приёмка ПОСЛЕ")
        lines.append("  python3 -m spa_core.monitoring.deployment_acceptance")
        lines.append("")
        lines.append("  # 5. и убедиться, что разрыв закрылся")
        lines.append("  python3 scripts/print_stale_agent_restarts.py")
        lines.append("")
        lines.append("Про telegram_bot: гейт check_agent_before_deploy.sh на долгожителе")
        lines.append("НЕ применять — он поднимает второй поллер на том же токене.")
    else:
        lines.append("Перезапускать нечего.")

    if unchecked:
        code = 2
    elif commands:
        code = 1
    else:
        code = 0
    return lines, commands, code


def main(argv: Optional[List[str]] = None,
         *,
         checker: Optional[Callable[..., dict]] = None,
         uid: Optional[int] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Напечатать, каких долгожителей перезапустить. НИЧЕГО не запускает.")
    ap.add_argument("--agent-dir", default=None,
                    help="каталог plist'ов (по умолчанию ~/Library/LaunchAgents)")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--min-gap-hours", type=float, default=STALE_ALERT_HOURS)
    args = ap.parse_args(argv)

    check = checker or check_agent_code_freshness
    doc = check(
        agent_dir=Path(args.agent_dir) if args.agent_dir else None,
        repo_root=Path(args.repo_root) if args.repo_root else None,
    )
    lines, _cmds, code = build_report(
        doc, uid=uid if uid is not None else os.getuid(),
        min_gap_hours=args.min_gap_hours)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
