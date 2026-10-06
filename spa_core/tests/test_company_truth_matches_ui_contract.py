"""spa_core/tests/test_company_truth_matches_ui_contract.py — RM-TRUTH-01 Wave 2, round-2
integration review (2026-10-06): the producer (``company_truth.py``) and the renderer
(``mission_ui/app.js``) silently drifted apart on the Studio and Product tabs even though every
*other* test in the suite was green — ``renderMemory``/``renderBackups``/``renderTasks``/
``renderProblems``/``renderIncidents``/``renderReleases``/``renderMachine``/
``renderPublicMetrics``/``renderDecisionsSummary`` all read field NAMES this module never wrote
(a bare ``cell.lag`` that only existed as ``cell.value.lag``; ``studio.backups.local`` that was
actually named ``local_backup``; a Studio "machine" card that was never wired in at all; a public
metrics ARRAY that was actually a cell with a nested array the UI's ``Array.isArray()`` rejected).

Round 1 already covered CORRECTNESS (absence/staleness semantics, redaction, byte-identical
rebuilds) — this file covers SHAPE: does the real producer emit, under every key path the WP2
fixture (``fixtures/mission_truth_scene.json``, the UI's own contract — ``app.js`` reads exactly
this shape) declares, a value of a compatible kind? The walk is GENERIC (no hand-picked list of
paths) precisely because the round-1 defect class was "the one path nobody happened to check" —
a hand-picked list would only ever re-check the paths someone already thought of.
"""
# FROZEN-DATE-OK: injected-clock — NOW is passed explicitly into every function under test below
# (`ct.build(ct.TruthInputs(..., now=NOW))`); nothing here reads the real clock. Every on-disk
# fixture timestamp is derived from the SAME NOW anchor.
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from spa_core.studio_os import company_truth as ct

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
ISO = "%Y-%m-%dT%H:%M:%SZ"
FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "mission_truth_scene.json")
                     .read_text(encoding="utf-8"))

#: a card in this state carries ONLY the §2.0 cell envelope (``unknown()``'s own output) —
#: the extra bare fields a MEASURED card's renderer reads (``cell.lag``, ``cell.disk_free_gb``, …)
#: are simply inapplicable then (design inv. #17: absence is a value, and a card that is honestly
#: not measured never pretends to carry fields it has nothing to put in). This scene measures
#: every card this file's fixes touch; the few capital sub-cards it does NOT wire up real data
#: for (trading_lab/btc/basis/treasury/sherlock/oracle — independently confirmed conformant by
#: the round-2 review against the real production tree, see the task's own verification command)
#: fall back to this, honest, envelope-only shape — which is exactly what `unknown()` emits, so
#: there is nothing extra to check there.
_UNMEASURED_LIKE = {"NOT_MEASURED", "STALE", "CORRUPT"}
_CELL_ENVELOPE = {"value", "display_ru", "display_en", "metric_type", "state", "as_of", "canon",
                  "freshness", "unknown_ru", "unknown_en"}


def _kind(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "dict"
    return type(v).__name__


def _assert_walk(fixture, real, path):
    """Every leaf key path present in *fixture* must exist in *real* with a compatible kind
    (dict/list/str/number/null) — ``null`` on EITHER side is always compatible: absence is itself
    a valid value (inv. #17), and a fixture literal is an EXAMPLE value, not a pinned one."""
    if isinstance(fixture, dict):
        assert isinstance(real, dict), f"{path}: expected a dict, real={real!r}"
        keys = fixture.keys()
        if real.get("state") in _UNMEASURED_LIKE and fixture.get("state") not in _UNMEASURED_LIKE:
            keys = [k for k in keys if k in _CELL_ENVELOPE]  # see _UNMEASURED_LIKE docstring above
        for k in keys:
            assert k in real, f"missing key: {path}.{k}"
            _assert_walk(fixture[k], real[k], f"{path}.{k}")
    elif isinstance(fixture, list):
        if not fixture:
            return  # an empty example list declares no shape to check
        assert isinstance(real, list), f"{path}: expected a list, real={real!r}"
        if real:
            _assert_walk(fixture[0], real[0], f"{path}[0]")
    else:
        fk, rk = _kind(fixture), _kind(real)
        assert fk is None or rk is None or fk == rk, f"{path}: fixture kind={fk} real kind={rk} (fixture={fixture!r} real={real!r})"


def _w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _card(fm: dict) -> dict:
    return {"fm": fm, "trail": [], "body": "", "path": None}


def _full_scene(tmp_path: Path) -> ct.TruthInputs:
    """A scene realistic enough that every card this file's fixes touch (home/studio/product/
    decisions) comes back MEASURED/MEASURED_ZERO/NOT_ENOUGH_HISTORY — exercising the actual bare
    fields each renderer reads, not just the always-present §2.0 envelope."""
    repo, mirror, data = tmp_path / "repo", tmp_path / "mirror", tmp_path / "repo" / "data"
    now_iso = NOW.strftime(ISO)

    # ── memory index (studio.memory) — a tiny hand-built sqlite db, no real build() needed ──
    (repo / "data" / "memory").mkdir(parents=True)
    con = sqlite3.connect(repo / "data" / "memory" / "index.db")
    con.execute("CREATE TABLE chunks (path TEXT, body TEXT)")
    con.execute("INSERT INTO chunks VALUES (?, ?)", ("docs/decisions/ADR-0005-x.md", "text"))
    con.commit()
    con.close()
    (mirror / "docs" / "decisions").mkdir(parents=True)
    (mirror / "docs" / "decisions" / "ADR-0005-x.md").write_text("x", encoding="utf-8")
    (mirror / "docs" / "decisions" / "ADR-0008-y.md").write_text("y", encoding="utf-8")  # lag = 3 > 0

    # ── manifest / roles / agent_health / launchctl (studio.fleet, self_heal/backups/machine SLOs) ──
    (repo / "architecture").mkdir(parents=True)
    _w(repo / "architecture" / "manifest.json", {"agents": [
        {"label": "com.spa.agent_one", "intent": "active", "schedule": "daemon", "produces": []},
        {"label": "com.spa.agent_two", "intent": "active", "schedule": "interval", "produces": []},
    ]})
    _w(repo / "architecture" / "roles.json", {"roles": [{"role_id": "x", "implemented": True}]})
    _w(data / "agent_health.json", {"agents": [
        {"label": "com.spa.agent_one", "status": "OK"}, {"label": "com.spa.agent_two", "status": "OK"}]})
    launchctl_map = {"com.spa.agent_one": {}, "com.spa.agent_two": {}}

    # ── equity curve (home.yield / capital.defi.books.conservative) ──
    _w(data / "equity_curve_daily.json", {"generated_at": now_iso, "bars": [
        {"date": "2026-10-04", "equity": 100000, "evidenced": True, "drawdown_pct": 0.0},
        {"date": "2026-10-05", "equity": 100500, "evidenced": True, "drawdown_pct": -0.1},
    ]})
    # ── hy/lp sleeve books present but under REPORTABLE_AFTER=30 days — NOT_ENOUGH_HISTORY with
    #    a bare `accumulating_days`, matching the fixture's balanced/aggressive rows exactly ──
    sleeve_doc = {"daily_history": [{"economics_model": "sleeve-econ-v2", "equity": 100000,
                                     "positions_count": 1}]}
    _w(data / "hy_paper_trading.json", sleeve_doc)
    _w(data / "lp_paper_trading.json", sleeve_doc)

    # ── site freshness + readiness scopes (home.product / studio.scopes / capital.readiness) ──
    _w(data / "site_freshness_report.json", {"site_as_of": "06.10", "fails": []})
    scopes = [
        {"scope": "INVESTMENT_ENGINE_READINESS", "status": "NOT_READY", "as_of": now_iso,
         "source": "x", "freshness": {}, "reason": "GoLive 29/29 инвентарь пройден; custody не готов",
         "blocking_effect": "Блокирует переход на реальные деньги. Не блокирует бумажную торговлю."},
        {"scope": "STUDIO_OS_HEALTH", "status": "OK", "as_of": now_iso, "source": "x", "freshness": {},
         "reason": "86 из 92 агентов в норме", "blocking_effect": "Ничего не блокирует. Не блокирует паблик сайт."},
        {"scope": "PRODUCT_DATA_HEALTH", "status": "OK", "as_of": now_iso, "source": "x", "freshness": {},
         "reason": "учёт сходится", "blocking_effect": "Ничего не блокирует. Не блокирует деньги."},
        {"scope": "PUBLICATION_HEALTH", "status": "OK", "as_of": now_iso, "source": "x", "freshness": {},
         "reason": "сайт свежий", "blocking_effect": "Ничего не блокирует. Не блокирует флот."},
        {"scope": "OWNER_CONTROL_HEALTH", "status": "OK", "as_of": now_iso, "source": "x", "freshness": {},
         "reason": "бот отвечает", "blocking_effect": "Ничего не блокирует. Не блокирует сайт."},
        {"scope": "PUBLIC_SURFACE", "status": "OK", "as_of": now_iso, "source": "x", "freshness": {},
         "reason": "сайт честен", "blocking_effect": "Ничего не блокирует. Не блокирует флот."},
    ]

    # ── resource health (studio.machine — NOT wired before this fix) ──
    _w(data / "resource_health.json", {"generated_at": now_iso, "disk": {"free_gb": 400}})

    # ── problems (studio.problems.items / home.attention "problem") ──
    _w(data / "problems.json", {"generated_at": now_iso, "problems": {
        "k1": {"problem_id": "p1", "agent": "novel_edge_rnd", "cause_code": "module_not_found",
               "status": "OPEN", "occurrences": 6, "rca": None,
               "detail": "падает при старте: модуль не найден", "last_seen": now_iso}}})

    # ── backups: three honest facts (studio.backups.local/off_host/recovery) ──
    (data / "backups").mkdir()
    (data / "backups" / "spa_state_a.tar.gz").write_bytes(b"x")
    import os
    os.utime(data / "backups" / "spa_state_a.tar.gz", (NOW.timestamp(), NOW.timestamp()))
    _w(data / "dr_offsite_status.json", {"verified": True, "is_real_remote": False, "last_offsite_ts": now_iso})
    _w(data / "resilience_status.json", {"restore_drill": {"all_ok": True, "stale": False,
                                                            "never_run": False, "last_ts": now_iso}})
    _w(data / "self_heal_status.json", {"ts": now_iso, "healthy": True, "failures": []})
    _w(data / "current_positions.json", {"cash_usd": 100000})

    # ── tasks/releases/incidents (direct TruthInputs — not read from a file) ──
    board = {"counts": {"new": 2, "backlog": 1, "in-progress": 3, "blocked": 1}}
    orphans = {"counts": {"stale_in_progress": 1}}
    release_feed = {"items": [{"release": "IN_PROD_TREE", "at": now_iso}]}
    push_state_section = {"open": [{"event": "telegram_bot_down", "since": "05.10"}]}
    roadmap = {"items": [{"epic": "RM-TRUTH-01", "state": "IN_PROGRESS"}],
              "current": {"epic": "RM-TRUTH-01"}, "confirmed": "02.10"}

    # ── decisions triage (decisions.groups / studio.decisions_summary / home.needs) ──
    cards = {
        "owner-decision-a.md": _card({"type": "owner-decision", "status": "needs-owner",
                                      "subject": "MONEY", "title": "Про деньги"}),
        "needs-owner-etherscan.md": _card({"status": "needs-owner",
                                           "title": "Добавить ключ Etherscan на сервер"}),
        "owner-decision-c.md": _card({"type": "owner-decision", "status": "owner-accepted",
                                      "title": "Принято"}),
        "inbox-site-faq.md": _card({"status": "backlog", "domain": "site", "title": "Обновить FAQ"}),
    }

    return ct.TruthInputs(
        data=data, mirror=mirror, repo=repo, now=NOW, measure_host=False,
        rep={"claude_sessions": 0}, capital={"real_capital": {"state": "LIVE_NOT_APPROVED"}},
        cards=cards, prod_cards=None, roadmap=roadmap, board=board, orphans=orphans,
        manifest=json.loads((repo / "architecture" / "manifest.json").read_text(encoding="utf-8")),
        roles=json.loads((repo / "architecture" / "roles.json").read_text(encoding="utf-8")),
        launchctl_map=launchctl_map, lineage_fn=None, log_rows=[], log_bad_lines=0,
        scopes=scopes, release_feed=release_feed, push_state_section=push_state_section,
        old_owner_items=[{"days": 9, "title": "Добавить ключ Etherscan на сервер"}],
        decisions_v1=None,
    )


def test_real_company_truth_matches_every_fixture_leaf_for_a_realistic_scene(tmp_path):
    real = ct.build(_full_scene(tmp_path))
    for area in ("home", "capital", "studio", "product", "decisions"):
        _assert_walk(FIXTURE[area], real[area], area)


def test_real_company_truth_matches_the_fixture_on_the_real_production_tree():
    """The companion, read-only check this task's own verification command runs: the SAME walk,
    against the ACTUAL `~/Documents/SPA_Claude` tree, so capital sub-cards this file's synthetic
    scene above does not wire real data for (trading_lab/btc/basis/treasury/sherlock/oracle) are
    also checked where production happens to have them measured. Best-effort: a dev machine or CI
    box without that tree skips, it never counts as a pass."""
    import pytest
    from spa_core.studio_os import mission_control as mc
    repo = Path.home() / "Documents" / "SPA_Claude"
    if not (repo / "data").is_dir():
        pytest.skip("NOT MEASURED: ~/Documents/SPA_Claude is not present on this machine")
    # measure_host=False: a read-only shape check has no business running real `ps`/`launchctl`
    # probes against the live host — it only needs the JSON/tracker files mc.build() already
    # knows how to assemble into TruthInputs.
    m = mc.build(mc.MCInputs(repo=repo, measure_host=False))
    real = m["truth"]
    # Capital included: the one real-data drift this walk surfaced (`capital.sherlock.total` was
    # the factory's `reviewed_today` FLAG printed as a count) is fixed in company_truth — a flag
    # is not a number, so the count is the third outcome (None) until the source names one.
    for area in ("home", "capital", "studio", "product", "decisions"):
        _assert_walk(FIXTURE[area], real[area], area)


# ── studio.memory: never claim "знает все решения" while lag > 0 ────────────────────────────────
def test_memory_card_never_claims_it_knows_everything_while_it_is_lagging(tmp_path):
    """Round-2 review, 2026-10-06: ``cell.lag`` lived only inside ``value``, so
    ``renderMemory``'s own ``cell.lag > 0 ? … : t("studio.memory.ok")`` ternary always took the
    "знает все решения" branch — even while the index was 30 ADRs behind. Two guards: the bare
    field is now the SAME number the computation used, and the card carries no pre-composed
    sentence a renderer could show ALONGSIDE the bare-field one (§2.0's "two kinds of text")."""
    repo, mirror = tmp_path / "repo", tmp_path / "mirror"
    (repo / "data" / "memory").mkdir(parents=True)
    (repo / "architecture").mkdir(parents=True)
    con = sqlite3.connect(repo / "data" / "memory" / "index.db")
    con.execute("CREATE TABLE chunks (path TEXT, body TEXT)")
    con.execute("INSERT INTO chunks VALUES (?, ?)", ("docs/decisions/ADR-0005-x.md", "text"))
    con.commit()
    con.close()
    (mirror / "docs" / "decisions").mkdir(parents=True)
    (mirror / "docs" / "decisions" / "ADR-0005-x.md").write_text("x", encoding="utf-8")
    (mirror / "docs" / "decisions" / "ADR-0030-y.md").write_text("y", encoding="utf-8")
    cell = ct.studio_memory(repo, mirror)
    assert cell["lag"] == cell["value"]["lag"] == 25
    assert cell["lag"] > 0
    assert cell["display_ru"] is None and cell["display_en"] is None  # nothing to contradict it


def test_memory_card_at_zero_lag_is_also_a_bare_field_not_just_a_sentence(tmp_path):
    repo, mirror = tmp_path / "repo", tmp_path / "mirror"
    (repo / "data" / "memory").mkdir(parents=True)
    (repo / "architecture").mkdir(parents=True)
    con = sqlite3.connect(repo / "data" / "memory" / "index.db")
    con.execute("CREATE TABLE chunks (path TEXT, body TEXT)")
    con.execute("INSERT INTO chunks VALUES (?, ?)", ("docs/decisions/ADR-0005-x.md", "text"))
    con.commit()
    con.close()
    (mirror / "docs" / "decisions").mkdir(parents=True)
    (mirror / "docs" / "decisions" / "ADR-0005-x.md").write_text("x", encoding="utf-8")
    cell = ct.studio_memory(repo, mirror)
    assert cell["lag"] == 0
    assert cell["state"] == ct.MEASURED_ZERO


# ── studio.backups: the UI-facing rename (local_backup/off_host_backup/recovery_tested →
#    local/off_host/recovery) — the computation's own names stay intact and independently
#    tested by test_backups_three_facts.py; only the re-projection changed. ──────────────────────
def test_studio_backups_are_exposed_under_the_names_the_renderer_reads(tmp_path):
    scene = _full_scene(tmp_path)
    real = ct.build(scene)
    b = real["studio"]["backups"]
    assert set(b) >= {"local", "off_host", "recovery"}
    assert "local_backup" not in b and "off_host_backup" not in b and "recovery_tested" not in b
    assert b["local"]["state"] in (ct.MEASURED, ct.STALE)
    assert b["off_host"]["is_real_remote"] is False and b["off_host"]["state"] == ct.MEASURED_ZERO


# ── product.public_metrics: an ARRAY, not a cell wrapping one ───────────────────────────────────
def test_public_metrics_is_a_plain_array_array_isarray_true(tmp_path):
    mirror = tmp_path / "mirror"
    _w(mirror / "landing" / "src" / "data" / "site_numbers.json", {
        "measured_at": "2026-10-05T00:00:00Z",
        "headline": {"apy": {"value": 4.9, "unit": "%", "source": "x"},
                    "evidenced_days": {"value": 100, "unit": "дней"}},
    })
    rows = ct.product_public_metrics(mirror)
    assert isinstance(rows, list) and len(rows) == 2
    for row in rows:
        assert row["state"] == ct.MEASURED
        assert isinstance(row["label_ru"], str) and isinstance(row["value_ru"], str)


def test_public_metrics_absent_is_an_empty_array_never_a_crash(tmp_path):
    assert ct.product_public_metrics(tmp_path / "no-mirror-here") == []
