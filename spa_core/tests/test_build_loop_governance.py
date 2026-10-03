"""ADR-551 — Build Loop v1, agent output governance, resource guardrails.

Every guard here has a positive control (it fires on the real failure shape) and a negative control
(it stays quiet on the healthy shape). Times are relative (no literal dates) and process liveness is
injected (no literal pids) — .claude/rules/deployment.md.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.monitoring import resource_cleanup as rc
from spa_core.monitoring import resource_guard as rg
from spa_core.owner_queue import queue as Q
from spa_core.studio_os import build_loop as bl
from spa_core.studio_os import orphans as orph
from spa_core.studio_os import provenance as prov
from spa_core.utils import heavy_job as hj

REPO = Path(__file__).resolve().parents[2]
GB = 1024 ** 3


# ── Phase 1: lifecycle ───────────────────────────────────────────────────────

class TestLifecycle:
    def test_transition_table_is_the_one_vocabulary(self):
        assert Q.CARD_STATUSES == frozenset(Q.CARD_TRANSITIONS)
        for src, dsts in Q.CARD_TRANSITIONS.items():
            assert dsts <= Q.CARD_STATUSES, src

    def test_unknown_status_is_refused(self):
        with pytest.raises(Q.LifecycleRefused):
            Q.check_lifecycle("inbox", "new", "closed")

    def test_disallowed_transition_is_refused(self):
        with pytest.raises(Q.LifecycleRefused):
            Q.check_lifecycle("inbox", "done", "owner-done", closed_by="a", evidence="b")

    def test_done_without_evidence_is_refused_and_with_evidence_allowed(self):
        with pytest.raises(Q.LifecycleRefused):
            Q.check_lifecycle("inbox", "in-progress", "done")
        Q.check_lifecycle("inbox", "in-progress", "done", closed_by="agent", evidence="probe satisfied")

    def test_a_carrier_closes_without_evidence(self):
        Q.check_lifecycle("inbox", "new", "done", carried=True)

    def test_owner_decision_needs_the_owners_recorded_answer(self):
        with pytest.raises(Q.LifecycleRefused):
            Q.check_lifecycle("owner-decision", "needs-owner", "owner-done", fm={}, closed_by="a", evidence="b")
        Q.check_lifecycle("owner-decision", "needs-owner", "owner-done", fm={"owner_choice": "да"},
                          closed_by="a", evidence="b")
        Q.check_lifecycle("owner-decision", "owner-accepted", "owner-done", fm={}, closed_by="a", evidence="b")

    def test_the_owners_own_status_in_the_trail_is_an_answer(self):
        owner = [{"old": "needs-owner", "new": "owner-done", "source": "telegram.answer"}]
        Q.check_lifecycle("owner-decision", "ingested", "owner-done", fm={"status_trail_items": owner},
                          closed_by="a", evidence="b")
        agent = [{"old": "needs-owner", "new": "owner-done", "source": "queue.set_status/closed_by:agent/evidence:x"}]
        with pytest.raises(Q.LifecycleRefused):
            Q.check_lifecycle("owner-decision", "ingested", "owner-done", fm={"status_trail_items": agent},
                              closed_by="a", evidence="b")

    def test_answers_given_in_nimbalyst_write_no_trail_and_still_count(self, tmp_path):
        # owner sets owner-accepted by hand → agent takes it into work → agent closes with evidence
        c = Q.create_card("owner-decision", "поручение", "b", status="needs-owner", tracker_dir=tmp_path)
        c.write_text(c.read_text(encoding="utf-8").replace("status: needs-owner", "status: owner-accepted"), encoding="utf-8")
        Q.set_status(c, "in-progress")
        Q.set_status(c, "owner-done", closed_by="agent", evidence="criterion checked")
        # owner sets owner-done by hand → agent ingests → agent may close the ingested card
        d = Q.create_card("owner-decision", "выбор", "b", status="needs-owner", tracker_dir=tmp_path)
        d.write_text(d.read_text(encoding="utf-8").replace("status: needs-owner", "status: owner-done"), encoding="utf-8")
        Q.set_status(d, "ingested")
        Q.set_status(d, "done", closed_by="agent", evidence="answer carried")

    def test_a_session_id_cannot_forge_the_owners_word(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPA_SESSION_ID", "x -> owner-done")
        c = Q.create_card("owner-decision", "подделка", "b", status="needs-owner", tracker_dir=tmp_path)
        Q.set_status(c, "backlog")
        with pytest.raises(Q.LifecycleRefused):
            Q.set_status(c, "done", closed_by="agent", evidence="whatever")

    def test_the_bridge_retracts_its_own_untouched_question_and_nobody_else_can(self, tmp_path):
        Q.check_lifecycle("owner-decision", "needs-owner", "done", fm={"finding_key": "k1"},
                          closed_by="findings_bridge", evidence="finding k1 absent")
        with pytest.raises(Q.LifecycleRefused):       # any other agent
            Q.check_lifecycle("owner-decision", "needs-owner", "done", fm={"finding_key": "k1"},
                              closed_by="random_agent", evidence="whatever")
        with pytest.raises(Q.LifecycleRefused):       # a card somebody already moved
            Q.check_lifecycle("owner-decision", "needs-owner", "done",
                              fm={"finding_key": "k1", "status_trail_items": [{"old": "x", "new": "needs-owner", "source": "s"}]},
                              closed_by="findings_bridge", evidence="x")
        with pytest.raises(Q.LifecycleRefused):       # never owner-done
            Q.check_lifecycle("owner-decision", "needs-owner", "owner-done", fm={"finding_key": "k1"},
                              closed_by="findings_bridge", evidence="x")

    def test_a_legacy_top_level_type_is_still_an_owner_decision(self, tmp_path):
        p = tmp_path / "own-99-legacy.md"
        p.write_text("---\ntype: owner-decision\ntitle: x\nstatus: ingested\n---\n\nb\n", encoding="utf-8")
        with pytest.raises(Q.LifecycleRefused):
            Q.set_status(p, "done", closed_by="agent", evidence="whatever")

    def test_a_misrouted_owner_card_can_be_demoted_to_the_agents_queue(self):
        Q.check_lifecycle("owner-decision", "needs-owner", "backlog")

    def test_legacy_status_is_not_judged_so_a_dead_letter_stays_repairable(self):
        Q.check_lifecycle("inbox", None, "backlog")
        Q.check_lifecycle("inbox", "legacy-weird", "backlog")

    def test_cli_closes_with_evidence_and_refuses_without(self, tmp_path):
        card = Q.create_card("agent-task", "проба цикла", "тело", status="in-progress", tracker_dir=tmp_path)
        env = dict(os.environ, SPA_TRACKER_DIR=str(tmp_path), PYTHONPATH=str(REPO))
        cmd = [sys.executable, str(REPO / "scripts" / "orchestrator_queue.py"), "set-status", str(card), "done"]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(REPO))
        assert r.returncode == 2 and "REFUSED" in r.stderr and "evidence" in r.stderr
        r = subprocess.run(cmd + ["--closed-by", "test", "--evidence", "probe satisfied"],
                           capture_output=True, text=True, env=env, cwd=str(REPO))
        assert r.returncode == 0, r.stderr
        text = card.read_text(encoding="utf-8")
        assert "status: done" in text and "evidence:probe satisfied" in text


# ── Phase 2: provenance ──────────────────────────────────────────────────────

def _git(repo: Path, *args, env=None):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", **(env or {})})


def _scene_repo(tmp_path: Path, main: str = "main") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", main)
    (repo / "page.astro").write_text("<div id=\"calc-slider\"></div>\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "M3: yield calculator\n\nCo-Authored-By: Claude Test <noreply@example.com>")
    (repo / "page.astro").write_text("<div id=\"calc-slider\"></div>\n<p>scenario</p>\n", encoding="utf-8")
    _git(repo, "commit", "-am", "ADR-900: scenario block (cycle #42)")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


class TestProvenance:
    def test_registry_is_well_formed(self):
        reg = prov.load_registry()
        ids = [a["id"] for a in reg["artifacts"]]
        assert len(ids) == len(set(ids))
        for a in reg["artifacts"]:
            for k in ("purpose", "purpose_source", "source_task", "source_decision", "producer_role",
                      "producer_run", "reviewer", "owner_role", "status", "anchors"):
                assert a.get(k) not in (None, ""), (a["id"], k)
            assert a["status"] in prov.STATUSES, a["id"]
            for anc in a["anchors"]:
                path = anc.split("#")[0]
                if not path.startswith("data/"):
                    assert (REPO / path).exists(), (a["id"], path)

    def test_removal_is_never_a_plain_yes(self):
        for st in prov.STATUSES:
            for cons in ([], ["x"]):
                for kind in ("site-page", "guard"):
                    v = prov.removal_verdict({"status": st, "consumers": cons, "kind": kind})["may_remove"]
                    assert v in ("NO", "ONLY_WITH_CHANGE_RECORD", "ONLY_WITH_CHANGE_RECORD_AND_OWNER"), (st, cons, kind)

    def test_unknown_purpose_is_not_obsolete(self):
        x = prov.explain("landing/src/pages/does-not-exist-anywhere.astro", root=REPO)
        assert x["record"]["status"] == "UNKNOWN_PURPOSE"
        assert x["removal"]["may_remove"] == "NO" and "UNKNOWN is not OBSOLETE" in x["removal"]["why"]

    def test_git_facts_name_what_history_carries_and_nothing_more(self, tmp_path):
        repo = _scene_repo(tmp_path)
        g = prov.git_facts("page.astro", root=repo, marker="calc-slider")
        assert g["state"] == "MEASURED"
        assert g["first"]["subject"].startswith("M3") and g["first_basis"].startswith("content")
        assert g["last"]["subject"].startswith("ADR-900")
        assert g["adrs"] == ["ADR-900"] and g["models"] == ["Claude Test"] and g["cycles"] == ["42"]
        assert g["sessions"] == [], "no session id in history ⇒ none reported, never invented"

    def test_release_is_measured_against_the_production_commit(self, tmp_path):
        repo = _scene_repo(tmp_path)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        dd = tmp_path / "data"
        dd.mkdir()
        (dd / "code_sync_status.json").write_text(json.dumps({"origin_main": head, "timestamp": "t", "result": "IN_SYNC"}), encoding="utf-8")
        assert prov.release_of(head[:9], root=repo, data_dir=dd)["state"] == "RELEASED"
        first = subprocess.run(["git", "-C", str(repo), "rev-list", "--max-parents=0", "HEAD"],
                               capture_output=True, text=True).stdout.strip()
        (dd / "code_sync_status.json").write_text(json.dumps({"origin_main": first, "timestamp": "t", "result": "IN_SYNC"}), encoding="utf-8")
        assert prov.release_of(head[:9], root=repo, data_dir=dd)["state"] == "ON_MAIN_NOT_SYNCED"

    def test_release_without_production_evidence_is_not_released(self, tmp_path):
        repo = _scene_repo(tmp_path)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        empty = tmp_path / "nodata"
        empty.mkdir()
        assert prov.release_of(head[:9], root=repo, data_dir=empty)["state"] == "ON_MAIN_PRODUCTION_UNKNOWN"
        assert prov.release_of("deadbeef0", root=repo, data_dir=empty)["state"] == "UNKNOWN", \
            "a git error is not «not released»"

    def test_a_failed_code_sync_is_not_production_evidence(self, tmp_path):
        repo = _scene_repo(tmp_path)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        dd = tmp_path / "data"
        dd.mkdir()
        for result, want in (("CHECKOUT_FAILED", "ON_MAIN_PRODUCTION_UNKNOWN"), ("ROLLED_BACK", "ON_MAIN_PRODUCTION_UNKNOWN"),
                             ("IN_SYNC", "RELEASED"), ("SYNCED", "RELEASED")):
            (dd / "code_sync_status.json").write_text(json.dumps({"origin_main": head, "result": result}), encoding="utf-8")
            assert prov.release_of(head[:9], root=repo, data_dir=dd)["state"] == want, result

    def test_manifest_fallback_resolves_a_fleet_data_artifact(self, tmp_path):
        man = tmp_path / "manifest.json"
        man.write_text(json.dumps({"agents": [{"label": "com.spa.x", "role": "analytics",
                                               "governed_by": ["ADR-1"], "passport": {"goal": "measure x"}}],
                                   "artifacts": [{"path": "data/x.json", "producer": "com.spa.x",
                                                  "consumers": ["api"], "status": "active"}]}), encoding="utf-8")
        m = prov.manifest_artifact("data/x.json", manifest_path=man)
        assert m["agent"]["passport"]["goal"] == "measure x"


# ── Scenario A: the calculator, reconstructed by a fresh reader ─────────────

class TestScenarioACalculator:
    def test_why_who_owns_and_may_it_go(self):
        x = prov.explain("site.calculator", root=REPO)
        r = x["record"]
        assert "M3" in r["purpose_source"] and "b7a822194" in r["purpose_source"]
        assert "ADR-548" in r["source_decision"] and r["owner_role"] == "owner"
        assert r["producer_run"].startswith("UNKNOWN"), "the producing session is not provable — say so"
        assert x["removal"]["may_remove"] == "NO"

    def test_the_element_id_resolves_to_the_same_record(self):
        assert prov.find_record("calc-slider")["id"] == "site.calculator"
        assert prov.find_record("landing/src/pages/index.astro#calc-slider")["id"] == "site.calculator"


# ── Scenario B: an existing creative role produces a harmless artifact ──────

class TestScenarioBSupervisedOutput:
    def test_cmo_draft_gets_provenance_and_review_state(self, tmp_path):
        from spa_core.cmo import editorial_agent
        from spa_core.cmo.draft_store import DraftStore
        ledger = tmp_path / "track_ledger.json"
        ledger.write_text(json.dumps({"n_evidenced_days": 3, "days_needed": 30}), encoding="utf-8")
        drafts = tmp_path / "data" / "cmo_drafts"
        res = editorial_agent.run(drafts_dir=drafts, ledger_path=ledger, decisions_path=tmp_path / "none.jsonl")
        assert res["created"] is True, res
        sv = orph.supervise(tmp_path / "data")["roles"]["marketing"]
        item = sv["items"][-1]
        assert item["producer_role"] == "marketing" and item["producer"] == "com.spa.cmo_editorial"
        assert item["disposition"] == "NEEDS_REVIEW", "an output nobody looked at is never «fine»"
        assert item["provenance"].endswith("marketing.cmo_drafts")
        store = DraftStore(drafts)
        store.approve(res["draft_id"])
        sv2 = orph.supervise(tmp_path / "data")["roles"]["marketing"]
        assert sv2["items"][-1]["disposition"] == "ACCEPTED_NOT_RELEASED"
        assert "no publisher" in (sv2["finding"] or "")


# ── Scenario C: an orphan is detected and NOT deleted ───────────────────────

class TestScenarioCOrphan:
    def test_page_without_lineage_is_reported_and_kept(self, tmp_path):
        repo = tmp_path / "repo"
        pages = repo / "landing" / "src" / "pages"
        pages.mkdir(parents=True)
        _git(repo, "init", "-b", "main")
        orphan = pages / "orphan-page.astro"
        orphan.write_text("<h1>who made me?</h1>\n", encoding="utf-8")
        known = pages / "known.astro"
        known.write_text("<h1>known</h1>\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add pages")
        reg = {"artifacts": [{"id": "k", "anchors": ["landing/src/pages/known.astro"]}]}
        found = orph.pages_without_lineage(repo, reg)
        names = [f["artifact"] for f in found]
        assert names == ["landing/src/pages/orphan-page.astro"]
        assert found[0]["removal_risk"].startswith("HIGH") and "do not remove" in found[0]["recommended_action"]
        assert orphan.exists(), "the report deletes nothing"

    def test_a_page_whose_history_names_a_decision_is_not_an_orphan(self, tmp_path):
        repo = tmp_path / "repo"
        pages = repo / "landing" / "src" / "pages"
        pages.mkdir(parents=True)
        _git(repo, "init", "-b", "main")
        (pages / "decided.astro").write_text("<h1>x</h1>\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "ADR-900: decided page")
        assert orph.pages_without_lineage(repo, {"artifacts": []}) == []

    def test_stale_in_progress_card_is_reported(self, tmp_path):
        c = Q.create_card("agent-task", "застрявшая", "тело", status="in-progress", tracker_dir=tmp_path)
        old = time.time() - 30 * 86400
        os.utime(c, (old, old))
        found = orph.stale_cards(tmp_path)
        assert [f["artifact"] for f in found] == [c.name]
        assert orph.stale_cards(tmp_path, now=old + 86400) == []


# ── Scenario D: resource pressure, simulated ────────────────────────────────

def _policy(tmp_path: Path) -> dict:
    p = rg.load_policy()
    p = json.loads(json.dumps(p))
    p["disk"]["reserve_path"] = str(tmp_path / "reserve.bin")
    p["disk"]["reserve_gb"] = 0.0001
    return p


class TestScenarioDPressure:
    def test_disk_thresholds(self, tmp_path):
        pol = _policy(tmp_path)
        du = lambda free: (lambda _p: SimpleNamespace(free=free * GB, total=460 * GB))
        assert rg.measure_disk(pol, disk_usage=du(100))["state"] == rg.OK
        assert rg.measure_disk(pol, disk_usage=du(30))["state"] == rg.WARN
        assert rg.measure_disk(pol, disk_usage=du(5))["state"] == rg.CRITICAL

        def boom(_p):
            raise OSError("volume gone")
        assert rg.measure_disk(pol, disk_usage=boom)["state"] == rg.UNMEASURED

    def test_memory_pressure_and_swap(self, tmp_path):
        pol = _policy(tmp_path)

        def run_with(level, swap):
            return lambda cmd, **k: level if "pressure" in cmd[-1] else swap
        sw = "total = 3072,00M  used = {u}M  free = 1M  (encrypted)"
        assert rg.measure_memory(pol, run=run_with("1", sw.format(u="1000,00")))["state"] == rg.OK
        assert rg.measure_memory(pol, run=run_with("2", sw.format(u="1000,00")))["state"] == rg.WARN
        assert rg.measure_memory(pol, run=run_with("4", sw.format(u="1000,00")))["state"] == rg.CRITICAL
        assert rg.measure_memory(pol, run=run_with("1", sw.format(u="3050,00")))["state"] == rg.CRITICAL
        assert rg.measure_memory(pol, run=lambda c, **k: None)["state"] == rg.UNMEASURED

    def test_a_blind_guard_is_not_fine_and_alerts(self, tmp_path):
        pol = _policy(tmp_path)

        def boom(_p):
            raise OSError("volume gone")
        rep = rg.build_report(pol, disk_usage=boom,
                              run=lambda cmd, **k: "1" if "pressure" in cmd[-1] else
                              ("total = 3072,00M  used = 10,00M  free = 1M" if "swap" in cmd[-1] else None))
        assert rep["overall"] == rg.UNMEASURED
        rg.notify(rep, data_dir=tmp_path, send=False)
        state = (tmp_path / "telegram" / "push_state.json").read_text(encoding="utf-8")
        assert "unmeasured:disk" in state
        assert max((rg.UNMEASURED, rg.CRITICAL), key=lambda s: rg._RANK[s]) == rg.CRITICAL
        assert max((rg.WARN, rg.UNMEASURED), key=lambda s: rg._RANK[s]) == rg.UNMEASURED

    def test_reserve_is_released_at_critical_and_rebuilt_when_healthy(self, tmp_path):
        pol = _policy(tmp_path)
        assert rg.manage_reserve({"state": rg.OK}, pol)["action"] == "created"
        assert (tmp_path / "reserve.bin").exists()
        assert rg.manage_reserve({"state": rg.WARN}, pol)["action"] == "kept"
        assert rg.manage_reserve({"state": rg.CRITICAL}, pol)["action"] == "released"
        assert not (tmp_path / "reserve.bin").exists()
        assert rg.manage_reserve({"state": rg.WARN}, pol)["action"] == "absent", "no flapping below OK"

    def test_critical_alerts_once_and_resolves(self, tmp_path):
        crit = {"overall": rg.CRITICAL, "disk": {"state": rg.CRITICAL, "free_gb": 5.0},
                "memory": {"state": rg.OK, "pressure_level": 1, "swap": {"used_pct": 10.0}}}
        ok = {"overall": rg.OK, "disk": {"state": rg.OK, "free_gb": 90.0},
              "memory": {"state": rg.OK, "pressure_level": 1, "swap": {"used_pct": 10.0}}}
        from spa_core.telegram import push_policy
        assert "resource_critical" in push_policy.TIER1_WHITELIST
        rg.notify(crit, data_dir=tmp_path, send=False)
        state = json.loads((tmp_path / "telegram" / "push_state.json").read_text(encoding="utf-8"))
        assert "resource_critical" in json.dumps(state)
        rg.notify(ok, data_dir=tmp_path, send=False)

    def test_classification_protects_critical_and_slows_only_disposable(self, tmp_path):
        pol = _policy(tmp_path)
        assert rg.classify("python3 -m spa_core.paper_trading.hy_cycle --run", "com.spa.hy_cycle", pol) == "CRITICAL"
        assert rg.classify("python3 -m pytest spa_core/tests", "com.spa.hy_cycle", pol) == "CRITICAL"
        assert rg.classify("python3 -m pytest spa_core/tests", "com.spa.orchestrator", pol) == "DISPOSABLE"
        assert rg.classify("/x/claude -p do", None, pol) == "DISPOSABLE"
        assert rg.classify("bash agent_orchestrator.sh", "com.spa.orchestrator", pol) == "IMPORTANT"
        calls = []
        rep = {"memory": {"state": rg.WARN},
               "processes": {"disposable": [{"pid": 1234567, "cmd": "pytest"}]}}
        acted = rg.protect(rep, pol, setpriority=lambda w, p, n: calls.append((p, n)), getpriority=lambda w, p: 0)
        assert calls == [(1234567, pol["heavy_jobs"]["nice"])] and acted[0]["nice"] == "0->10"
        assert rg.protect({"memory": {"state": rg.OK}, "processes": {"disposable": [{"pid": 1, "cmd": "x"}]}},
                          pol, setpriority=lambda *a: calls.append(a)) == []


# ── Scenario E: a known disposable old setup is identified and safely cleaned ─

class TestScenarioECleanup:
    def test_only_allow_listed_and_expired_is_removed(self, tmp_path):
        root = tmp_path / "T"
        root.mkdir()
        old = time.time() - 72 * 3600
        stand = root / "g17_abandoned"
        (stand / "data").mkdir(parents=True)
        (stand / "data" / "x.json").write_text("{}" * 1000, encoding="utf-8")
        young = root / "g18_running"
        young.mkdir()
        foreign = root / "keep_me_unknown"
        foreign.mkdir()
        target = tmp_path / "precious"
        target.mkdir()
        (root / "g17_link").symlink_to(target)
        for p in (stand, stand / "data", stand / "data" / "x.json", foreign):
            os.utime(p, (old, old))
        pol = {"cleanup": {"disposable_dirs": [{"root": str(root), "prefixes": ["g17_", "g18_"], "ttl_hours": 24}],
                           "never_touch": [str(target)], "max_deletions_per_run": 100}}
        cands = rg.cleanup_candidates(pol)
        assert [Path(c["path"]).name for c in cands] == ["g17_abandoned"] and cands[0]["bytes"] > 0
        log = tmp_path / "log.jsonl"
        done = rg.apply_cleanup(cands, pol, log_path=log)
        assert done[0]["removed"] and not stand.exists()
        assert young.exists() and foreign.exists() and target.exists() and (root / "g17_link").is_symlink()
        assert json.loads(log.read_text().splitlines()[0])["path"].endswith("g17_abandoned")

    def test_age_is_the_newest_entry_not_the_top_level_mtime(self, tmp_path):
        root = tmp_path / "T"
        live = root / "g17_live" / "deep" / "deeper"
        live.mkdir(parents=True)
        (live / "x.json").write_text("{}", encoding="utf-8")       # written NOW, deep inside
        old = time.time() - 72 * 3600
        for p in (root / "g17_live", root / "g17_live" / "deep"):
            os.utime(p, (old, old))
        pol = {"cleanup": {"disposable_dirs": [{"root": str(root), "prefixes": ["g17_"], "ttl_hours": 24}],
                           "never_touch": [], "max_deletions_per_run": 100}}
        assert rg.cleanup_candidates(pol) == [], "a sandbox written deep inside is alive"

    def test_an_unresolvable_root_is_not_measured_not_clean(self, tmp_path):
        pol = {"cleanup": {"disposable_dirs": [{"root": "$USER_TEMP", "prefixes": ["g17_"], "ttl_hours": 24}],
                           "never_touch": [], "max_deletions_per_run": 1}}
        um: list = []
        import spa_core.monitoring.resource_guard as mod
        orig = mod.expand_root
        mod.expand_root = lambda r: None
        try:
            assert rg.cleanup_candidates(pol, unmeasured=um) == []
        finally:
            mod.expand_root = orig
        assert um and um[0]["root"] == "$USER_TEMP"

    def test_user_temp_root_is_asked_of_the_os_not_the_environment(self, monkeypatch):
        monkeypatch.delenv("TMPDIR", raising=False)
        assert rg.user_temp_root(run=lambda cmd, **k: "/var/folders/xx/T/\n") == "/var/folders/xx/T"

    def test_a_stand_too_large_to_age_is_kept_and_named(self, tmp_path, monkeypatch):
        root = tmp_path / "T"
        (root / "g17_huge").mkdir(parents=True)
        old = time.time() - 72 * 3600
        os.utime(root / "g17_huge", (old, old))
        monkeypatch.setattr(rg, "_newest_mtime", lambda p, cap_entries=0: None)
        pol = {"cleanup": {"disposable_dirs": [{"root": str(root), "prefixes": ["g17_"], "ttl_hours": 24}],
                           "never_touch": [], "max_deletions_per_run": 100}}
        um: list = []
        assert rg.cleanup_candidates(pol, unmeasured=um) == []
        assert um and "kept" in um[0]["reason"]

    def test_the_five_minute_path_never_walks_deep(self, tmp_path, monkeypatch):
        root = tmp_path / "T"
        (root / "g17_x").mkdir(parents=True)
        old = time.time() - 72 * 3600
        os.utime(root / "g17_x", (old, old))

        def boom(*a, **k):
            raise AssertionError("deep walk on the 5-minute path")
        monkeypatch.setattr(rg, "_newest_mtime", boom)
        pol = {"cleanup": {"disposable_dirs": [{"root": str(root), "prefixes": ["g17_"], "ttl_hours": 24}],
                           "never_touch": [], "max_deletions_per_run": 100}}
        assert len(rg.cleanup_candidates(pol, sizes=False, deep=False)) == 1

    def test_never_touch_wins_over_the_allow_list(self, tmp_path):
        root = tmp_path / "T"
        (root / "g17_x").mkdir(parents=True)
        old = time.time() - 72 * 3600
        os.utime(root / "g17_x", (old, old))
        pol = {"cleanup": {"disposable_dirs": [{"root": str(root), "prefixes": ["g17_"], "ttl_hours": 1}],
                           "never_touch": [str(root)], "max_deletions_per_run": 100}}
        assert rg.cleanup_candidates(pol) == []

    def test_the_real_policy_never_targets_canonical_trees(self):
        pol = rg.load_policy()
        roots = {rg.expand_root(r["root"]) for r in pol["cleanup"]["disposable_dirs"]}
        for t in pol["cleanup"]["never_touch"]:
            assert os.path.realpath(t) not in {os.path.realpath(r) for r in roots if r}
        for r in pol["cleanup"]["disposable_dirs"]:
            assert all(len(p) >= 4 for p in r["prefixes"]), "a short prefix would match too much"

    def test_maintenance_reports_without_reaping_in_a_sandbox(self, tmp_path, monkeypatch):
        pol = {"cleanup": {"disposable_dirs": [], "never_touch": [], "max_deletions_per_run": 1}}
        res = rc.run(data_dir=tmp_path, policy=pol, reap=False, orphans=False)
        assert res["disposable_removed"] == 0


# ── Scenario F: two workers never mutate the same tree ──────────────────────

def _hpol(tmp_path: Path, cap: int = 2) -> dict:
    return {"registry_dir": str(tmp_path / "leases"), "max_concurrent": {"full_suite": cap, "default": 3},
            "full_suite_min_tests": 2000, "min_free_disk_gb": 20, "refuse_at_pressure_level": 4, "nice": 10}


_ROOMY = lambda _p: SimpleNamespace(free=200 * GB, total=460 * GB)  # noqa: E731


class TestScenarioFConcurrency:
    def test_same_tree_refused_other_tree_admitted(self, tmp_path):
        pol = _hpol(tmp_path)
        a = hj.admit("full_suite", str(tmp_path), pid=os.getpid(), policy=pol, disk_usage=_ROOMY,
                     pressure=lambda: 1, renice=False)
        with pytest.raises(hj.AdmissionRefused, match="already held"):
            hj.admit("full_suite", str(tmp_path), pid=os.getppid(), policy=pol, disk_usage=_ROOMY,
                     pressure=lambda: 1, renice=False)
        other = tmp_path / "other"
        other.mkdir()
        b = hj.admit("full_suite", str(other), pid=os.getppid(), policy=pol, disk_usage=_ROOMY,
                     pressure=lambda: 1, renice=False)
        a.release()
        b.release()
        assert hj.live_leases(pol) == []

    def test_cap_disk_and_pressure_refuse(self, tmp_path):
        pol = _hpol(tmp_path, cap=1)
        lease = hj.admit("full_suite", str(tmp_path / "a"), pid=os.getpid(), policy=pol, disk_usage=_ROOMY,
                         pressure=lambda: 1, renice=False)
        with pytest.raises(hj.AdmissionRefused, match="cap 1"):
            hj.admit("full_suite", str(tmp_path / "b"), pid=os.getppid(), policy=pol, disk_usage=_ROOMY,
                     pressure=lambda: 1, renice=False)
        lease.release()
        with pytest.raises(hj.AdmissionRefused, match="free disk"):
            hj.admit("full_suite", str(tmp_path), policy=pol, pressure=lambda: 1, renice=False,
                     disk_usage=lambda _p: SimpleNamespace(free=5 * GB, total=460 * GB))
        with pytest.raises(hj.AdmissionRefused, match="pressure"):
            hj.admit("full_suite", str(tmp_path), policy=pol, disk_usage=_ROOMY, pressure=lambda: 4, renice=False)

    def test_a_dead_holder_does_not_block(self, tmp_path):
        pol = _hpol(tmp_path)
        hj.admit("full_suite", str(tmp_path), pid=os.getpid(), policy=pol, disk_usage=_ROOMY,
                 pressure=lambda: 1, renice=False)
        b = hj.admit("full_suite", str(tmp_path), pid=os.getppid(), policy=pol, disk_usage=_ROOMY,
                     pressure=lambda: 1, renice=False, alive=lambda pid: pid != os.getpid())
        assert b.tree == os.path.realpath(str(tmp_path))

    def test_six_real_processes_race_for_one_tree_exactly_one_wins(self, tmp_path):
        reg = tmp_path / "leases"
        tree = tmp_path / "tree"
        tree.mkdir()
        code = (
            "import json,sys,time;from types import SimpleNamespace as S;from spa_core.utils import heavy_job as h;"
            f"p={{'registry_dir':{str(reg)!r},'max_concurrent':{{'full_suite':5,'default':5}},'full_suite_min_tests':1,"
            "'min_free_disk_gb':0,'refuse_at_pressure_level':99,'nice':10}\n"
            "try:\n"
            f"  l=h.admit('full_suite',{str(tree)!r},policy=p,pressure=lambda:1,renice=False,"
            "disk_usage=lambda _:S(free=10**12,total=10**12));print('WON');sys.stdout.flush();time.sleep(2)\n"
            "except h.AdmissionRefused as e:\n  print('REFUSED')\n")
        env = dict(os.environ, PYTHONPATH=str(REPO))
        procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=env, cwd=str(REPO))
                 for _ in range(6)]
        outs = [p.communicate(timeout=60)[0].strip() for p in procs]
        assert outs.count("WON") == 1 and outs.count("REFUSED") == 5, outs

    def test_plugin_engages_only_for_full_local_runs(self, monkeypatch):
        from spa_core.utils import pytest_heavy_admission as plug
        monkeypatch.setattr(sys, "platform", "darwin")
        for v in ("SPA_HEAVY_LEASE", "SPA_HEAVY_ADMISSION", "CI", "GITHUB_ACTIONS", "PYTEST_XDIST_WORKER"):
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv("SPA_ENV", "ci")
        assert plug._engaged(5000, 2000), "the PRESCRIBED local command (SPA_ENV=ci) must take a lease"
        assert not plug._engaged(100, 2000)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert not plug._engaged(5000, 2000), "a CI runner is its own machine"
        monkeypatch.delenv("GITHUB_ACTIONS")
        monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
        assert not plug._engaged(5000, 2000), "an xdist worker is not the job"
        monkeypatch.delenv("PYTEST_XDIST_WORKER")
        monkeypatch.setenv("SPA_HEAVY_LEASE", "/x")
        assert not plug._engaged(5000, 2000), "a nested run inherits its parent's lease"
        assert plug.REFUSED_EXIT == 75, "not pytest's 4 (usage error)"

    def test_a_reused_pid_is_not_the_holder_and_stale_leases_are_pruned(self, tmp_path):
        pol = _hpol(tmp_path)
        hj.admit("full_suite", str(tmp_path), pid=os.getpid(), policy=pol, disk_usage=_ROOMY,
                 pressure=lambda: 1, renice=False, started=lambda pid: "Mon Jan  1 00:00:00 2001")
        assert len(hj.live_leases(pol, started=lambda pid: "Mon Jan  1 00:00:00 2001")) == 1
        # same pid, different start time ⇒ another process now owns the number
        assert hj.live_leases(pol, started=lambda pid: "Tue Jan  2 00:00:00 2001") == []
        assert list((tmp_path / "leases").glob("*.json")) == [], "a stale lease is removed"

    def test_garbage_and_zero_pid_leases_are_dead(self, tmp_path):
        pol = _hpol(tmp_path)
        d = tmp_path / "leases"
        d.mkdir()
        (d / "a.json").write_text(json.dumps({"kind": "full_suite", "tree": "/x", "pid": 0}), encoding="utf-8")
        (d / "b.json").write_text(json.dumps({"kind": "full_suite", "tree": "/x", "pid": "nope"}), encoding="utf-8")
        assert hj.live_leases(pol) == []
        assert not hj.pid_alive(0) and not hj.pid_alive(-1)


# ── Scenario G: a fresh reader reconstructs a completed task's full lineage ──

class TestScenarioGLineage:
    def test_every_stage_from_files_alone(self, tmp_path):
        tdir = tmp_path / "tracker"
        tdir.mkdir()
        card = Q.create_card("agent-task", "собрать отчёт", "ADR-900 решил", status="in-progress",
                             source="owner telegram /task", tracker_dir=tdir)
        Q.set_status(card, "done", closed_by="agent", evidence="report regenerated, 12 passed")
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        (repo / "x.txt").write_text("x", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", f"fix: {card.stem} (ADR-900) — reverse control red without the fix")
        _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        dd = tmp_path / "data"
        dd.mkdir()
        (dd / "code_sync_status.json").write_text(json.dumps({"origin_main": head, "timestamp": "t", "result": "IN_SYNC"}), encoding="utf-8")
        x = bl.lineage(card.stem, tdir=tdir, root=repo, data_dir=dd, memory=False)
        st = {k: v["state"] for k, v in x["stages"].items()}
        for s in ("IDEA", "ASSIGNED", "RUN", "ARTIFACT", "REVIEW", "DECISION", "RELEASE", "OUTCOME"):
            assert st[s] == "DONE", (s, x["stages"][s])
        assert st["TASK"] == "MISSING", "no acceptance criterion declared — the lineage says so"
        assert "ADR-900" in x["stages"]["DECISION"]["evidence"]["adrs"]

    def test_a_card_without_a_source_has_an_unknown_idea(self, tmp_path):
        c = Q.create_card("agent-task", "без источника", "тело", status="in-progress", tracker_dir=tmp_path)
        x = bl.lineage(c.stem, tdir=tmp_path, root=tmp_path, memory=False)
        assert x["stages"]["IDEA"]["state"] == "UNKNOWN"

    def test_a_slug_prefix_is_not_the_card(self, tmp_path):
        tdir = tmp_path / "tracker"
        tdir.mkdir()
        card = Q.create_card("agent-task", "x", "b", status="in-progress", source="s", tracker_dir=tdir)
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        (repo / "x.txt").write_text("x", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", f"work on {card.stem}-2 (another card)")
        _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        x = bl.lineage(card.stem, tdir=tdir, root=repo, data_dir=tmp_path, memory=False)
        assert x["stages"]["ARTIFACT"]["state"] == "MISSING"

    def test_unknown_card_is_named_not_invented(self, tmp_path):
        x = bl.lineage("no-such-card", tdir=tmp_path, memory=False)
        assert x["state"] == "NOT_FOUND"

    def test_board_separates_active_blocked_and_owner_gates(self, tmp_path):
        Q.create_card("agent-task", "a", "b", status="in-progress", tracker_dir=tmp_path)
        Q.create_card("agent-task", "c", "d", status="blocked", tracker_dir=tmp_path)
        Q.create_card("owner-decision", "e", "f", status="needs-owner", tracker_dir=tmp_path)
        b = bl.board(tmp_path)
        assert (len(b["active"]), len(b["blocked"]), len(b["owner_gates"])) == (1, 1, 1)


# ── Phase 3: the governance holes the audit found stay closed ───────────────

class TestGovernanceHoles:
    def test_rnd_agent_declares_itself_autonomous_and_is_governed(self):
        s = (REPO / "scripts" / "agent_novel_edge_rnd.sh").read_text(encoding="utf-8")
        assert "export SPA_AUTONOMOUS=1" in s
        assert "claude_run_with_timeout.py" in s and "--label novel_edge_rnd" in s

    def test_autopush_runs_only_allow_listed_scripts(self, tmp_path):
        s = (REPO / "scripts" / "auto_push.sh").read_text(encoding="utf-8")
        assert "auto_push_allowlist.txt" in s and "REFUSED" in s
        allow = (REPO / "scripts" / "auto_push_allowlist.txt").read_text(encoding="utf-8")
        assert [ln for ln in allow.splitlines() if ln.strip() and not ln.startswith("#")] == []

    def test_build_loop_runners_start_below_critical_priority(self):
        for name in ("agent_orchestrator.sh", "agent_novel_edge_rnd.sh"):
            assert "nice -n 10" in (REPO / "scripts" / name).read_text(encoding="utf-8"), name
