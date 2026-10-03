"""Owner Control Plane seams (2026-09-30 epic): Telegram intake CLI + the Director report.

Two things are pinned here, both hermetic (tmp dirs, injected launchctl/ps/git/disk, no host):

1. **Canonical intake over a process seam** (`spa_core.owner_remote.cli`). The Studio Bridge bot calls
   it; SPA stays the single owner of card/idea/decision writes. `plan` never writes; `confirm` writes
   exactly once per token; RED never becomes a write — not even when a RED draft is confirmed directly.
2. **The Director report never claims what it did not read** (`spa_core.studio_os.director_report`):
   every missing source is «не измерено», a dead service is an alert, and the «since» anchor is the
   Owner's previous look, not a guess.

Clock: every timestamp is derived from one fixed NOW that is passed into the code under test.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.owner_remote import answers, cli, gateway
from spa_core.studio_os import director_report as dr

#: A fixed anchor passed INTO the code under test (never read from the wall clock at import:
#: a run that crosses midnight must not change what this file asserts).
NOW = datetime.fromtimestamp(1_790_000_000, tz=timezone.utc)


# ── intake seam ────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def seam(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "PENDING", tmp_path / "pending.json")
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    monkeypatch.setattr(gateway, "IDEAS", ideas)
    monkeypatch.setattr(gateway, "REPO", tmp_path)
    cards = []

    def fake_save(text, source="telegram", transcript=None):
        p = tmp_path / f"inbox-card-{len(cards)}.md"
        p.write_text(text, encoding="utf-8")
        cards.append((p, source))
        return p, text[:40]

    import spa_core.telegram.inbox_intake as ii
    import spa_core.studio_os.links as links
    monkeypatch.setattr(ii, "save_inbox_task", fake_save)
    monkeypatch.setattr(links, "record_link", lambda *a, **k: {"ok": True})
    return SimpleNamespace(cards=cards, ideas=ideas, tmp=tmp_path)


def test_plan_never_writes_and_confirm_writes_exactly_once(seam):
    p = cli.cmd_plan("Создай задачу проверить Morpho", "telegram_bridge", 11)
    assert p["action"] == "confirm" and p["kind"] == "task"
    assert seam.cards == []                                  # a plan is not a write
    r1 = gateway.confirm(p["token"])
    r2 = gateway.confirm(p["token"])                         # double tap / Telegram retry
    assert r1["ok"] and r2["ok"] and r2["idempotent"] is True
    assert len(seam.cards) == 1 and seam.cards[0][1] == "telegram_bridge"


def test_idea_goes_to_the_accepted_idea_home_once(seam):
    p = cli.cmd_plan("Добавь идею для Earn DeFi: сравнить Morpho и Aave", "telegram_bridge", 12)
    assert p["kind"] == "idea"
    r = gateway.confirm(p["token"])
    gateway.confirm(p["token"])
    files = list(seam.ideas.glob("*.md"))
    assert r["ok"] and r["kind"] == "idea" and len(files) == 1
    assert "Идея ≠ инструкция" in files[0].read_text(encoding="utf-8")
    assert seam.cards == []


def test_red_is_blocked_at_plan_and_again_at_confirm(seam):
    p = cli.cmd_plan("Переведи 10000 в Aave", "telegram_bridge", 13)
    assert p["action"] == "block" and "token" not in p
    # defence in depth: even a RED draft smuggled into the ledger cannot be confirmed
    gateway.register_pending("x:1", title="t", body="Создай задачу вывести деньги", source="s")
    assert gateway.confirm("x:1") == {"ok": False, "error": "red_blocked"}
    assert seam.cards == [] and not list(seam.ideas.glob("*"))


def test_unclassified_text_waits_for_the_owner_to_choose(seam):
    p = cli.cmd_plan("проверить Morpho", "telegram_bridge", 14)
    assert p["kind"] == "unclassified" and p["action"] == "clarify"
    assert gateway.confirm(p["token"])["ok"] is False           # no silent default
    assert gateway.confirm(p["token"], as_kind="task")["ok"] is True
    assert len(seam.cards) == 1


def test_a_real_question_is_answered_and_leaves_nothing_pending(seam):
    p = cli.cmd_plan("Покажи капитал", "telegram_bridge", 18)
    assert p["action"] == "report" and p["section"] == "product" and "token" not in p
    assert not gateway._load_pending()


# The ten cases the Owner required after the live defect of 2026-09-30 («Скажи, пожалуйста, что сейчас
# нужно от меня?» was offered «Как задачу / Как идею»). Text and the SAME words after Whisper take one path.
ROUTING = [
    ("Скажи, пожалуйста, что сейчас нужно от меня?", "report", "owner"),
    ("Что сейчас нужно от меня?", "report", "owner"),
    ("Что сейчас сломано?", "report", "alerts"),
    ("Что было сделано сегодня?", "report", "work"),
    ("Добавь задачу проверить Telegram завтра", "confirm", "task"),
    ("У меня идея добавить новый Trading Engine", "confirm", "idea"),
    ("Запиши решение оставить mission_tick выключенным", "confirm", "decision"),
    ("Что будет, если увеличить risk limit?", "explain", None),
    ("Увеличь risk limit", "block", None),
    ("проверить Morpho", "clarify", "unclassified"),
]


@pytest.mark.parametrize("text,action,detail", ROUTING)
def test_owner_routing_matrix(seam, text, action, detail):
    p = cli.cmd_plan(text, "telegram_bridge", 100)
    assert p["action"] == action, (text, p)
    if action == "report":
        assert p["section"] == detail and "token" not in p           # answered, nothing to record
    if action in ("confirm", "clarify"):
        assert p["kind"] == detail and p["token"]
    if action in ("report", "explain", "block"):
        assert not gateway._load_pending(), "a read or a refusal must leave no draft"
    assert seam.cards == [] and not list(seam.ideas.glob("*"))         # plan NEVER writes


@pytest.mark.parametrize("text,action,detail", ROUTING)
def test_voice_transcript_routes_exactly_like_text(seam, text, action, detail):
    typed = cli.cmd_plan(text, "telegram_bridge", 200)
    voiced = cli.cmd_plan(text, "telegram_bridge_voice", 200)
    for k in ("action", "intent", "zone", "section", "kind"):
        assert typed.get(k) == voiced.get(k), k


def test_explaining_a_risky_action_changes_nothing_and_ordering_it_is_red(seam):
    q = cli.cmd_plan("Что будет, если увеличить risk limit?", "telegram_bridge", 300)
    assert q["zone"] == "RED" and q["intent"] == "READ_QUESTION" and "никогда" in q["text"].lower()
    a = cli.cmd_plan("Увеличь risk limit", "telegram_bridge", 301)
    assert a["zone"] == "RED" and a["intent"] == "ACTION_COMMAND" and "token" not in a


def test_a_typed_draft_cannot_be_reclassified(seam):
    p = cli.cmd_plan("Добавь идею про новый отчёт", "telegram_bridge", 15)
    r = gateway.confirm(p["token"], as_kind="task")
    assert r["ok"] is False and seam.cards == []


def test_cancel_prevents_any_write(seam):
    p = cli.cmd_plan("Создай задачу обновить README", "telegram_bridge", 16)
    gateway.cancel(p["token"])
    assert gateway.confirm(p["token"])["error"] == "cancelled" and seam.cards == []


def test_cli_speaks_one_json_object(seam, capsys):
    assert cli.main(["plan", "--text", "Создай задачу X", "--source", "telegram_bridge",
                     "--message-id", "17"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["token"] == "telegram_bridge:17"


def test_green_answers_do_not_claim_health_without_a_read_model(monkeypatch):
    monkeypatch.setattr(answers, "_load", lambda rel: None)
    for fn in (answers.answer_broken, answers.answer_attention, answers.answer_active,
               answers.answer_blocked, answers.answer_decisions_waiting, answers.answer_system):
        assert fn() == answers.RM_MISSING, fn.__name__


# ── Director report ────────────────────────────────────────────────────────────────────────────
def _card(d: Path, name: str, status: str, title: str, created: datetime, trail=()):
    lines = ["---", f"title: \"{title}\"", f"status: {status}", f"created: {created.date().isoformat()}"]
    if trail:
        lines.append("status_trail:")
        lines += [f"  - \"{t}\"" for t in trail]
    (d / name).write_text("\n".join(lines + ["---", "", "body"]), encoding="utf-8")


def _repo(tmp_path: Path, *, cycle_age_h=2.0, agent_health=True, resources="OK") -> Path:
    repo = tmp_path / "repo"
    tr = repo / "nimbalyst-local" / "tracker"
    tr.mkdir(parents=True)
    data = repo / "data"
    data.mkdir()
    _card(tr, "own-a.md", "needs-owner", "Решить про порог", NOW - timedelta(days=9))
    _card(tr, "owner-decision-b.md", "needs-owner", "Выдать права ключу", NOW - timedelta(days=2))
    _card(tr, "inbox-c.md", "in-progress", "Чинить сторожа", NOW - timedelta(days=1))
    _card(tr, "inbox-d.md", "done", "Сделали отчёт", NOW - timedelta(days=3),
          trail=[f"{(NOW - timedelta(hours=3)).isoformat()} in-progress -> done · queue.set_status"])
    _card(tr, "inbox-e.md", "done", "Давно сделали", NOW - timedelta(days=30),
          trail=[f"{(NOW - timedelta(days=20)).isoformat()} new -> done · queue.set_status"])
    (data / "paper_trading_status.json").write_text(json.dumps({
        "execution_mode": "read_only_simulation", "days_running": 113, "last_cycle_status": "ok",
        "kill_switch_active": False,
        "last_cycle_ts": (NOW - timedelta(hours=cycle_age_h)).isoformat()}), encoding="utf-8")
    (data / "golive_status.json").write_text(json.dumps({"passed": 29, "total": 29}), encoding="utf-8")
    # ADR-552 / WP-A05 #5: a healthy world includes a FRESH clear reading of the drawdown kill switch;
    # without it the switch is «не измерено», never «не взведён».
    (data / "kill_switch_status.json").write_text(json.dumps({
        "generated_at": (NOW - timedelta(hours=1)).isoformat(), "triggered": False, "state": "CLEAR"}), encoding="utf-8")
    (data / "derisk_status.json").write_text(json.dumps({
        "generated_at": (NOW - timedelta(hours=1)).isoformat(), "active": False, "tier": "NONE"}), encoding="utf-8")
    if resources:
        # ADR-551: a healthy world includes a fresh resource-guard reading; its absence is NOT MEASURED.
        (data / "resource_health.json").write_text(json.dumps({
            "generated_at": (NOW - timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%SZ"), "overall": resources,
            "disk": {"state": "OK", "free_gb": 120.0}, "memory": {"state": "OK", "pressure_level": 1,
            "swap": {"used_pct": 40.0}}, "processes": {"top": [], "rss_mb_by_class": {}}}), encoding="utf-8")
    if agent_health:
        (data / "agent_health.json").write_text(json.dumps({
            "timestamp": (NOW - timedelta(minutes=10)).isoformat(), "cadence_minutes": 60,
            "stale_after_minutes": 90, "overall_status": "OK", "healthy_count": 80, "warning_count": 0,
            "critical_count": 0, "total_agents": 81, "agents": [
                {"label": "com.spa.mission_tick", "status": "OK",
                 "note": "intentionally disabled (launchctl disable)"}]}), encoding="utf-8")
    return repo


def _trusted(tmp_path: Path) -> Path:
    t = tmp_path / "StudioOS"
    (t / "releases" / "4cb68535aaaa").mkdir(parents=True, exist_ok=True)
    (t / "approved_release.json").write_text(json.dumps({"approved_sha": "4cb68535aaaa"}))
    (t / "runtime.json").write_text(json.dumps({"runtime_digest": "09eecca2ffff"}))
    return t


LAUNCHCTL_ALL_UP = "PID\tStatus\tLabel\n" + "\n".join(
    f"{100 + i}\t0\t{lbl}" for i, (lbl, _) in enumerate(dr.KEY_SERVICES))
PS = "/usr/bin/python3 x\n/Users/u/.local/bin/claude -p do the thing --x\n"


def _inputs(tmp_path, repo, **kw):
    base = dict(repo=repo, trusted_root=_trusted(tmp_path), now=NOW, launchctl_text=LAUNCHCTL_ALL_UP,
                ps_text=PS, git_log=lambda since: ["a" * 40, "A\tdocs/decisions/ADR-900-x.md"],
                disk_usage=lambda p: SimpleNamespace(free=40, total=100), measure_host=False)
    base.update(kw)
    return dr.Inputs(**base)


def test_summary_carries_every_section_and_the_owner_line(tmp_path):
    rep = dr.collect(_inputs(tmp_path, _repo(tmp_path)))
    text = dr.render(rep, "summary")
    for head in ("СТАТУС:", "РАБОТАЕТ:", "СДЕЛАНО", "В РАБОТЕ:", "ПРОБЛЕМЫ:", "НУЖНО ОТ ЮРИЯ: 2"):
        assert head in text, head
    assert rep["status"] == "green" and rep["alerts"] == []
    assert rep["work"]["done_since"] == 1          # only the transition inside the window counts
    assert rep["git"] == {"commits": 1, "new_adrs": ["ADR-900-x"]}
    assert "на паузе (намеренно): mission_tick" in dr.render(rep, "system")
    assert len(text) < 3500                         # one iPhone screen, never the 4096 limit


def test_a_stopped_owner_facing_service_is_a_red_alert(tmp_path):
    lc = LAUNCHCTL_ALL_UP.replace("100\t0\tcom.studiobridge.telegram", "-\t1\tcom.studiobridge.telegram")
    assert lc != LAUNCHCTL_ALL_UP
    rep = dr.collect(_inputs(tmp_path, _repo(tmp_path), launchctl_text=lc))
    assert rep["status"] == "red"
    assert any("Bridge-бот не запущен" in a for a in rep["alerts"])


def test_unread_sources_are_not_measured_never_green(tmp_path):
    repo = _repo(tmp_path, agent_health=False)
    import shutil as _sh
    _sh.rmtree(repo / "nimbalyst-local")
    rep = dr.collect(_inputs(tmp_path, repo, launchctl_text=None, git_log=lambda s: None))
    text = dr.render(rep, "summary")
    assert rep["status"] != "green"
    assert rep["work"] is None and rep["owner"] is None and rep["services"] is None
    assert "НУЖНО ОТ ЮРИЯ: не измерено" in text
    assert any("не измерено" in a for a in rep["alerts"])


def test_stale_cycle_and_full_disk_are_alerts(tmp_path):
    rep = dr.collect(_inputs(tmp_path, _repo(tmp_path, cycle_age_h=40),
                             disk_usage=lambda p: SimpleNamespace(free=3, total=100)))
    assert rep["status"] == "red"
    assert any("дневной цикл не шёл" in a for a in rep["alerts"])
    assert any("диск почти полон" in a for a in rep["alerts"])


def test_since_anchor_is_the_previous_look(tmp_path):
    repo = _repo(tmp_path)
    dr.mark_seen(repo, NOW - timedelta(hours=1))
    rep = dr.collect(_inputs(tmp_path, repo))
    assert rep["since_basis"] == "previous_report"
    assert rep["work"]["done_since"] == 0           # the only closure happened 3 h ago


def test_kill_switch_is_read_from_the_switch_file_not_the_daily_snapshot(tmp_path):
    repo = _repo(tmp_path)                          # daily snapshot says kill_switch_active: False
    (repo / "data" / "kill_switch_active.json").write_text(json.dumps(
        {"active": True, "reason": "manual_telegram"}), encoding="utf-8")
    rep = dr.collect(_inputs(tmp_path, repo))
    assert rep["status"] == "red" and "🛑 стоп-кран взведён" in rep["alerts"]
    assert "ВЗВЕДЁН" in dr.render(rep, "product")
    (repo / "data" / "kill_switch_active.json").write_text("{broken", encoding="utf-8")
    rep = dr.collect(_inputs(tmp_path, repo))
    assert rep["kill_switch_active"] is None and rep["status"] != "green"


def test_trading_research_block_and_its_staleness_alert(tmp_path):
    repo = _repo(tmp_path)
    tr = repo / "data" / "trading_research"
    tr.mkdir(parents=True)
    status = {"generated_at_ms": int((NOW - timedelta(minutes=10)).timestamp() * 1000), "ok": True,
              "candidates": 138, "backtest_qualified": 5, "forward_paper": 5, "observations": 40,
              "evidence_verified": True, "live_capital_usd": 0, "stages": {"FORWARD_PAPER": 5},
              "shortlist": [{"id": "donchian@v1:BTC:4h:spot_long:abc", "oos_sharpe": 1.17,
                             "oos_max_drawdown": -0.26, "forward_bars": 3, "forward_net": 0.01}]}
    (tr / "status.json").write_text(json.dumps(status), encoding="utf-8")
    rep = dr.collect(_inputs(tmp_path, repo))
    text = dr.render(rep, "product")
    assert "Кандидатов: 138" in text and "forward-paper: 5" in text and "Живой капитал: $0" in text
    assert "TRADING: 138 кандидатов" in dr.render(rep, "summary")
    assert not any("торговое" in a for a in rep["alerts"])
    status["generated_at_ms"] = int((NOW - timedelta(hours=5)).timestamp() * 1000)
    (tr / "status.json").write_text(json.dumps(status), encoding="utf-8")
    rep = dr.collect(_inputs(tmp_path, repo))
    assert any("такт не шёл 5 ч" in a for a in rep["alerts"]) and rep["status"] == "red"


def test_trading_status_absent_is_not_measured(tmp_path):
    rep = dr.collect(_inputs(tmp_path, _repo(tmp_path)))
    assert rep["trading"] is None and "TRADING (исследование, бумага): не измерено" in dr.render(rep, "product")


# ── ADR-551: resources are part of the owner's read model, and silence is not health ─────────

def test_resources_absent_is_not_measured_not_green(tmp_path):
    rep = dr.collect(_inputs(tmp_path, _repo(tmp_path, resources=None)))
    assert any("ресурсы Мака" in a and "НЕ ИЗМЕРЕНО" in a.upper() for a in rep["alerts"]), rep["alerts"]
    assert rep["status"] != "green"


def test_resources_critical_is_red_and_rendered(tmp_path):
    rep = dr.collect(_inputs(tmp_path, _repo(tmp_path, resources="CRITICAL")))
    assert rep["status"] == "red"
    assert any(a.startswith("🔴 ресурсы Мака") for a in rep["alerts"])
    assert "Ресурсы: CRITICAL" in dr.render(rep, "system")



def test_a_fleet_in_warning_is_yellow_with_names_not_green(tmp_path):
    """ADR-552: Mission Control showed DEGRADED while /report said «всё работает» for the same
    agent_health.json (4 agents in WARNING, 2026-10-03). One meaning in both places."""
    repo = _repo(tmp_path)
    ah = json.loads((repo / "data" / "agent_health.json").read_text())
    ah.update(overall_status="WARNING", warning_count=1)
    ah["agents"].append({"label": "com.spa.site_freshness", "status": "WARNING"})
    (repo / "data" / "agent_health.json").write_text(json.dumps(ah))
    rep = dr.collect(_inputs(tmp_path, repo))
    assert rep["status"] == "yellow"
    assert any(a.startswith("🟡 агенты с предупреждением: 1 — site_freshness") for a in rep["alerts"])


@pytest.mark.parametrize("status, expect", [
    ({"state": "CLEAR", "triggered": False, "hours": 1}, False),
    ({"state": "CLEAR_PARTIAL", "triggered": False, "hours": 1}, False),
    ({"state": "HARD_KILL", "triggered": True, "hours": 1}, True),
    ({"state": "UNMEASURED", "triggered": False, "hours": 1}, None),       # the switch's own third outcome
    ({"state": "CLEAR", "triggered": False, "hours": 30}, None),           # a stale CLEAR proves nothing
    (None, None),                                                          # file absent
])
def test_kill_switch_reading_keeps_the_third_outcome(tmp_path, status, expect):
    """WP-A05 #5: an UNMEASURED, stale or absent drawdown reading was shown as «не взведён»."""
    repo = _repo(tmp_path)
    f = repo / "data" / "kill_switch_status.json"
    if status is None:
        f.unlink()
    else:
        f.write_text(json.dumps({"generated_at": (NOW - timedelta(hours=status["hours"])).isoformat(),
                                 "state": status["state"], "triggered": status["triggered"]}))
    rep = dr.collect(_inputs(tmp_path, repo))
    assert rep["kill_switch_active"] is expect
    if expect is None:
        assert any(a.startswith("❔ стоп-кран") for a in rep["alerts"])


def test_soft_derisk_is_named(tmp_path):
    repo = _repo(tmp_path)
    (repo / "data" / "derisk_status.json").write_text(json.dumps({
        "generated_at": (NOW - timedelta(hours=1)).isoformat(), "active": True, "tier": "SOFT_DERISK"}))
    rep = dr.collect(_inputs(tmp_path, repo))
    assert rep["derisk_active"] is True and rep["status"] == "yellow"
