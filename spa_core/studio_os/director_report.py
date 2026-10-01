"""Director report — the Owner's one-screen answer to «что происходит?» (Studio OS, read-only).

Owner directive 2026-09-30 (Telegram Owner Control Plane epic): the Owner must understand the system
from an iPhone without CLI access. This module builds that answer from the CANONICAL sources only:

    SYSTEM   — trusted runtime + approved release (/Library/Application Support/StudioOS), launchd,
               data/agent_health.json (stale-aware), last daily cycle, disk space
    WORK     — tracker cards (nimbalyst-local/tracker, status + status_trail), origin/main history in
               the full mirror clone (the production clone is shallow)
    PRODUCT  — paper track status (data/paper_trading_status.json, data/golive_status.json), ADRs
    OWNER    — needs-owner cards (НУЖНО ОТ ЮРИЯ)
    ALERTS   — only exceptions: kill switch, CRITICAL agents, stale cycle, full disk

The lesson it is built around (Bridge b19.6.28): a status surface that derives a claim from something
other than the thing it claims about will eventually assert it forever. So every source that cannot be
read is reported as «не измерено» (invariant #17) — never as zero, never as «всё хорошо».

LLM FORBIDDEN. Stdlib only. Reads only, except ``--mark``, which records WHEN the Owner last saw the
summary (data/director_report_state.json) so «сделано с прошлого отчёта» has a real anchor.
Never moves capital, never touches risk, never sends anything: the caller (the Bridge Telegram bot)
renders the text. Every path and every external answer (launchctl, ps, git) is injectable for tests.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
MIRROR = Path.home() / "Documents" / "SPA_mirror"
TRUSTED_ROOT = Path("/Library/Application Support/StudioOS")
STATE_FILE = "data/director_report_state.json"

#: A daily cycle older than this is a real exception (same SLA agent_health uses).
CYCLE_STALE_H = 26.0
#: A forward-paper tick older than this is an exception (the scheduler runs every 15 min).
TRADING_STALE_H = 2.0
#: Disk below this share free is an alert (2026-09-26: one log filled the Mac Mini to zero).
DISK_FREE_MIN = 0.10
#: Owner-facing services whose liveness the Owner actually feels.
KEY_SERVICES = (
    ("com.studiobridge.telegram", "Bridge-бот"),
    ("com.spa.telegram_bot", "SPA-бот"),
    ("com.studiobridge.coordinator", "координатор Bridge"),
    ("com.spa.apiserver", "API сайта"),
    ("com.spa.cloudflared", "туннель"),
)
NOT_MEASURED = "не измерено"
SECTIONS = ("summary", "system", "work", "product", "owner", "alerts")


# ── sources (each returns a value or None = NOT MEASURED) ──────────────────────────────────────
def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _run(args: List[str], timeout: float = 15.0, cwd: Optional[Path] = None) -> Optional[str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           cwd=str(cwd) if cwd else None)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def _parse_ts(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class Card:
    path: str
    kind: str          # inbox / own / owner / agent
    title: str
    status: str
    created: str
    trail: List[str] = field(default_factory=list)


_FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v.strip()


def parse_card(path: Path) -> Optional[Card]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _FM_RE.match(text)
    if not m:
        return None
    fm = m.group(1)
    fields: Dict[str, str] = {}
    trail: List[str] = []
    in_trail = False
    for line in fm.splitlines():
        if in_trail:
            if line.startswith("  - ") or line.startswith("- "):
                trail.append(_unquote(line.split("- ", 1)[1]))
                continue
            in_trail = False
        if line.startswith("status_trail:"):
            in_trail = True
            continue
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            fields[k.strip()] = _unquote(v)
    status = fields.get("status")
    if not status:
        return None
    return Card(path=path.name, kind=path.name.split("-", 1)[0], title=fields.get("title", path.stem),
                status=status, created=fields.get("created", ""), trail=trail)


def load_cards(tracker: Path) -> Optional[List[Card]]:
    if not tracker.is_dir():
        return None
    out = []
    for p in sorted(tracker.glob("*.md")):
        if p.name.startswith("_"):
            continue
        c = parse_card(p)
        if c:
            out.append(c)
    return out


_TRAIL_RE = re.compile(r"^(\S+)\s+(\S+)\s*->\s*(\S+)")


def became_done_since(card: Card, since: datetime) -> bool:
    for t in card.trail:
        m = _TRAIL_RE.match(t)
        if m and m.group(3) == "done":
            ts = _parse_ts(m.group(1))
            if ts and ts >= since:
                return True
    return False


def parse_launchctl_list(text: Optional[str]) -> Optional[Dict[str, dict]]:
    if text is None:
        return None
    out = {}
    for line in text.splitlines():
        p = line.split("\t")
        if len(p) == 3 and p[2] != "Label":
            pid = int(p[0]) if p[0].strip().isdigit() else 0
            out[p[2].strip()] = {"pid": pid, "exit": p[1].strip()}
    return out


def count_claude_sessions(ps_text: Optional[str]) -> Optional[int]:
    """Headless Claude worker sessions (`claude -p …`) currently running."""
    if ps_text is None:
        return None
    n = 0
    for line in ps_text.splitlines():
        cmd = line.strip()
        if re.search(r"(^|/)claude(\s|$)", cmd) and " -p " in f" {cmd} " and "claude_run_with_timeout" not in cmd:
            n += 1
    return n


# ── the report model ───────────────────────────────────────────────────────────────────────────
@dataclass
class Inputs:
    repo: Path = REPO
    mirror: Path = MIRROR
    trusted_root: Path = TRUSTED_ROOT
    now: Optional[datetime] = None
    launchctl_text: Optional[str] = None
    ps_text: Optional[str] = None
    git_log: Optional[Callable[[datetime], Optional[List[str]]]] = None
    disk_usage: Optional[Callable[[str], Any]] = None
    measure_host: bool = True   # False in tests: never ask the real machine


def _git_log_since(mirror: Path, since: datetime) -> Optional[List[str]]:
    out = _run(["git", "-C", str(mirror), "log", "origin/main", f"--since={since.isoformat()}",
                "--format=%H", "--name-status"], timeout=20)
    if out is None:
        return None
    return out.splitlines()


def collect(inp: Inputs) -> dict:
    now = inp.now or datetime.now(timezone.utc)
    repo = Path(inp.repo)
    rep: dict = {"generated_at": now.isoformat(timespec="seconds")}

    # previous report anchor
    st = _read_json(repo / STATE_FILE)          # None ⇒ the Owner has not looked yet
    prev = _parse_ts(st.get("last_summary_at")) if isinstance(st, dict) else None
    rep["previous_report_at"] = prev.isoformat(timespec="seconds") if prev else None
    since = prev or (now - timedelta(hours=24))
    rep["since"] = since.isoformat(timespec="seconds")
    rep["since_basis"] = "previous_report" if prev else "last_24h"

    # SYSTEM — release / runtime (declared identity; the trusted plane owns its own verification)
    appr = _read_json(Path(inp.trusted_root) / "approved_release.json")
    rt = _read_json(Path(inp.trusted_root) / "runtime.json")
    rep["approved_release"] = (appr or {}).get("approved_sha")
    rep["runtime_digest"] = (rt or {}).get("runtime_digest")
    rep["release_present"] = bool(rep["approved_release"]) and (
        Path(inp.trusted_root) / "releases" / str(rep["approved_release"])).is_dir()

    # SYSTEM — fleet health (stale-aware reader; a dead monitor must not keep saying «healthy»)
    try:
        from spa_core.monitoring.agent_health_monitor import load_report
        ah = load_report(repo / "data", now=now)
    except Exception:  # noqa: BLE001 — unreadable ⇒ not measured, surfaced below
        ah = None
    if isinstance(ah, dict) and ah.get("overall_status"):
        agents = ah["agents"] if isinstance(ah.get("agents"), list) else []
        rep["fleet"] = {
            "overall": ah.get("overall_status"),
            "ok": ah.get("healthy_count"), "warning": ah.get("warning_count"),
            "critical": ah.get("critical_count"), "total": ah.get("total_agents"),
            "critical_labels": [a.get("label") for a in agents if a.get("status") == "CRITICAL"],
            "disabled_labels": [a.get("label") for a in agents
                                if "intentionally disabled" in str(a.get("note") or "")],
            "snapshot_at": ah.get("timestamp"),
        }
    else:
        rep["fleet"] = None

    lc_text = inp.launchctl_text
    if lc_text is None and inp.measure_host:
        lc_text = _run(["launchctl", "list"])
    lc = parse_launchctl_list(lc_text)
    if lc is None:
        rep["services"] = None
    else:
        rep["services"] = [{"label": lbl, "name": name,
                            "loaded": lbl in lc, "running": bool(lc.get(lbl, {}).get("pid"))}
                           for lbl, name in KEY_SERVICES]

    ps_text = inp.ps_text
    if ps_text is None and inp.measure_host:
        ps_text = _run(["ps", "-axo", "command"])
    rep["claude_sessions"] = count_claude_sessions(ps_text)

    pts = _read_json(repo / "data" / "paper_trading_status.json")
    cyc = _parse_ts((pts or {}).get("last_cycle_ts"))
    rep["cycle_age_h"] = round((now - cyc).total_seconds() / 3600, 1) if cyc else None
    rep["cycle_status"] = (pts or {}).get("last_cycle_status")

    du = inp.disk_usage or (shutil.disk_usage if inp.measure_host else None)
    try:
        d = du("/") if du else None
        rep["disk_free_share"] = round(d.free / d.total, 3) if d else None
    except (OSError, AttributeError, ZeroDivisionError):
        rep["disk_free_share"] = None

    # WORK / OWNER — tracker
    cards = load_cards(repo / "nimbalyst-local" / "tracker")
    if cards is None:
        rep["work"] = None
        rep["owner"] = None
    else:
        def pick(pred):
            return [c for c in cards if pred(c)]
        in_prog = pick(lambda c: c.status == "in-progress" and c.kind in ("inbox", "agent"))
        blocked = pick(lambda c: c.status == "blocked")
        new = pick(lambda c: c.status == "new" and c.kind == "inbox")
        done = pick(lambda c: became_done_since(c, since))
        rep["work"] = {
            "in_progress": len(in_prog), "blocked": len(blocked), "new": len(new),
            "done_since": len(done),
            "done_titles": [c.title for c in done][:5],
            "in_progress_titles": [c.title for c in sorted(in_prog, key=lambda c: c.created,
                                                             reverse=True)][:5],
            "blocked_titles": [c.title for c in blocked][:5],
        }
        waiting = sorted(pick(lambda c: c.status == "needs-owner"), key=lambda c: c.created)
        rep["owner"] = {
            "needs_owner": len(waiting),
            "items": [{"title": c.title, "created": c.created, "card": c.path} for c in waiting],
        }

    # WORK — canonical history on origin/main (full mirror clone)
    gl = inp.git_log or (lambda s: _git_log_since(Path(inp.mirror), s))
    lines = gl(since) if (inp.git_log or inp.measure_host) else None
    if lines is None:
        rep["git"] = None
    else:
        commits = [ln for ln in lines if re.fullmatch(r"[0-9a-f]{40}", ln.strip())]
        adrs = sorted({ln.split("\t")[-1] for ln in lines
                       if ln.startswith("A\t") and "docs/decisions/ADR-" in ln})
        rep["git"] = {"commits": len(commits), "new_adrs": [Path(a).stem for a in adrs]}

    # KILL SWITCH — from the switch file itself, not the once-a-day cycle snapshot (a stop armed at
    # 10:00 would otherwise read «не взведён» until tomorrow's cycle). Missing file = not armed
    # (governance's own contract); unreadable = not measured.
    ks_path = repo / "data" / "kill_switch_active.json"
    if not ks_path.exists():
        kill = False
    else:
        ks = _read_json(ks_path)
        kill = None if not isinstance(ks, dict) else (ks.get("active") is not False)
    rep["kill_switch_active"] = kill

    # PRODUCT
    gls = _read_json(repo / "data" / "golive_status.json")
    rep["product"] = None if pts is None and gls is None else {
        "mode": (pts or {}).get("execution_mode"),
        "days_running": (pts or {}).get("days_running"),
        "golive_passed": (gls or {}).get("passed"), "golive_total": (gls or {}).get("total"),
        "golive_state": (gls or {}).get("go_live_state"),
        "kill_switch_active": kill,
    }

    # TRADING RESEARCH (read-only; the engine owns this state — spa_core/trading_research, ADR-525)
    trs = _read_json(repo / "data" / "trading_research" / "status.json")
    if not isinstance(trs, dict) or "generated_at_ms" not in trs:
        rep["trading"] = None
    else:
        age_h = round((now.timestamp() * 1000 - trs["generated_at_ms"]) / 3_600_000, 1)
        rep["trading"] = {**{k: trs.get(k) for k in ("ok", "candidates", "backtest_qualified",
                                                     "forward_paper", "observations", "evidence_verified",
                                                     "live_capital_usd", "shortlist", "error")},
                          # stages absent ⇒ None (not measured); present but no such stage ⇒ a measured 0
                          "robust": (trs["stages"].get("ROBUST", 0) if isinstance(trs.get("stages"), dict) else None),
                          "champions": (trs["stages"].get("CHAMPION_CANDIDATE", 0)
                                        if isinstance(trs.get("stages"), dict) else None),
                          "age_h": age_h}

    # DEFI PAPER PORTFOLIOS (read-only; ONE read model shared with the site — ADR-533)
    try:
        from spa_core.defi_engine.package_status import build_all as _pkg_build
        rep["defi"] = _pkg_build(repo / "data", now)["packages"]
    except Exception as exc:  # noqa: BLE001 — a broken read model is a named gap, not a crash
        rep["defi"] = None
        rep["defi_error"] = f"{type(exc).__name__}: {exc}"

    # ALERTS — only exceptions
    alerts: List[str] = []
    t = rep["trading"]
    if t is not None and (t["ok"] is False or t["age_h"] > TRADING_STALE_H):
        alerts.append(f"🔴 торговое исследование: такт не шёл {t['age_h']:.0f} ч"
                      + (f" ({t['error']})" if t.get("error") else ""))
    elif t is not None and t["evidence_verified"] is False:
        alerts.append("🔴 торговое исследование: цепочка доказательств нарушена")
    if rep.get("defi") is None:
        alerts.append("❔ DeFi-портфели: " + NOT_MEASURED)
    else:
        for _name, _p in rep["defi"].items():
            if (_p.get("work") or {}).get("state") == "FAILED":
                alerts.append(f"🔴 DeFi {_name}: {(_p.get('work') or {}).get('reason')}")
    if kill is True:
        alerts.append("🛑 стоп-кран взведён")
    elif kill is None:
        alerts.append("❔ стоп-кран: " + NOT_MEASURED)
    if rep["fleet"] is None:
        alerts.append("❔ здоровье флота: " + NOT_MEASURED)
    elif rep["fleet"]["critical_labels"]:
        alerts.append("🔴 упали агенты: " + ", ".join(
            lbl.replace("com.spa.", "") for lbl in rep["fleet"]["critical_labels"][:6]))
    elif rep["fleet"]["overall"] in ("STALE", "UNCHECKED"):
        alerts.append(f"❔ снимок здоровья флота {rep['fleet']['overall']} — монитор молчит")
    if rep["cycle_age_h"] is None:
        alerts.append("❔ дневной цикл: " + NOT_MEASURED)
    elif rep["cycle_age_h"] > CYCLE_STALE_H:
        alerts.append(f"🔴 дневной цикл не шёл {rep['cycle_age_h']:.0f} ч")
    if rep["disk_free_share"] is not None and rep["disk_free_share"] < DISK_FREE_MIN:
        alerts.append(f"🔴 диск почти полон: свободно {rep['disk_free_share']:.0%}")
    for s in rep["services"] or []:
        if not s["running"]:
            alerts.append(f"🔴 {s['name']} не запущен")
    if rep["services"] is None:
        alerts.append("❔ службы launchd: " + NOT_MEASURED)
    rep["alerts"] = alerts
    red = any(a.startswith("🔴") or a.startswith("🛑") for a in alerts)
    rep["status"] = "red" if red else ("yellow" if alerts else "green")
    return rep


# ── rendering (plain text, iPhone-first: short lines, drill-down lives behind buttons) ─────────
_STATUS_WORD = {"green": "🟢 всё работает", "yellow": "🟡 есть что проверить", "red": "🔴 есть проблема"}


def _short(sha) -> str:
    return str(sha)[:8] if sha else NOT_MEASURED


def _hm(iso) -> str:
    dt = _parse_ts(iso)
    return dt.astimezone().strftime("%d.%m %H:%M") if dt else "—"


def _age_days(created: str, now: datetime) -> Optional[int]:
    try:
        d = datetime.strptime(created[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, (now - d).days)


def _clip(s: str, n: int = 90) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def render_owner(rep: dict, now: datetime, limit: int = 5) -> List[str]:
    o = rep.get("owner")
    if o is None:
        return ["НУЖНО ОТ ЮРИЯ: " + NOT_MEASURED]
    if not o["needs_owner"]:
        return ["НУЖНО ОТ ЮРИЯ: ничего — решений в очереди нет"]
    oldest = _age_days(o["items"][0]["created"], now)
    head = f"НУЖНО ОТ ЮРИЯ: {o['needs_owner']} решени{'е' if o['needs_owner'] == 1 else 'й'}"
    if oldest is not None:
        head += f" (старейшее {oldest} дн)"
    lines = [head]
    for it in o["items"][:limit]:
        age = _age_days(it["created"], now)
        lines.append(f"• {_clip(it['title'], 80)}" + (f" · {age} дн" if age is not None else ""))
    if o["needs_owner"] > limit:
        lines.append(f"… и ещё {o['needs_owner'] - limit}")
    return lines


def render_summary(rep: dict) -> str:
    now = _parse_ts(rep["generated_at"]) or datetime.now(timezone.utc)
    L = [f"🧭 ОТЧЁТ ДИРЕКТОРА · {_hm(rep['generated_at'])}", ""]
    L.append("СТАТУС: " + _STATUS_WORD[rep["status"]])
    f = rep.get("fleet")
    works = []
    if f:
        works.append(f"агенты {f['ok']}/{f['total']} в норме")
    svc = rep.get("services")
    if svc is not None:
        up = sum(1 for s in svc if s["running"])
        works.append(f"службы {up}/{len(svc)}")
    if rep.get("cycle_age_h") is not None:
        works.append(f"цикл {rep['cycle_age_h']:.1f} ч назад")
    works.append(f"релиз {_short(rep.get('approved_release'))}")
    L.append("РАБОТАЕТ: " + " · ".join(works))
    w, g = rep.get("work"), rep.get("git")
    basis = ("с прошлого отчёта " + _hm(rep["previous_report_at"])) if rep.get("previous_report_at") \
        else "за 24 ч (прошлого отчёта нет)"
    done = []
    if w is not None:
        done.append(f"карточек закрыто {w['done_since']} (по журналу статусов)")
    if g is not None:
        done.append(f"коммитов {g['commits']}")
        if g["new_adrs"]:
            done.append(f"решений ADR {len(g['new_adrs'])}")
    L.append(f"СДЕЛАНО ({basis}): " + (" · ".join(done) if done else NOT_MEASURED))
    if w is not None:
        inw = f"В РАБОТЕ: {w['in_progress']} задач · новых {w['new']}"
        if w["blocked"]:
            inw += f" · заблокировано {w['blocked']}"
    else:
        inw = "В РАБОТЕ: " + NOT_MEASURED
    if rep.get("claude_sessions") is not None:
        inw += f" · работников сейчас {rep['claude_sessions']}"
    L.append(inw)
    for line in render_defi(rep, short=True):
        L.append(line)
    t = rep.get("trading")
    if t is not None:
        L.append(f"TRADING: {t['candidates']} кандидатов · forward-paper {t['forward_paper']} · "
                 f"живой капитал {_usd_or_nm(t.get('live_capital_usd'))}")
    L.append("ПРОБЛЕМЫ: " + ("нет" if not rep["alerts"] else ""))
    for a in rep["alerts"][:6]:
        L.append(f"• {a}")
    L.append("")
    L.extend(render_owner(rep, now, limit=3))
    return "\n".join(L)


def render_system(rep: dict) -> str:
    L = ["🛰 СИСТЕМА"]
    L.append(f"Одобренный релиз: {_short(rep.get('approved_release'))}"
             + ("" if rep.get("release_present") else " (каталог релиза НЕ найден)"))
    L.append(f"Доверенный runtime: {_short(rep.get('runtime_digest'))}")
    f = rep.get("fleet")
    if f is None:
        L.append("Агенты: " + NOT_MEASURED)
    else:
        L.append(f"Агенты: {f['ok']} в норме · {f['warning']} предупр. · {f['critical']} крит. "
                 f"из {f['total']} (снимок {_hm(f['snapshot_at'])}, {f['overall']})")
        if f["critical_labels"]:
            L.append("  упали: " + ", ".join(x.replace("com.spa.", "") for x in f["critical_labels"]))
        if f["disabled_labels"]:
            L.append("  на паузе (намеренно): "
                     + ", ".join(x.replace("com.spa.", "") for x in f["disabled_labels"]))
    svc = rep.get("services")
    if svc is None:
        L.append("Службы: " + NOT_MEASURED)
    else:
        for s in svc:
            L.append(f"  {'✅' if s['running'] else '❌'} {s['name']}")
    cs = rep.get("claude_sessions")
    L.append("Работники Claude сейчас: " + (str(cs) if cs is not None else NOT_MEASURED))
    ca = rep.get("cycle_age_h")
    L.append("Дневной цикл: " + (f"{ca:.1f} ч назад ({rep.get('cycle_status')})" if ca is not None
                                 else NOT_MEASURED))
    ds = rep.get("disk_free_share")
    L.append("Диск свободен: " + (f"{ds:.0%}" if ds is not None else NOT_MEASURED))
    return "\n".join(L)


def render_work(rep: dict) -> str:
    L = ["🛠 РАБОТА"]
    w, g = rep.get("work"), rep.get("git")
    if w is None:
        return "\n".join(L + ["Трекер: " + NOT_MEASURED])
    L.append(f"Закрыто с {_hm(rep['since'])}: {w['done_since']} "
             "(учтены карточки с журналом статусов status_trail)")
    for t in w["done_titles"]:
        L.append(f"  ✓ {_clip(t)}")
    L.append(f"В работе: {w['in_progress']} · новых: {w['new']} · заблокировано: {w['blocked']}")
    for t in w["in_progress_titles"]:
        L.append(f"  ▶ {_clip(t)}")
    for t in w["blocked_titles"]:
        L.append(f"  ⛔ {_clip(t)}")
    if g is None:
        L.append("История origin/main: " + NOT_MEASURED)
    else:
        L.append(f"Коммитов в main: {g['commits']}")
        if g["new_adrs"]:
            L.append("Новые решения (ADR): " + ", ".join(_clip(a, 60) for a in g["new_adrs"][:5]))
    return "\n".join(L)


def render_product(rep: dict) -> str:
    p = rep.get("product")
    L = ["📈 ПРОДУКТ · Earn DeFi / SPA"]
    if p is None:
        return "\n".join(L + ["Трек: " + NOT_MEASURED, ""] + render_trading(rep))
    mode = "бумажный трек (капитал виртуальный)" if p.get("mode") != "live" else "LIVE"
    L.append(f"Режим: {mode}")
    if p.get("days_running") is not None:
        L.append(f"Трек идёт: {p['days_running']} дн")
    if p.get("golive_total"):
        L.append(f"Проверки готовности: {p['golive_passed']}/{p['golive_total']} · {p.get('golive_state')}")
    ks = p.get("kill_switch_active")
    L.append("Стоп-кран: " + ("ВЗВЕДЁН" if ks is True else "не взведён" if ks is False else NOT_MEASURED))
    L.append("")
    L.extend(render_defi(rep))
    L.append("")
    L.extend(render_trading(rep))
    return "\n".join(L)


_DEFI_WORD = {"RUNNING": "работает", "PAUSED": "пауза", "FAILED": "НЕ РАБОТАЕТ", "NOT_STARTED": "не запущен",
              "HEALTHY": "данные в норме", "WAITING_FOR_DATA": "ждёт данных", "DEGRADED": "данные неполные",
              "HOLD": "удержание", "WARMUP": "разогрев", "ACCUMULATING": "накапливает", "REPORTABLE": "отчётна"}


def render_defi(rep: dict, short: bool = False) -> List[str]:
    """Three paper portfolios — one line each; the mechanic version and why it holds (ADR-533)."""
    d = rep.get("defi")
    if d is None:
        return ["DEFI (3 бумажных портфеля): " + NOT_MEASURED]
    L = ["DEFI — 3 бумажных портфеля, реального капитала нет"]
    for name in ("conservative", "balanced", "aggressive"):
        p = d.get(name)
        if not isinstance(p, dict):
            L.append(f"• {name}: {NOT_MEASURED}")
            continue
        w, da, h = p.get("work"), p.get("data"), p.get("history")
        if not (isinstance(w, dict) and isinstance(da, dict) and isinstance(h, dict)):
            L.append(f"• {name}: {NOT_MEASURED} (статус неполный)")
            continue
        line = (f"• {name}: {_DEFI_WORD.get(w.get('state'), w.get('state'))} · "
                f"{_DEFI_WORD.get(da.get('state'), da.get('state'))} · "
                f"{_DEFI_WORD.get(h.get('state'), h.get('state'))} {h.get('valid_periods')} дн · "
                f"{p.get('running_version')}")
        if p.get("new_version_pending"):
            line += f" → {p['new_version_pending']['strategy_version']} (ждёт первой строки)"
        L.append(line)
        if not short and da.get("reason"):
            L.append(f"   причина: {_clip(str(da['reason']), 120)}")
    return L


def _usd_or_nm(v) -> str:
    return NOT_MEASURED if v is None else f"${v}"


def render_trading(rep: dict) -> List[str]:
    t = rep.get("trading")
    if t is None:
        return ["TRADING (исследование, бумага): " + NOT_MEASURED]
    L = ["TRADING — исследование и бумажный forward, реального капитала нет",
         f"Кандидатов: {t['candidates']} · прошли бэктест: {t['backtest_qualified']} · "
         f"forward-paper: {t['forward_paper']} · robust: {t['robust']} · чемпионов: {t['champions']}",
         f"Живой капитал: {_usd_or_nm(t.get('live_capital_usd'))} · наблюдений: {t['observations']} · "
         f"цепочка {'цела' if t['evidence_verified'] else 'НАРУШЕНА'} · такт {t['age_h']:.1f} ч назад"]
    if t.get("shortlist"):
        L.append("Лучшие кандидаты (разные сделки, OOS):")
        for s in t["shortlist"][:3]:
            name = s["id"].split(":")[0] + " " + s["id"].split(":")[2] + " " + s["id"].split(":")[3]
            fb = s.get("forward_bars") or 0
            fwd = (f" · forward {s['forward_net']:+.1%} за {fb} бар." if fb and s.get("forward_net") is not None
                   else " · forward только начался")
            L.append(f"• {name}: Sharpe OOS {s['oos_sharpe']:.2f}, просадка {s['oos_max_drawdown']:.0%}{fwd}")
    return L


def render_alerts(rep: dict) -> str:
    if not rep["alerts"]:
        return "🚨 ТРЕВОГИ: нет"
    return "\n".join(["🚨 ТРЕВОГИ"] + [f"• {a}" for a in rep["alerts"]])


def render(rep: dict, section: str = "summary") -> str:
    now = _parse_ts(rep["generated_at"]) or datetime.now(timezone.utc)
    if section == "owner":
        return "\n".join(["✋ " + render_owner(rep, now, limit=12)[0]] + render_owner(rep, now, limit=12)[1:])
    return {"summary": render_summary, "system": render_system, "work": render_work,
            "product": render_product, "alerts": render_alerts}[section](rep)


def mark_seen(repo: Path, at: datetime) -> None:
    from spa_core.utils.atomic import atomic_save
    atomic_save({"last_summary_at": at.isoformat(timespec="seconds")}, str(Path(repo) / STATE_FILE))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Studio OS Director report (read-only)")
    ap.add_argument("--section", choices=SECTIONS, default="summary")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--mark", action="store_true",
                    help="record that the Owner has now seen the summary (anchor for «сделано с прошлого отчёта»)")
    a = ap.parse_args(argv)
    rep = collect(Inputs())
    out = {"ok": True, "section": a.section, "text": render(rep, a.section), "report": rep}
    at = _parse_ts(rep["generated_at"])
    if a.mark and a.section == "summary" and at is not None:
        mark_seen(REPO, at)
    if a.format == "json":
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(out["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
