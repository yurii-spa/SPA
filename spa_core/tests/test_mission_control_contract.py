"""Mission Control v1 read model (ADR-552) — the contract, its honesty and its boundary.

Every test builds a disposable scene (production tree + origin mirror) and passes the clock IN, so
nothing here asks the real machine or reads the live tracker. What is held:

* every emitted section is declared in ``CONTRACT`` and every declared path exists (WP-A02);
* absence is ``NOT_MEASURED`` and age beyond the contract is ``STALE`` — never ``HEALTHY``/``0``/``[]``;
* colour follows health only (ADR-537);
* secrets, local paths, e-mails and long ids never reach the model;
* the owner queue means the same thing in Telegram (``director_report``) and here;
* real capital is ``LIVE_NOT_APPROVED`` only on readable evidence; otherwise ``UNKNOWN``;
* the lineage drill-down is the ``build_loop`` CLI's own answer;
* the SPA bot deep link opens exactly one card, for the owner only.
"""
# FROZEN-DATE-OK: injected-clock — NOW is passed into build()/collect() as MCInputs.now / Inputs.now
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.studio_os import build_loop as bl
from spa_core.studio_os import director_report as dr
from spa_core.studio_os import mission_control as mc

NOW = datetime.fromtimestamp(1_790_000_000, tz=timezone.utc)
ISO = "%Y-%m-%dT%H:%M:%SZ"
SECRET = "eyJhIjoiZmFrZXRva2VuZmFrZXRva2VuZmFrZXRva2Vu"


# ── scene ──────────────────────────────────────────────────────────────────────────────────────
def _card(d: Path, name: str, status: str, title: str, *, created=None, extra=(), body=None, trail=()):
    lines = ["---", f'title: "{title}"', f"status: {status}",
             f"created: {(created or NOW - timedelta(days=2)).date().isoformat()}"] + list(extra)
    if trail:
        lines.append("status_trail:")
        lines += [f'  - "{t}"' for t in trail]
    if body is None:
        body = ("## Что случилось и почему это важно\nПричина.\n\n## Что от тебя нужно\nВыбрать вариант.\n\n"
                "## Как понять, что готово\nКарточка закрыта.\n\n## Что будет после\nАгент применит.\n")
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("\n".join(lines + ["---", "", body]), encoding="utf-8")


def _w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _scene(tmp_path: Path, *, resources="OK", res_age_min=4, kill=False, mode="read_only_simulation"):
    repo, mirror = tmp_path / "prod", tmp_path / "mirror"
    ptr, otr = repo / "nimbalyst-local" / "tracker", mirror / "nimbalyst-local" / "tracker"
    data = repo / "data"
    # origin (mirror) — where questions land
    _card(otr, "own-a.md", "needs-owner", "Решить про порог", created=NOW - timedelta(days=9), extra=["adr: ADR-900"])
    _card(otr, "owner-decision-b.md", "needs-owner", "Выдать права ключу")
    _card(otr, "owner-decision-c.md", "needs-owner", "Уже отвечено в Telegram")
    _card(otr, "owner-decision-d.md", "owner-accepted", "Принято, в работе")
    _card(otr, "owner-decision-e.md", "needs-owner", "Битая карточка без секций", body="просто текст")
    _card(otr, "own-f.md", "owner-done", "Отклонено вчера",
          extra=['owner_choice: "не надо"', f"owner_answered_at: {(NOW - timedelta(days=1)).strftime(ISO)}"])
    _card(otr, "inbox-g.md", "in-progress", "Чинить сторожа",
          trail=[f"{(NOW - timedelta(hours=5)).isoformat()} new -> in-progress · queue.set_status"])
    _card(otr, "inbox-h.md", "done", "Сделали отчёт", extra=["closed_by: agent", "evidence: ADR-900"],
          trail=[f"{(NOW - timedelta(hours=3)).isoformat()} in-progress -> done · queue.set_status"])
    # production tree — the owner's answers land here first; it has every card except one origin is ahead with
    for f in otr.glob("*.md"):
        if f.name != "owner-decision-b.md":
            ptr.mkdir(parents=True, exist_ok=True)
            (ptr / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    _card(ptr, "owner-decision-c.md", "owner-done", "Уже отвечено в Telegram",
          extra=['owner_choice: "вариант 1"', f"owner_answered_at: {(NOW - timedelta(hours=2)).strftime(ISO)}"])
    (mirror / "docs").mkdir(parents=True)
    (mirror / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n\nLast confirmed by the owner: **2026-10-03**\n\n## Order of the next epics\n\n"
        "1. ~~Done epic~~ — closed\n2. Mission Control — in progress (ADR-552)\n3. Capital Allocator — later\n\n## Other\n",
        encoding="utf-8")
    if resources:
        _w(data / "resource_health.json", {
            "generated_at": (NOW - timedelta(minutes=res_age_min)).strftime(ISO), "overall": resources,
            "disk": {"state": "CRITICAL" if resources == "CRITICAL" else "OK",
                     "free_gb": 3.0 if resources == "CRITICAL" else 120.0, "warn_free_gb": 25, "critical_free_gb": 10},
            "memory": {"state": "OK", "pressure_level": 1, "swap": {"used_pct": 40.0}},
            "processes": {"rss_mb_by_class": {"claude": 900},
                          "top": [{"cmd": f"/opt/homebrew/bin/cloudflared tunnel run --token {SECRET}",
                                   "class": "service", "rss_mb": 40, "label": "com.spa.tunnel"}]}})
    _w(data / "code_sync_status.json", {"result": "IN_SYNC", "origin_main": "a" * 40, "timestamp": NOW.strftime(ISO)})
    _w(data / "deployment_acceptance.json", {"status": "OK"})
    _w(data / "orphan_report.json", {"generated_at": NOW.strftime(ISO), "total": 3, "counts": {"UNKNOWN_PURPOSE": 3}})
    _w(data / "paper_trading_status.json", {"execution_mode": mode})
    _w(data / "telegram" / "push_state.json", {"updated_at": NOW.strftime(ISO), "events": {}})
    _w(data / "dr_offsite_status.json", {"verified": True, "is_real_remote": False})
    _w(data / "resilience_status.json", {"restore_drill": {"all_ok": True, "stale": False, "never_run": False,
                                                           "last_ts": NOW.strftime(ISO)}})
    (data / "backups").mkdir(parents=True, exist_ok=True)
    (data / "backups" / "spa_state_x.tar.gz").write_bytes(b"x")
    return SimpleNamespace(repo=repo, mirror=mirror, data=data, kill=kill)


def _rep(kill=False, **over):
    rep = {"status": "green", "alerts": [], "services": [{"name": "apiserver", "running": True, "loaded": True}],
           "fleet": {"overall": "OK", "ok": 80, "warning": 0, "critical": 0, "total": 80,
                     "snapshot_at": NOW.strftime(ISO)},
           "trading": {"ok": True, "age_h": 0.2, "candidates": 138, "backtest_qualified": 4, "forward_paper": 4,
                       "observations": 10, "evidence_verified": None, "live_capital_usd": 0},
           "kill_switch_active": kill, "derisk_active": False, "claude_sessions": 1, "approved_release": "b" * 40}
    rep.update(over)
    return rep


def _pv(live=0):
    pkg = {"work": {"state": "RUNNING", "last_run_at": NOW.strftime(ISO)}, "data": {"state": "HEALTHY"},
           "decision": {"state": "OPEN", "position_en": "5 positions"}, "history": {"state": "WARMUP", "valid_periods": 2},
           "mode": {"state": "PAPER_ONLY", "live": "NOT_APPROVED"}, "mechanic_short_en": "lending", "running_version": "v1"}
    return {"generated_at": NOW.strftime(ISO), "live_capital_usd": live,
            "packages": {k: dict(pkg) for k in ("conservative", "balanced", "aggressive")}}


def _commits():
    return [{"sha": "c" * 9, "full": "c" * 40, "at": (NOW - timedelta(hours=1)).isoformat(),
             "subject": "feat(mc): Mission Control ADR-552 /Users/someone/x.py owner@example.com", "co_author": "Claude"}]


def _build(s, *, rep=None, packages=_pv, git=_commits, leases=lambda: [], sync=NOW - timedelta(minutes=20)):
    return mc.build(mc.MCInputs(repo=s.repo, mirror=s.mirror, now=NOW, measure_host=False, mirror_synced_at=sync,
                                collect=(lambda: rep if rep is not None else _rep(kill=s.kill)),
                                packages=packages, git_log=lambda h: git() if git else None, leases=leases))


def _walk_metas(node, path=""):
    if isinstance(node, dict):
        if isinstance(node.get("_meta"), dict):
            yield path, node["_meta"]
        for k, v in node.items():
            if k not in ("_meta", "contract"):
                yield from _walk_metas(v, f"{path}.{k}" if path else k)


def _get(model, path):
    cur = model
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return KeyError
        cur = cur[part]
    return cur


# ── WP-A02 contract ────────────────────────────────────────────────────────────────────────────
def test_every_declared_path_exists_and_every_section_is_declared(tmp_path):
    m = _build(_scene(tmp_path))
    declared = {r["path"] for r in mc.CONTRACT}
    for row in mc.CONTRACT:
        assert set(row) >= {"path", "source", "stale_after_min", "unknown", "redaction", "mobile", "alert"}, row
        assert _get(m, row["path"]) is not KeyError, row["path"]
    emitted = {f"{a}.{k}" for a in ("overview", "capital", "studio", "system") for k in m[a] if not k.startswith("_")
               and k not in ("boundary", "sessions")}
    emitted |= {"decisions", "intake", "release_feed"}
    assert emitted <= declared, sorted(emitted - declared)
    assert set(mc.AREAS) == {"overview", "capital", "studio", "decisions", "system"}


def test_colour_follows_health_only(tmp_path):
    m = _build(_scene(tmp_path))
    metas = list(_walk_metas(m))
    assert len(metas) >= 15
    for path, meta in metas:
        assert meta["state"] in mc.HEALTH, path
        assert meta["colour"] == mc.COLOUR[meta["state"]], path
    assert m["capital"]["packages"]["status_colour_is_not_a_risk_grade"] is True
    assert "never profit" in m["vocabulary"]["colour_rule"]


def test_healthy_scene_is_healthy(tmp_path):
    m = _build(_scene(tmp_path))
    assert m["system"]["_meta"]["state"] == "HEALTHY"
    assert m["overview"]["system"]["state"] == "HEALTHY"
    assert m["overview"]["now"]["current_epic"]["epic"] == "Mission Control"
    assert m["overview"]["now"]["current_epic"]["state"] == "IN_PROGRESS"
    assert m["studio"]["epics"]["items"][0]["state"] == "DONE"


# ── inv. #17: absence and age are their own values ────────────────────────────────────────────
def test_unreadable_sources_are_not_measured_never_green(tmp_path):
    s = _scene(tmp_path, resources=None)
    for f in ("code_sync_status.json", "orphan_report.json", "dr_offsite_status.json"):
        (s.data / f).unlink()
    (s.data / "backups" / "spa_state_x.tar.gz").unlink()
    m = _build(s, rep={"_error": "boom"}, packages=lambda: None, git=None, leases=lambda: None)
    for sec in (m["system"]["resources"], m["system"]["backups"], m["system"]["code"], m["system"]["services"],
                m["system"]["agents"], m["capital"]["packages"], m["capital"]["trading_research"],
                m["studio"]["orphans"], m["release_feed"]):
        assert sec["_meta"]["state"] == "NOT_MEASURED", sec
        assert sec["_meta"]["reason"]
    assert m["system"]["_meta"]["state"] == "NOT_MEASURED"
    assert m["system"]["heavy_jobs"] is None and m["overview"]["now"]["heavy_jobs"] is None
    assert m["system"]["kill_switch"] is None
    assert m["overview"]["system"]["kill_switch"] is None
    assert "kill switch not measured" in m["system"]["_meta"]["reason"]
    # the execution mode is still readable (read_only_simulation) — that, not an engine constant, is the basis
    assert m["capital"]["real_capital"]["state"] == "LIVE_NOT_APPROVED"
    assert "execution_mode=read_only_simulation" in m["capital"]["real_capital"]["basis"]


def test_no_tracker_means_owner_queue_not_measured(tmp_path):
    s = _scene(tmp_path)
    import shutil
    shutil.rmtree(s.mirror / "nimbalyst-local")
    m = _build(s)
    assert m["decisions"]["_meta"]["state"] == "NOT_MEASURED"
    assert m["overview"]["needs_owner"] == {"count": None}
    assert m["studio"]["board"]["_meta"]["state"] == "NOT_MEASURED"


def test_stale_guard_reading_is_stale_and_degrades_the_system(tmp_path):
    m = _build(_scene(tmp_path, res_age_min=60))
    assert m["system"]["resources"]["_meta"]["state"] == "STALE"
    assert "contract: 20" in m["system"]["resources"]["_meta"]["reason"]
    assert m["system"]["_meta"]["state"] == "DEGRADED"


@pytest.mark.parametrize("overall, expect", [("WARN", "DEGRADED"), ("CRITICAL", "CRITICAL")])
def test_resource_pressure_reaches_the_overview(tmp_path, overall, expect):
    m = _build(_scene(tmp_path, resources=overall))
    assert m["system"]["resources"]["_meta"]["state"] == expect
    assert m["overview"]["resources"]["state"] == expect
    assert m["system"]["_meta"]["state"] == expect


def test_armed_kill_switch_is_critical(tmp_path):
    m = _build(_scene(tmp_path, kill=True))
    assert m["system"]["kill_switch"] is True
    assert m["system"]["_meta"]["state"] == "CRITICAL"


# ── redaction ──────────────────────────────────────────────────────────────────────────────────
def test_no_secret_path_or_email_reaches_the_model(tmp_path):
    s = _scene(tmp_path)
    _card(s.mirror / "nimbalyst-local" / "tracker", "owner-decision-z.md", "needs-owner",
          f"Ротация /Users/someone/.secret owner@example.com 123456789012",
          body=f"## Что случилось\n--token {SECRET} в /private/var/x\n\n## Что от тебя нужно\nПовернуть.\n")
    rep = _rep(alerts=[f"🔴 cloudflared --token {SECRET} упал в /Users/someone/Library/x"])
    m = _build(s, rep=rep)
    blob = json.dumps(m, ensure_ascii=False)
    for leak in (SECRET, "/Users/", "/private/", "owner@example.com", "123456789012", "someone"):
        assert leak not in blob, leak
    assert m["system"]["resources"]["top"][0]["name"] == "cloudflared"


def test_proc_name_keeps_the_name_and_drops_arguments():
    assert mc.proc_name(f"/x/python3 -m spa_core.telegram.bot --token {SECRET}") == "bot"
    assert mc.proc_name("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --flag") == "Google Chrome"
    assert mc.proc_name(None) == "?"


# ── owner decisions: one meaning in Telegram and here ──────────────────────────────────────────
def test_decision_cases(tmp_path):
    m = _build(_scene(tmp_path))
    d = {i["id"]: i for i in m["decisions"]["pending"]}
    assert d["own-a"]["state"] == "NEEDS_OWNER" and d["own-a"]["evidence"] == "ADR-900"
    assert d["owner-decision-b"]["evidence"] == "UNKNOWN"                  # missing evidence is named
    assert d["owner-decision-c"]["state"] == "ANSWERED"                    # answered in prod, origin lags
    assert d["owner-decision-d"]["state"] == "ACCEPTED"
    bad = d["owner-decision-e"]                                            # malformed card
    assert bad["missing_fields"] == ["reason", "requested_action"] and bad["reason"] == "UNKNOWN"
    assert m["decisions"]["counts"] == {"needs_owner": 3, "accepted_in_work": 1, "answered_awaiting_delivery": 1}
    assert [r["id"] for r in m["decisions"]["recently_resolved"]] == ["own-f"]
    assert m["decisions"]["recently_resolved"][0]["owner_answer"] == "не надо"
    for i in m["decisions"]["pending"]:
        assert i["answer_in"] == "telegram"
        if i["id"] == "owner-decision-b":                                  # origin is ahead of production
            assert i["telegram_link"] is None and "not in the production tracker" in i["telegram_link_note"]
            continue
        assert i["telegram_link"].startswith(f"https://t.me/{mc.TELEGRAM_BOT}?start=od_")
        assert len(i["telegram_link"].split("start=", 1)[1]) <= 64          # Telegram start payload limit


def test_owner_queue_count_matches_the_telegram_director(tmp_path):
    s = _scene(tmp_path)
    rep = dr.collect(dr.Inputs(repo=s.repo, mirror=s.mirror, now=NOW, measure_host=False,
                               launchctl_text="PID\tStatus\tLabel\n", ps_text="", git_log=lambda since: [],
                               disk_usage=lambda p: SimpleNamespace(free=40, total=100)))
    assert rep["owner"]["source"] == "origin tracker + production answers"
    m = _build(s, rep=rep)
    assert m["overview"]["needs_owner"]["count"] == rep["owner"]["needs_owner"] == 3
    assert m["overview"]["needs_owner"]["accepted_in_work"] == rep["owner"]["accepted_in_work"] == 1


def test_answered_statuses_are_one_shared_constant():
    src = Path(dr.__file__).read_text(encoding="utf-8")
    assert "ANSWERED_STATUSES" in src
    assert '("owner-done", "owner-accepted", "ingested")' not in src


# ── capital safety ─────────────────────────────────────────────────────────────────────────────
def test_real_capital_is_zero_only_on_evidence(tmp_path):
    m = _build(_scene(tmp_path))
    rc = m["capital"]["real_capital"]
    assert rc["state"] == "LIVE_NOT_APPROVED" and rc["usd"] == 0 and "read_only_simulation" in rc["basis"]
    m2 = _build(_scene(tmp_path / "live", mode="live"))
    assert m2["capital"]["real_capital"]["state"] == "UNKNOWN"
    s4 = _scene(tmp_path / "nomode")                      # WP-A05 #8: engines say 0 but the mode is unreadable
    (s4.data / "paper_trading_status.json").unlink()
    m4 = _build(s4)
    assert m4["capital"]["real_capital"] == {"state": "UNKNOWN", "usd": None, "basis": m4["capital"]["real_capital"]["basis"]}
    m3 = _build(_scene(tmp_path / "money"), packages=lambda: _pv(live=1000))
    assert m3["capital"]["real_capital"]["state"] == "UNKNOWN" and m3["capital"]["real_capital"]["usd"] is None


def test_read_model_has_no_write_or_execution_path():
    src = Path(mc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any("execution" in x or "telegram" in x for x in mods), mods
    called = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            called.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    for bad in ("write_text", "write_bytes", "open", "urlopen", "set_status", "record_owner_answer", "unlink",
                "rename", "rmtree", "kill", "post", "run_cycle"):
        assert bad not in called, bad
    assert [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and getattr(n.func, "id", "") == "atomic_save"].__len__() == 1      # the single --out write


# ── lineage drill-down = the build_loop CLI ────────────────────────────────────────────────────
def test_lineage_is_the_build_loop_answer(tmp_path):
    s = _scene(tmp_path)
    m = _build(s)
    assert "inbox-h" in m["studio"]["lineage"]
    cli = bl.lineage("inbox-h", tdir=s.mirror / "nimbalyst-local" / "tracker", root=s.mirror,
                     data_dir=s.data, memory=False)
    assert {k: v["state"] for k, v in m["studio"]["lineage"]["inbox-h"].items()} == \
           {k: v["state"] for k, v in cli["stages"].items()}
    assert m["studio"]["board"]["review"] is None and "no REVIEW status" in m["studio"]["board"]["review_note"]


def test_release_feed_is_a_summary_not_a_commit_dump(tmp_path):
    m = _build(_scene(tmp_path))
    it = m["release_feed"]["items"][0]
    assert it["kind"] == "decision" and it["adrs"] == ["ADR-552"] and it["commit"] == "c" * 9
    assert it["release"] == "PRODUCTION_UNKNOWN"                           # not measured ≠ in production
    assert m["overview"]["today"]["releases"] == 1


# ── SPA bot deep link (WP-A04) ─────────────────────────────────────────────────────────────────
@pytest.fixture
def bot(tmp_path, monkeypatch):
    from spa_core.telegram import bot as botmod
    from spa_core.telegram import owner_decisions as od
    tr = tmp_path / "tracker"
    _card(tr, "owner-decision-long-slug-alpha.md", "needs-owner", "A")
    _card(tr, "owner-decision-long-slug-beta.md", "needs-owner", "B")
    _card(tr, "own-x.md", "needs-owner", "X")
    monkeypatch.setattr(od, "_live_tracker_dir", lambda _=None: tr)
    b = object.__new__(botmod.TelegramBot)
    sent = []
    b._get_router = lambda: SimpleNamespace(is_owner=lambda chat: chat == "OWNER")
    b._send_card = lambda path, chat: sent.append(Path(path).name)
    return SimpleNamespace(b=b, sent=sent)


@pytest.mark.parametrize("text, chat, expect", [
    ("/start od_own-x", "OWNER", "own-x.md"),
    ("/start od_owner-decision-long-slug-al", "OWNER", "owner-decision-long-slug-alpha.md"),
    ("/start od_owner-decision-long-slug", "OWNER", None),                 # ambiguous prefix
    ("/start od_own-x", "STRANGER", None),                                 # not the owner
    ("/start od_../own-x", "OWNER", None),                                 # malformed payload
    ("/start od_own-*", "OWNER", None),                                    # glob metacharacters refused
    ("/start", "OWNER", None),
])
def test_decision_deeplink_opens_exactly_one_card_for_the_owner(bot, text, chat, expect):
    handled = bot.b._handle_decision_deeplink(text, chat)
    assert handled is (expect is not None)
    assert bot.sent == ([expect] if expect else [])


def test_every_model_link_resolves_through_the_bot(tmp_path, monkeypatch):
    from spa_core.telegram import bot as botmod
    from spa_core.telegram import owner_decisions as od
    s = _scene(tmp_path)
    long = "owner-decision-" + "x" * 70
    for root in (s.mirror, s.repo):
        _card(root / "nimbalyst-local" / "tracker", f"{long}.md", "needs-owner", "Длинный слаг")
    _card(s.mirror / "nimbalyst-local" / "tracker", "owner-decision-AI1-upper.md", "needs-owner", "Вне грамматики")
    _card(s.repo / "nimbalyst-local" / "tracker", "owner-decision-AI1-upper.md", "needs-owner", "Вне грамматики")
    m = _build(s)
    # the bot resolves in the PRODUCTION tracker (WP-A05 #10: the mirror stand-in hid the lag case)
    monkeypatch.setattr(od, "_live_tracker_dir", lambda _=None: s.repo / "nimbalyst-local" / "tracker")
    b = object.__new__(botmod.TelegramBot)
    sent = []
    b._get_router = lambda: SimpleNamespace(is_owner=lambda chat: True)
    b._send_card = lambda path, chat: sent.append(Path(path).stem)
    linked = [i for i in m["decisions"]["pending"] if i["telegram_link"]]
    for i in linked:
        payload = i["telegram_link"].split("?start=", 1)[1]
        assert b._handle_decision_deeplink(f"/start {payload}", "OWNER"), i["id"]
    assert sent == [i["id"] for i in linked]
    unlinked = {i["id"]: i["telegram_link_note"] for i in m["decisions"]["pending"] if not i["telegram_link"]}
    assert set(unlinked) == {"owner-decision-b", "owner-decision-AI1-upper"}, unlinked
    assert all(unlinked.values())


def test_every_non_healthy_section_names_its_reason(tmp_path):
    rep = _rep(fleet={"overall": "WARNING", "ok": 78, "warning": 2, "critical": 0, "total": 80,
                      "snapshot_at": NOW.strftime(ISO)})
    m = _build(_scene(tmp_path, res_age_min=60), rep=rep)
    for path, meta in _walk_metas(m):
        if meta["state"] != "HEALTHY":
            assert meta["reason"], path
    assert "agents DEGRADED" in m["system"]["_meta"]["reason"] and "resources STALE" in m["system"]["_meta"]["reason"]


def test_ui_translates_every_vocabulary_value_the_model_can_emit():
    """A missing key renders as the raw key («vocab.health.LIVE_NOT_APPROVED», found by the
    failure-injection run) — every state the model emits must have an RU and an EN label."""
    src = (Path(mc.__file__).parent / "mission_ui" / "i18n.js").read_text(encoding="utf-8")
    d = json.loads(src.split("/*I18N_START*/", 1)[1].split("/*I18N_END*/", 1)[0])
    groups = {"health": mc.HEALTH + ("UNKNOWN",), "work": mc.WORK, "decision": mc.DECISION,
              "capital_mode": mc.CAPITAL_MODE + ("UNKNOWN",)}
    for lang in ("ru", "en"):
        for g, values in groups.items():
            for v in values:
                assert f"vocab.{g}.{v}" in d[lang], (lang, g, v)
    app = (Path(mc.__file__).parent / "mission_ui" / "app.js").read_text(encoding="utf-8")
    assert "renderBadge(rc.state" not in app          # real capital is a mode, never a health badge


def test_stale_mirror_makes_the_owner_queue_and_board_stale(tmp_path):
    """WP-A05 #7: cards, board and history read from the origin mirror were «fresh» by construction."""
    m = _build(_scene(tmp_path), sync=NOW - timedelta(hours=5))
    for sec in (m["decisions"], m["studio"]["board"], m["studio"], m["release_feed"]):
        assert sec["_meta"]["state"] == "STALE", sec["_meta"]
    assert _build(_scene(tmp_path / "x"), sync=None)["decisions"]["_meta"]["state"] == "STALE"


def test_soft_derisk_and_package_failures_degrade_their_sections(tmp_path):
    m = _build(_scene(tmp_path), rep=_rep(derisk_active=True))
    assert m["system"]["_meta"]["state"] == "DEGRADED" and "soft de-risk" in m["system"]["_meta"]["reason"]
    assert m["system"]["derisk"] is True
    pv = _pv()
    pv["packages"]["balanced"]["work"] = {"state": "FAILED"}
    m2 = _build(_scene(tmp_path / "p"), packages=lambda: pv)
    assert m2["capital"]["packages"]["_meta"]["state"] == "CRITICAL" and "balanced" in m2["capital"]["packages"]["_meta"]["reason"]
    assert m2["capital"]["_meta"]["state"] == "CRITICAL"
    m3 = _build(_scene(tmp_path / "s"), rep=_rep(services=[]))
    assert m3["system"]["services"]["_meta"]["state"] == "NOT_MEASURED"


def test_release_label_claims_only_what_code_sync_delivers(tmp_path):
    """WP-A05 #6: a docs/site commit is not «in production» by code-sync."""
    commits = [dict(_commits()[0], files=["docs/x.md", "landing/src/pages/index.astro"]),
               dict(_commits()[0], sha="d" * 9, full="d" * 40, files=["spa_core/x.py"])]
    m = _build(_scene(tmp_path), git=lambda: commits)
    rel = {i["commit"]: i["release"] for i in m["release_feed"]["items"]}
    assert rel["c" * 9] == "NOT_APPLICABLE"
    assert rel["d" * 9] == "PRODUCTION_UNKNOWN"            # measure_host off: containment not asked
    assert "restart" in m["release_feed"]["release_note"]


@pytest.mark.parametrize("raw, leak", [
    ("bot 7712345678:AAF3kqABCDEFGHIJKLMNOPQRSTUVWXYZabcd died", "AAF3kq"),
    ("GET https://api.telegram.org/bot7712345678:AAF3kqABCDEFGHIJKLMNOPQRSTUVWXYZabcd/getUpdates", "AAF3kq"),
    ("cookie eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl", "eyJzdWIi"),
    ("Authorization: Bearer abc.def.ghi", "abc.def"),
    ("x-api-key: zzz123secret", "zzz123"),
    ("aws wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalrX"),
])
def test_safe_text_redacts_the_shapes_redact_cmd_misses(raw, leak):
    assert leak not in mc.safe_text(raw, 400)


def test_safe_text_keeps_card_slugs_and_plain_words():
    slug = "owner-decision-utochnenie-po-zametke-hrapovik-zamorozhe-very-long"
    assert mc.safe_text(f"named_cards_closed_at_origin:{slug}", 400).endswith(slug)
    assert mc.safe_text("a token was rotated today") == "a token was rotated today"


@pytest.mark.parametrize("drill, state, shown", [
    ({"all_ok": True, "stale": False, "never_run": False}, "HEALTHY", "OK"),
    ({"all_ok": False, "stale": False, "never_run": False}, "DEGRADED", "FAILED"),
    ({"all_ok": True, "stale": True, "never_run": False}, "DEGRADED", "STALE"),
    ({"never_run": True}, "DEGRADED", "NEVER_RUN"),
    (None, "DEGRADED", None),
])
def test_restore_drill_is_read_from_its_real_shape(tmp_path, drill, state, shown):
    """The fresh-session check found «Restore drill: not measured» under a «healthy» badge while the drill
    ran every day: the model read a `status` key the file never had."""
    s = _scene(tmp_path)
    if drill is None:
        (s.data / "resilience_status.json").unlink()
    else:
        _w(s.data / "resilience_status.json", {"restore_drill": dict(drill, last_ts=NOW.strftime(ISO))})
    b = _build(s)["system"]["backups"]
    assert b["restore_drill"] == shown and b["_meta"]["state"] == state
    if state != "HEALTHY":
        assert "restore drill" in b["_meta"]["reason"]


# ── Investment CIO (ADR-554) in the Capital area ────────────────────────────────────────────────
def test_cio_section_is_not_measured_before_any_recommendation(tmp_path):
    m = _build(_scene(tmp_path))
    cio = m["capital"]["investment_cio"]
    assert cio["_meta"]["state"] == "NOT_MEASURED" and cio["_meta"]["reason"]
    assert m["overview"]["capital"]["investment_cio"]["state"] == "NOT_MEASURED"


def test_cio_section_matches_the_canonical_read_and_never_executes(tmp_path):
    from spa_core.investment_cio import read as cio_read, run as cio_run
    s = _scene(tmp_path)
    assert cio_run.main(["--data-dir", str(s.data), "--now", NOW.strftime(ISO)]) == 0
    m = _build(s)
    cio, canon = m["capital"]["investment_cio"], cio_read.latest(s.data, now=NOW)
    assert cio["stance"] == canon["recommendation"]["stance"]
    assert cio["recommendation_id"] == canon["recommendation"]["recommendation_id"][:12]
    assert cio["executes"] is False and cio["role"]["role_id"] == "chief_investment_officer"
    assert cio["_meta"]["state"] == "HEALTHY" and cio["ledger"]["chain_ok"] is True
    assert "nothing executes it" in cio["boundary"]


def test_a_tampered_cio_ledger_is_critical_in_mission_control(tmp_path):
    from spa_core.investment_cio import run as cio_run
    s = _scene(tmp_path)
    assert cio_run.main(["--data-dir", str(s.data), "--now", NOW.strftime(ISO)]) == 0
    led = s.data / "investment_cio" / "ledger.jsonl"
    rows = [json.loads(x) for x in led.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows[-1]["recommendation"]["stance"] = "RECOMMEND"          # rewrite history after the fact
    led.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    cio = _build(s)["capital"]["investment_cio"]
    assert cio["_meta"]["state"] == "CRITICAL" and cio["integrity"] == "BROKEN"
    assert "stance" not in cio and "recommended_weights" not in cio      # a tampered recommendation is withheld
