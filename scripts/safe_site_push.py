#!/usr/bin/env python3
# LLM_FORBIDDEN
"""safe_site_push — the ONLY sanctioned path for the autonomous orchestrator to push
site (landing/) changes to live earn-defi.com.

Owner-approved 2026-07-15 (ADR-OWN-2026-07-autoship): full autonomous auto-ship of SAFE
site changes; OWNER-GATED classes (yield numbers / tier naming / SPA expansion / legal /
solicitation / honesty-token removal) route to a needs-owner card and never auto-ship.

Flow:
  1. Run the owner-gate guard (scripts/check_owner_gate.py --diff-mode files) on the
     landing/ targets.
  2. CLEAN (exit 0) → set SPA_SITE_PUSH_VERIFIED=1 and delegate to push_to_github_batch.py
     (one commit). The raw push tools honour that marker and allow the push.
  3. GATED (exit 2) → do NOT push. Open a `needs-owner` card summarising the blocked
     change + violations, notify the owner, exit 2. The orchestrator continues other work.
  4. Guard ERROR (exit 1) → fail CLOSED: do NOT push, exit 1.

Why a wrapper AND a hard interlock in the push tools: an LLM can forget to call this
wrapper. The deterministic interlock in push_to_github*.py (active only when
SPA_AUTONOMOUS=1) refuses any autonomous landing/ push that did not go through here.

Pure stdlib. Attended sessions may also use this wrapper; it just adds the guard +
card-routing around a normal push.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_GUARD = _REPO_ROOT / "scripts" / "check_owner_gate.py"
_BATCH = _REPO_ROOT / "push_to_github_batch.py"


def _run_guard(site_files: list[str], message: str) -> tuple[int, dict]:
    """Run the guard on the given files; return (exit_code, report_dict)."""
    cmd = [
        sys.executable, str(_GUARD),
        "--diff-mode", "files", "--files", *site_files,
        "--commit-message", message or "", "--report",
    ]
    rc = subprocess.run(cmd, cwd=str(_REPO_ROOT)).returncode
    report: dict = {}
    try:
        report = json.loads(
            (_REPO_ROOT / "data" / "owner_gate_check.json").read_text(encoding="utf-8")
        )
    except Exception:
        pass
    return rc, report


def _route_to_owner_card(site_files: list[str], report: dict, message: str) -> None:
    """Create a needs-owner card for the blocked change and notify (best-effort)."""
    violations = report.get("violations", [])
    lines = [
        "## Что случилось и почему это важно",
        "Автономный оркестратор хотел изменить публичный сайт, но правка задевает "
        "owner-gated область (числа доходности / нейминг тиров / legal / solicitation). "
        "Такое не уезжает в live само — только с твоего одобрения (инвариант #8).",
        "",
        "## Что от тебя нужно",
        "Посмотри изменение и реши: одобрить или отклонить.",
        f"- Файлы: {', '.join(site_files)}",
        f"- Коммит-сообщение оркестратора: {message}",
        "- Что зафлагано owner-gate линтером:",
    ]
    for v in violations[:20]:
        lines.append(f"  - [{v.get('klass')}] {v.get('file')} · {v.get('rule')} · "
                     f"{v.get('matched_text', '')[:120]}")
    lines += [
        "",
        "## Как понять, что готово",
        "Ты написал в карточке «одобряю» (или «отклоняю»); при одобрении оркестратор "
        "запушит с трейлером `Owner-Approved: <id-карточки>`.",
        "",
        "## Что будет после",
        "Одобришь → изменение уезжает в live /dashboard и на сайт. Отклонишь → оркестратор "
        "не трогает эту область.",
    ]
    body = "\n".join(lines)
    try:
        from spa_core.owner_queue.queue import create_card  # type: ignore

        # create_card returns the full Path to the new card (queue.py). Pass the FULL
        # path to notify — a bare basename would not resolve against TRACKER_DIR and
        # load_card would FileNotFoundError, silently dropping the owner notification.
        card_path = create_card(
            tracker_type="owner-decision",
            title="Сайт: автономная правка задела owner-gated область — нужно решение",
            body=body,
            source="orchestrator",
        )
        print(f"safe_site_push: routed to owner card {card_path}", file=sys.stderr)
        try:
            subprocess.run(
                [sys.executable, str(_REPO_ROOT / "scripts" / "orchestrator_queue.py"),
                 "notify", str(card_path)],
                cwd=str(_REPO_ROOT), timeout=30,
            )
        except Exception:
            pass
    except Exception as exc:
        print(f"safe_site_push: FAILED to create owner card ({exc}); NOT pushing.",
              file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Guarded site push (owner-gate + card routing).")
    ap.add_argument("--files", nargs="+", required=True)
    ap.add_argument("--message", "-m", required=True)
    ap.add_argument("--repo")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args(argv)

    files = [str(Path(f)) for f in args.files]
    site_files = [f for f in files if "landing/" in f.replace("\\", "/")]

    if site_files:
        rc, report = _run_guard(site_files, args.message)
        if rc == 2:
            print("safe_site_push: GATED — owner-gated change, NOT pushing.", file=sys.stderr)
            _route_to_owner_card(site_files, report, args.message)
            return 2
        if rc != 0:
            print(f"safe_site_push: guard error (rc={rc}) — failing CLOSED, NOT pushing.",
                  file=sys.stderr)
            return 1

    # Clean (or no site files) → delegate to the batch push with the verified marker set.
    env = {**os.environ, "SPA_SITE_PUSH_VERIFIED": "1"}
    cmd = [sys.executable, str(_BATCH), "--files", *files, "--message", args.message]
    if args.repo:
        cmd += ["--repo", args.repo]
    cmd += ["--branch", args.branch]
    return subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
