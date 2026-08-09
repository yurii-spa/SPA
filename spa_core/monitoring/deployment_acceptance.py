"""Deployment acceptance: after a change to the tree, CAN the system still run?

The question nobody was asking. On 2026-08-04 a file-level deployment applied
origin's file modes and stripped the executable bit from 67 of the 69 launchd
entrypoints. Every existing guard stayed quiet for five hours:

* ``deployment_drift`` said the code matched the delivered version — it did;
  a mode is not content, and a version says nothing about executability;
* ``agent_health`` watches heartbeats, so it can only notice hours later, once
  enough state files have gone stale;
* ``check_agent_before_deploy.sh`` gates ONE agent at the moment it is deployed
  — it is not run when the tree changes underneath 69 already-deployed agents;
* the daily cycle simply did not run, and nothing said so until a human asked.

Those guards answer "is the delivered version here?", "did agents report lately?"
and "is this one agent safe to deploy?". None answers **"can this fleet start?"**
That is this module's only job, and it asks it in the three ways that failed:

1. every launchd entrypoint exists and is EXECUTABLE;
2. the packages the agents import actually import;
3. the artifacts scheduled work is supposed to produce are not overdue.

Read-only. Fixes nothing, deploys nothing — it refuses to certify. Fail-CLOSED:
whatever cannot be established is CRITICAL, never a quiet pass.

LLM forbidden. Pure stdlib. Atomic writes.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
import os
import plistlib
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.monitoring.deployment_acceptance")

_REPO_ROOT = Path(__file__).resolve().parents[2]


def measuring_from_worktree(root: Optional[Path] = None) -> bool:
    """Правда ли, что нас спросили из git-worktree, а не из рабочего дерева прода.

    У worktree `.git` — ФАЙЛ со ссылкой на общий каталог, у обычного дерева это
    каталог. Признак структурный: не зависит от путей и работает для любого
    worktree, как бы он ни назывался.

    Зачем. Свежесть артефактов измеряется по mtime файлов в `data/`. В worktree
    там лежит git-копия, а не живое состояние прода: файлы «протухшие» просто
    потому, что их выложил checkout. Сессии обязаны гонять приёмку до и после
    изменений, работают при этом в worktree — и получают уверенный вердикт
    «задание не отработало» про агента, который на деле отработал минуты назад.
    """
    r = Path(root) if root else _REPO_ROOT
    return (r / ".git").is_file()
STATE_FILENAME = "deployment_acceptance.json"
DEFAULT_AGENT_DIR = Path.home() / "Library" / "LaunchAgents"
AGENT_GLOB = "com.spa.*.plist"

OK, WARNING, CRITICAL = "OK", "WARNING", "CRITICAL"

# Modules an agent imports on startup. If any of these fails to import, the
# corresponding agents die instantly — the failure mode of a partial file copy,
# where a new module references a dependency the tree does not have yet.
CRITICAL_IMPORTS = (
    "spa_core.adapters",
    "spa_core.allocator.allocator",
    "spa_core.risk.policy",
    "spa_core.risk.policy_enforcer",
    "spa_core.paper_trading.cycle_runner",
    "spa_core.monitoring.system_health_monitor",
)

# Artifacts that scheduled work MUST refresh, with the age past which their
# absence means the job did not run. Deliberately tighter than the existing
# 26 h gap monitor: a cycle that silently skips must surface the same morning,
# not the next day.
SCHEDULED_ARTIFACTS: Dict[str, float] = {
    "current_positions.json": 30.0,      # daily cycle (06:00 UTC) + slack
    # 30ч, а не 12: файл пересобирает ДНЕВНОЙ цикл (06:00 UTC), то есть раз в
    # сутки. SLO в 12ч у суточного артефакта означает, что тревога срабатывает
    # КАЖДЫЙ день во второй половине суток — гарантированно и без повода.
    # Измерено 2026-08-07: приёмка сообщила «adapter_status.json протух, работа
    # не запускалась», хотя цикл отработал штатно; через час файл был возрастом
    # 0.8ч. Сторож, который кричит по расписанию, перестаёт читаться, и на его
    # фоне теряется настоящая просрочка.
    # 30ч = сутки + 6ч запаса, ровно как у current_positions.json от ТОГО ЖЕ
    # производителя (согласованность важнее: два артефакта одного цикла не могут
    # иметь разный SLO без причины).
    "adapter_status.json": 30.0,         # daily cycle (06:00 UTC) + slack
    "agent_health.json": 6.0,            # fleet heartbeat
}


@dataclass
class AcceptanceReport:
    status: str = CRITICAL
    checked_at: str = ""
    entrypoints_total: int = 0
    entrypoints_broken: List[dict] = field(default_factory=list)
    imports_failed: List[dict] = field(default_factory=list)
    artifacts_overdue: List[dict] = field(default_factory=list)
    artifacts_unchecked: Optional[str] = None
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _schedule_interval_sec(doc: dict) -> Optional[float]:
    """How often this job fires, in seconds. ``None`` = could not be determined.

    Needed by ``deployment_drift``: an entrypoint that fires MORE OFTEN than the
    daily code sync cannot get its delivered version before it next runs. Callers
    must treat ``None`` as fail-CLOSED — "we do not know" is not "rarely".
    """
    if doc.get("KeepAlive"):
        return 0.0  # continuously restarted; drift takes effect immediately
    interval = doc.get("StartInterval")
    if isinstance(interval, int) and interval > 0:
        return float(interval)

    spec = doc.get("StartCalendarInterval")
    if spec is None:
        return None
    entries = spec if isinstance(spec, list) else [spec]
    if not entries:
        return None
    # Coarsest field present fixes the period: an entry pinning Hour fires daily,
    # one pinning only Minute fires hourly, and so on.
    periods: List[float] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        if "Month" in entry:
            periods.append(365 * 86400.0)
        elif "Day" in entry:
            periods.append(30 * 86400.0)
        elif "Weekday" in entry:
            periods.append(7 * 86400.0)
        elif "Hour" in entry:
            periods.append(86400.0)
        elif "Minute" in entry:
            periods.append(3600.0)
        else:
            periods.append(60.0)
    # N entries of the same period fire N times per period. Dividing keeps the
    # estimate on the URGENT side — rounding the other way would hide drift.
    return min(periods) / len(entries)


def _entrypoints_from_plists(agent_dir: Path) -> List[dict]:
    """(label, script, interval_sec) for every SPA launchd job.

    Unreadable plist ⇒ recorded rather than skipped. ``interval_sec`` is ``None``
    when the schedule could not be read — consumers must not read that as "rare".
    """
    out: List[dict] = []
    try:
        plists = sorted(Path(agent_dir).glob(AGENT_GLOB))
    except Exception as exc:  # noqa: BLE001
        log.warning("acceptance: cannot list %s (%s)", agent_dir, exc)
        return out
    for p in plists:
        label = p.stem
        try:
            with open(p, "rb") as fh:
                doc = plistlib.load(fh)
        except Exception as exc:  # noqa: BLE001
            out.append({"label": label, "script": None, "interval_sec": None,
                        "problem": "plist unreadable: {}".format(exc)})
            continue
        args = doc.get("ProgramArguments") or ([doc["Program"]] if doc.get("Program") else [])
        script = next((a for a in args if isinstance(a, str) and a.endswith((".sh", ".command", ".py"))), None)
        if script is None:
            # Nothing script-like: an inline binary invocation, not our concern.
            continue
        out.append({"label": label, "script": script,
                    "interval_sec": _schedule_interval_sec(doc), "problem": None})
    return out


def check_entrypoints(agent_dir: Optional[Path] = None) -> List[dict]:
    """Entrypoints that cannot be executed. THE 2026-08-04 failure.

    launchd reports exit 126 for a non-executable entrypoint, which is invisible
    until someone reads the exit codes — and a heartbeat monitor cannot tell
    "never started" from "started and stayed quiet".
    """
    broken: List[dict] = []
    for entry in _entrypoints_from_plists(agent_dir or DEFAULT_AGENT_DIR):
        if entry.get("problem"):
            broken.append(entry)
            continue
        script = entry["script"]
        if not os.path.isfile(script):
            broken.append({**entry, "problem": "entrypoint missing"})
        elif not os.access(script, os.X_OK):
            broken.append({**entry, "problem": "not executable (launchd would exit 126)"})
    return broken


def check_imports(
    modules=CRITICAL_IMPORTS,
    runner: Optional[Callable[[str], tuple]] = None,
    repo_root: Optional[Path] = None,
) -> List[dict]:
    """Modules that fail to import — the partial-copy failure mode.

    Imported in a SEPARATE process: this one already has them loaded, so an
    in-process import would answer about memory, not about the tree on disk.
    """
    failed: List[dict] = []
    root = Path(repo_root) if repo_root else _REPO_ROOT

    def _default(mod: str) -> tuple:
        try:
            proc = subprocess.run(
                ["python3", "-c", "import {}".format(mod)],
                cwd=str(root), capture_output=True, text=True, timeout=120)
        except Exception as exc:  # noqa: BLE001
            return False, "{}: {}".format(type(exc).__name__, exc)
        return proc.returncode == 0, (proc.stderr or "").strip()[-300:]

    run = runner or _default
    for mod in modules:
        ok, err = run(mod)
        if not ok:
            failed.append({"module": mod, "error": err})
    return failed


def _data_dir_for(data_dir: Optional[Path], repo_root: Optional[Path]) -> Path:
    """Каталог, О КОТОРОМ выносится вердикт. Решается ОДИН раз, для всех проверок.

    Иначе половины отчёта расходятся в том, какое дерево судят: признак worktree
    брался у `repo_root`, а свежесть мерилась у `_REPO_ROOT` — дерева, из которого
    ИМПОРТИРОВАН этот модуль. Когда приёмку зовут из worktree про прод (а правило
    доставки требует гонять её ровно так — до и после изменения дерева), это давало
    уверенное «просроченных артефактов нет», посчитанное по git-checkout'у, который
    свеж ПО ПОСТРОЕНИЮ: mtime у него — момент создания worktree.

    Зеркало аварии 2026-08-08 из шапки `test_acceptance_knows_its_tree`: там
    неверное дерево дало ложную ТРЕВОГУ, здесь — ложную ТИШИНУ. Тишина хуже:
    ложную тревогу идут проверять, а «чистый счёт» закрывают не читая.
    """
    if data_dir is not None:
        return Path(data_dir)          # явное указание вызывающего — не угадываем
    if repo_root is not None:
        return Path(repo_root) / "data"  # спросили про ЭТО дерево — про него и отвечаем
    return _REPO_ROOT / "data"


def check_scheduled_artifacts(
    data_dir: Optional[Path] = None,
    table: Optional[Dict[str, float]] = None,
    now: Optional[float] = None,
    repo_root: Optional[Path] = None,
) -> List[dict]:
    """Artifacts a scheduled job should have refreshed, but did not.

    A missing file is overdue by definition — "never produced" is the worst
    version of "not fresh", not an exemption from the check.

    ``repo_root`` называет дерево, о котором спрашивают (см. ``_data_dir_for``):
    без него прямой вызов получил бы вердикт о дереве, из которого импортирован
    модуль, а не о том, про которое спросили.
    """
    ddir = _data_dir_for(data_dir, repo_root)
    now = now if now is not None else time.time()
    overdue: List[dict] = []
    # Каталога нет вовсе — это тоже вердикт, а не повод вернуть пустой список.
    # Причину называем отдельно: «работа не запускалась» и «мерить негде» лечатся
    # по-разному, а слить их в одну строку — значит спрятать вторую.
    dir_missing = not ddir.is_dir()
    for name, max_age_h in (table or SCHEDULED_ARTIFACTS).items():
        f = ddir / name
        if not f.is_file():
            overdue.append({"artifact": name, "age_hours": None, "max_hours": max_age_h,
                            "problem": ("no data/ directory at {} — nothing to measure".format(ddir)
                                        if dir_missing else "never produced")})
            continue
        age_h = (now - f.stat().st_mtime) / 3600.0
        if age_h > max_age_h:
            overdue.append({"artifact": name, "age_hours": round(age_h, 2),
                            "max_hours": max_age_h, "problem": "stale — the job did not run"})
    return overdue


def run_acceptance(
    *,
    agent_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    modules=CRITICAL_IMPORTS,
    artifacts: Optional[Dict[str, float]] = None,
    import_runner: Optional[Callable[[str], tuple]] = None,
    write: bool = True,
) -> dict:
    """Run all three checks and produce a verdict. Never raises."""
    rep = AcceptanceReport(checked_at=datetime.now(timezone.utc).isoformat())
    try:
        entries = _entrypoints_from_plists(agent_dir or DEFAULT_AGENT_DIR)
        rep.entrypoints_total = len(entries)
        rep.entrypoints_broken = check_entrypoints(agent_dir)
        rep.imports_failed = check_imports(modules, import_runner, repo_root)
        if data_dir is None and measuring_from_worktree(repo_root):
            # Не измеряем то, о чём не можем судить. «Не измерено» — честный ответ;
            # уверенное «протухло» про чужое дерево было бы ложной тревогой, а
            # ложная тревога учит выключать проверку.
            rep.artifacts_unchecked = (
                "измерено из git-worktree: data/ здесь — checkout, а не живое "
                "состояние прода. Свежесть артефактов НЕ ПРОВЕРЕНА. Запусти приёмку "
                "из рабочего дерева прода.")
        else:
            rep.artifacts_overdue = check_scheduled_artifacts(
                data_dir, artifacts, repo_root=repo_root)

        if rep.entrypoints_broken:
            rep.reasons.append(
                "{}/{} launchd entrypoints cannot be executed — those agents are DEAD "
                "(launchd exit 126), heartbeats will only reveal it hours later: {}".format(
                    len(rep.entrypoints_broken), rep.entrypoints_total,
                    [e["label"] for e in rep.entrypoints_broken[:8]]))
        if rep.imports_failed:
            rep.reasons.append(
                "{} critical module(s) do not import — agents using them die on start: {}".format(
                    len(rep.imports_failed), [m["module"] for m in rep.imports_failed]))
        if rep.artifacts_overdue:
            rep.reasons.append(
                "{} scheduled artifact(s) overdue — the job did not run: {}".format(
                    len(rep.artifacts_overdue), [a["artifact"] for a in rep.artifacts_overdue]))

        if rep.artifacts_unchecked:
            rep.reasons.append(rep.artifacts_unchecked)

        if rep.entrypoints_broken or rep.imports_failed:
            rep.status = CRITICAL
        elif rep.artifacts_overdue or rep.artifacts_unchecked:
            rep.status = WARNING
        elif rep.entrypoints_total == 0:
            # No entrypoints found at all is not a clean bill of health: it means
            # the check looked in the wrong place and verified nothing.
            rep.status = CRITICAL
            rep.reasons.append("no launchd entrypoints found — nothing was actually verified")
        else:
            rep.status = OK
            rep.reasons.append(
                "{} entrypoints executable, {} modules import, artifacts fresh".format(
                    rep.entrypoints_total, len(modules)))
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED, never a quiet pass
        rep.status = CRITICAL
        rep.reasons.append("acceptance check itself failed: {}: {}".format(type(exc).__name__, exc))

    doc = rep.to_dict()
    doc["monitor"] = "deployment_acceptance"
    doc["note"] = ("Answers only 'can this fleet start?'. It does not verify the code is the "
                   "delivered version (deployment_drift) nor that agents are producing "
                   "(agent_health) — three different questions, none replaces another.")
    if write:
        try:
            # Квитанция ложится в ТО ЖЕ дерево, о котором вердикт: иначе отчёт о
            # проде приземляется в data/ worktree, где его никто не читает.
            atomic_save(doc, str(_data_dir_for(data_dir, repo_root) / STATE_FILENAME))
        except Exception as exc:  # noqa: BLE001
            log.warning("acceptance: could not persist state (%s)", exc)

    (log.error if rep.status == CRITICAL else log.warning if rep.status == WARNING else log.info)(
        "deployment_acceptance: %s — %s", rep.status, "; ".join(rep.reasons))
    return doc


def format_report_text(doc: dict) -> str:
    icon = {OK: "✅", WARNING: "⚠️", CRITICAL: "🚨"}.get(doc.get("status"), "❓")
    lines = ["{} deployment_acceptance: {}".format(icon, doc.get("status")),
             "  entrypoints : {} checked, {} broken".format(
                 doc.get("entrypoints_total"), len(doc.get("entrypoints_broken", []))),
             "  imports     : {} failed".format(len(doc.get("imports_failed", []))),
             "  artifacts   : {}".format(
                 doc.get("artifacts_unchecked")
                 or "{} overdue".format(len(doc.get("artifacts_overdue", []))))]
    for e in doc.get("entrypoints_broken", [])[:10]:
        lines.append("    ✗ {}: {}".format(e.get("label"), e.get("problem")))
    for m in doc.get("imports_failed", [])[:5]:
        lines.append("    ✗ import {}: {}".format(m.get("module"), str(m.get("error"))[:80]))
    for a in doc.get("artifacts_overdue", [])[:5]:
        lines.append("    ✗ {}: {} (limit {}h)".format(
            a.get("artifact"), a.get("problem"), a.get("max_hours")))
    for r in doc.get("reasons", []):
        lines.append("  • {}".format(r))
    return "\n".join(lines)


def main() -> int:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description="Deployment acceptance — can the fleet still start? "
                    "Run BEFORE and AFTER any change to the working tree.")
    ap.add_argument("--agent-dir", default=None)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    doc = run_acceptance(
        agent_dir=Path(args.agent_dir) if args.agent_dir else None,
        data_dir=Path(args.data_dir) if args.data_dir else None,
        repo_root=Path(args.repo_root) if args.repo_root else None,
        write=not args.no_write)
    print(format_report_text(doc))
    return {OK: 0, WARNING: 1, CRITICAL: 2}.get(doc.get("status"), 2)


if __name__ == "__main__":
    raise SystemExit(main())
