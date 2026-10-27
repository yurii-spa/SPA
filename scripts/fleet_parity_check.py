#!/usr/bin/env python3
"""Q3-2 — Fleet-parity self-check (deterministic, advisory).

A drift guard for the LaunchAgent fleet, in the same spirit as the doc-drift guard: it asserts the
three declarations of "the fleet" agree with each other, so a plist that no installer installs (a
loaded-not-installed orphan) or an installer line pointing at a missing plist can never silently rot.

Three sources of truth:
  • DECLARED  — labels the installer (`scripts/install_all_agents.sh`) actually installs.
  • PLIST     — `com.spa.*.plist` files present on disk (scripts/ + launchd/).
  • RETIRED   — `agent_health_monitor.RETIRED_LABELS` (deliberately not-installed; must not revive).

Parity classes (any non-empty problem class → status DRIFT):
  • broken_declared_no_plist   — installer installs a label whose plist file is missing → install fails.
  • orphan_plist_not_declared  — a plist exists that is NEITHER installed NOR retired → dead/confusing.
  • retired_but_installed      — a RETIRED label the installer still installs → revival hazard (409/flood).

The LIVE running fleet (`launchctl list | grep com.spa`) is compared too WHEN available (prod host);
in a sandbox/CI checkout launchctl is absent, so that comparison is reported as `unavailable`, never
failed. Deterministic, stdlib-only, LLM-forbidden, fail-CLOSED. Advisory — writes a status file, never
loads/unloads anything.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.utils.atomic import atomic_save  # noqa: E402

_INSTALLER = ROOT / "scripts" / "install_all_agents.sh"
_PLIST_DIRS = (ROOT / "scripts", ROOT / "launchd")
_OUT = ROOT / "data" / "fleet_parity.json"
# Манифест — источник правды о судьбе агента (`intent`); см. retired_labels().
_MANIFEST = ROOT / "architecture" / "manifest.json"
# Реестр карантина — тот же файл, что читает установщик перед каждой install_agent.
_QUARANTINE = ROOT / "attic" / "agents" / "QUARANTINE.json"

# a quoted "com.spa.<label>" token that is NOT a path and NOT a .plist filename = an install label
_LABEL_RE = re.compile(r'"(com\.spa\.[a-z0-9_-]+)"')


def declared_labels() -> set:
    """Labels the installer installs — the quoted install_agent label arg (not the plist path)."""
    try:
        text = _INSTALLER.read_text()
    except OSError as e:
        raise RuntimeError(f"fleet_parity: installer unreadable ({e})") from e
    out = set()
    for line in text.splitlines():
        # strip shell comments FIRST — a commented-out install_agent block is NOT a declared install
        # (matching it produced a false httpserver positive). The label arg is a bare quoted token; the
        # plist PATH arg is quoted too but the regex already only accepts label-shaped tokens (no '/').
        code = line.split("#", 1)[0]
        for m in _LABEL_RE.finditer(code):
            out.add(m.group(1))
    return out


def quarantined_labels():
    """Метки, которые установщик ПРОПУСКАЕТ (attic/agents/QUARANTINE.json), либо None.

    Строка install_agent в установщике — ещё не установка: установщик сверяет каждую
    метку с этим реестром и отложенную не ставит (test_installer_respects_quarantine).
    Без этой сверки каждый отложенный агент читался как «retired, но устанавливается»
    (замер 27.10: 5 из 5 находок класса — отложенные решением владельца 29–30.08).

    Разбор — тот же, что у установщика. Файла нет ⇒ пустое множество (установщик тоже
    никого не пропускает). Файл не читается ⇒ None — «не измерено» (инв. #17):
    установщик в этом случае ОТКАЗЫВАЕТ, и выдавать его карантин за пустой нельзя.
    """
    if not _QUARANTINE.exists():
        return set()
    try:
        import json
        data = json.loads(_QUARANTINE.read_text(encoding="utf-8"))
        rows = data.get("quarantined", data) if isinstance(data, dict) else data
        names = list(rows) if isinstance(rows, dict) else [
            r.get("label") or r.get("agent") or r.get("name") for r in rows]
    except Exception:  # noqa: BLE001 — нечитаемый реестр есть третий исход, а не пустота
        return None
    return {n if str(n).startswith("com.spa.") else "com.spa." + str(n) for n in names if n}


def plist_labels() -> set:
    out = set()
    for d in _PLIST_DIRS:
        if d.is_dir():
            for p in d.glob("com.spa.*.plist"):
                out.add(p.name[:-len(".plist")])
    return out


def manifest_intents() -> dict:
    """{label: intent} из манифеста — ЕДИНЫЙ источник правды о судьбе агента.

    Читается мягко: манифест недоступен ⇒ пустая карта, поведение прежнее.
    Сторож не вправе упасть из-за файла, который лишь уточняет его знание.
    """
    try:
        import json
        return {a["label"]: a.get("intent")
                for a in json.loads(_MANIFEST.read_text(encoding="utf-8"))["agents"]
                if isinstance(a, dict) and a.get("label")}
    except Exception:  # noqa: BLE001 — уточнение не важнее самой проверки
        return {}


def retired_labels() -> set:
    """Похороненные = константа ∪ манифест (`intent: retired`).

    ADR-144: два источника лимитов в одной системе — гарантированный разъезд.
    Здесь ровно он и случился: замер 31.08 показал ШЕСТЬ «сирот» из девяти,
    помеченных `retired` в манифесте, и НИ ОДНОГО из них в константе на 10 имён.
    Две трети находок — шум; список, где большинство находок ложные, читать
    перестают, и в нём утонет настоящая. Оставленный у агента plist — это
    документированная часть карантина («НЕ удалён: plist лежит в репозитории,
    команда возврата в attic/agents/QUARANTINE.json»), а не непорядок.

    ОБЪЕДИНЕНИЕ, а не замена: знание может только прибавиться. Константа
    остаётся источником для имён, которых в манифесте нет вовсе.
    """
    try:
        from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS
        out = set(RETIRED_LABELS)
    except Exception:  # noqa: BLE001
        out = set()
    return out | {l for l, i in manifest_intents().items() if i == "retired"}


def _live_labels():
    """Running com.spa.* labels via launchctl, or None when launchctl is unavailable (sandbox/CI)."""
    if not shutil.which("launchctl"):
        return None
    try:
        res = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    labels = set()
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if parts and parts[-1].startswith("com.spa."):
            labels.add(parts[-1].strip())
    return labels


def build_report(write: bool = True) -> dict:
    written = declared_labels()
    quarantined = quarantined_labels()
    # Объявлен = строка в установщике И установщик её не пропустит. Реестр не читается ⇒
    # ничего не вычитаем (установщик в этом случае отказывает целиком), и это видно ниже.
    declared = written - (quarantined or set())
    plist = plist_labels()
    retired = retired_labels()

    broken = sorted(declared - plist)                      # installed but no plist file
    # Спроектированный, но не развёрнутый агент: plist в репозитории есть,
    # установки нет — это его ШТАТНОЕ состояние, а не сирота. Выносится
    # отдельной строкой, а НЕ прячется: «сверено и нормально» обязано остаться
    # отличимым от «не сверяли».
    designed = {l for l, i in manifest_intents().items() if i == "designed"}
    orphan = sorted(plist - declared - retired - designed - (quarantined or set()))  # not installed, not retired, not quarantined
    designed_not_deployed = sorted((plist - declared) & designed)
    retired_installed = sorted(declared & retired)         # retired yet still installed → hazard

    live = _live_labels()
    live_block = {"available": live is not None}
    if live is not None:
        # a declared+has-plist label that is NOT running (excluding retired) — a possibly-down agent
        expected_running = (declared & plist) - retired
        live_block["running_count"] = len(live)
        live_block["declared_not_running"] = sorted(expected_running - live)
        live_block["running_not_declared"] = sorted(live - declared - retired)

    problems = bool(broken or orphan or retired_installed or quarantined is None)
    report = {
        "model": "fleet_parity_check",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_advisory": True,
        "deterministic": True,
        "llm_forbidden": True,
        "status": "DRIFT" if problems else "OK",
        "n_declared": len(declared),
        "n_plist": len(plist),
        "n_retired": len(retired),
        "broken_declared_no_plist": broken,
        "orphan_plist_not_declared": orphan,
        # Штатное состояние, а не находка: спроектирован, plist в репозитории
        # есть, установки нет. Видим отдельной строкой, чтобы «сверено и
        # нормально» осталось отличимо от «не сверяли».
        "designed_not_deployed": designed_not_deployed,
        "retired_but_installed": retired_installed,
        # Строка в установщике есть, но установщик её пропускает (карантин). Штатное
        # состояние отложенного агента; None — реестр не прочитан (не измерено).
        "quarantined_skipped_by_installer": (sorted(written & quarantined)
                                             if quarantined is not None else None),
        "quarantine_registry": "absent" if not _QUARANTINE.exists() else (
            "unreadable" if quarantined is None else "read"),
        "live": live_block,
        "note": (
            "Deterministic fleet-drift guard: the installer's declared fleet, the on-disk plists, and "
            "RETIRED_LABELS must agree. broken = installer references a missing plist; orphan = a plist "
            "nobody installs and isn't retired (loaded-not-installed hazard); retired_but_installed = a "
            "retired label the installer still installs (revival/flood hazard). launchctl comparison runs "
            "only on the prod host; absent in sandbox/CI (reported unavailable, never failed). Advisory."
        ),
    }
    if write:
        atomic_save(report, str(_OUT))
    return report


def main() -> int:
    rep = build_report(write=True)
    print(f"fleet parity: {rep['status']}  "
          f"(declared {rep['n_declared']} / plist {rep['n_plist']} / retired {rep['n_retired']})")
    for k in ("broken_declared_no_plist", "orphan_plist_not_declared", "retired_but_installed"):
        if rep[k]:
            print(f"  {k}: {rep[k]}")
    if rep["quarantine_registry"] == "unreadable":
        print("  quarantine registry: UNREADABLE — карантин не измерен, установщик откажет")
    lv = rep["live"]
    if lv.get("available"):
        if lv.get("declared_not_running"):
            print(f"  declared_not_running (host): {lv['declared_not_running']}")
    else:
        print("  live launchctl comparison: unavailable (not on prod host)")
    print(f"  → wrote {_OUT}")
    return 1 if rep["status"] == "DRIFT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
