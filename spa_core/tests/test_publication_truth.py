"""PRODUCT-TRUTH-02 (ADR-630): one product mapping, one cadence, a typed and verified publication artifact.

Each scene is a failure the audit of 2026-10-07 found or the epic named (§9), with its positive control:
the verifier must be RED on the broken artifact and GREEN on the honest one, so a «PASS» means something.
"""
# FROZEN-DATE-OK: the dates ARE the subject — the 2026-10-01 / 10-05 / 10-08 / 10-12 publication-cadence
# scene of the audit; every reader gets them as inputs (today=/now=/published_at=), no wall clock.
from __future__ import annotations

import copy
import datetime
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.publication import cadence, metric_types as mt, product_map

ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bsn = _load("_bsn_pt02", "scripts/build_site_numbers.py")
vp = _load("_vp_pt02", "scripts/verify_publication.py")
mon = _load("_mon_pt02", "scripts/site_freshness_monitor.py")

PS = {"generated_at": "2026-10-07T06:00:00Z", "packages": {
    "conservative": {"experiment_id": "conservative-lending-v1@2026-06-22", "experiment_start_date": "2026-06-22",
                     "history": {"valid_periods": 106}},
    "balanced": {"experiment_id": "balanced-fixed-carry-v1@2026-10-02", "history": {"valid_periods": 6}},
    "aggressive": {"experiment_id": "aggressive-susde-loop-v1@2026-10-02", "history": {"valid_periods": 6}},
}}
SNAP = {
    "as_of": "2026-10-07", "generated_at": "2026-10-07T06:00:00Z", "real_track_days": 106,
    "evidenced_anchor": "2026-06-22", "paper_apy_pct": 4.8943, "max_drawdown_pct": -0.0393, "nav_usd": 101538.0,
    "gates_passed": 29, "gates_total": 29, "go_live_state": "gate_passed_owner_decision_pending",
    "packages": {"conservative": {"apy_pct": 3.7, "dd_pct": -1.2}},
    "paper_tracks": {
        "conservative": {"status": "paper_test_running", "days_with_positions": 106, "apy_pct": 4.89,
                         "dd_pct": -0.0393, "nav_usd": 101538.0, "evidence": "paper",
                         "observed_accrual_since": "2026-06-22"},
        # 6 bars, annualised, and the snapshot says NOTHING about maturity — the defect class D6
        "balanced": {"status": "paper_test_running", "days_with_positions": 6, "apy_pct": -3.58,
                     "dd_pct": -0.31, "nav_usd": 99950.0, "evidence": "paper", "observed_accrual_since": "2026-10-02"},
        "aggressive": {"status": "paper_test_running", "days_with_positions": 6, "apy_pct": 7.02,
                       "dd_pct": -0.15, "nav_usd": 100100.0, "evidence": "paper", "observed_accrual_since": "2026-10-02"},
    },
    "package_status": PS,
}
CONST = {
    "kill_switch": {"soft_derisk_pct": 5.0, "hard_kill_pct": 10.0},
    "chain_caps": {"single_chain_pct": 90.0, "l2_total_pct": 50.0, "base_chain_pct": 20.0},
    "start_capital_usd": 100000.0, "min_cash_buffer_pct": 5.0,
    "max_per_protocol_t1_pct": 40.0, "max_per_protocol_t2_pct": 20.0,
    "max_t2_total_pct": 50.0, "tvl_floor_usd": 5000000, "apy_floor_pct": 1.0,
    "apy_ceiling_pct": 30.0, "min_paper_days_before_live": 30,
}
TODAY = "2026-10-07"


class _Scene(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="spa_pt02_"))
        self._s, self._c = bsn.SNAPSHOT, bsn.CONSTITUTION
        bsn.SNAPSHOT = self.d / "track_snapshot.json"
        bsn.CONSTITUTION = self.d / "constitution.json"
        bsn.SNAPSHOT.write_text(json.dumps(SNAP), encoding="utf-8")
        bsn.CONSTITUTION.write_text(json.dumps(CONST), encoding="utf-8")

    def tearDown(self):
        bsn.SNAPSHOT, bsn.CONSTITUTION = self._s, self._c
        shutil.rmtree(self.d, ignore_errors=True)

    def shelf(self, published_at=TODAY):
        return bsn.build(published_at=published_at)

    def put(self, doc, name="cand.json"):
        p = self.d / name
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return p

    def verify(self, doc, *, published="default", today=TODAY, approval=None, pages=None):
        if published == "default":   # an honest copy of the same shelf is what the public sees
            published = self.put(self.shelf(doc.get("published_at") or TODAY), "published_default.json")
        return vp.verify(shelf=self.put(doc), published=published, today=today, approval=approval,
                         pages=pages, bsn=bsn)

    def approval_card(self, doc, status="owner-done", line=None):
        cand = self.put(doc)
        line = line or vp.approval_line(doc, bsn._sha256(cand))
        card = self.d / "own-publish.md"
        card.write_text(f"---\nstatus: {status}\napproves: landing/src/data/site_numbers.json\n---\n{line}\n",
                        encoding="utf-8")
        return str(card)


# ── 1. the mapping ────────────────────────────────────────────────────────────────────────────────
class TheMappingIsExplicit(unittest.TestCase):
    def test_public_names_internal_books_and_track_starts(self):
        rows = {r["profile"]: r for r in product_map.checked(PS)}
        self.assertEqual([rows[k]["public_name"] for k in ("conservative", "balanced", "aggressive")],
                         ["Conservative", "Balanced", "Aggressive"])
        self.assertEqual(rows["conservative"]["internal_book"], "conservative-lending-v1")
        self.assertEqual(rows["conservative"]["track_start"], "2026-06-22")
        # ADR-533 is dated 10-01, the books say 10-02 — both kept, the track starts where the book says
        self.assertEqual(rows["balanced"]["track_start"], "2026-10-02")
        self.assertEqual(rows["balanced"]["decision_date"], "2026-10-01")
        self.assertEqual(rows["conservative"]["maturity"], "REPORTABLE")
        self.assertEqual(rows["balanced"]["maturity"], "ACCUMULATING")
        self.assertIsNone(rows["balanced"]["result_metric_type"])
        self.assertEqual(rows["conservative"]["naming_decision"], "ADR-OWN-2026-07")

    def test_historical_names_carry_no_history(self):
        for r in product_map.build(PS):
            self.assertIn("no paper history", r["historical_name_note"])
            self.assertNotIn(r["historical_name"], ("Conservative", "Balanced", "Aggressive"))

    def test_a_book_that_does_not_match_the_decision_is_a_conflict(self):
        bad = copy.deepcopy(PS)
        bad["packages"]["balanced"]["experiment_id"] = "conservative-lending-v1@2026-06-22"
        with self.assertRaises(product_map.MappingConflict):
            product_map.checked(bad)

    def test_names_come_from_tier_bands_and_dates_from_the_adr_headers(self):
        """Review P1-4: no hand-typed copy — a renamed tier in tier_bands.json renames the row."""
        from spa_core.studio_os.memory.continuity import adr_effective
        bands = json.loads((ROOT / "landing" / "src" / "lib" / "tier_bands.json").read_text(encoding="utf-8"))
        rows = {r["profile"]: r for r in product_map.build(PS)}
        for k in ("conservative", "balanced", "aggressive"):
            self.assertEqual(rows[k]["public_name"], bands[k]["en"])
            self.assertEqual(rows[k]["historical_name"], bands[k]["alt_en"])
            adr = sorted((ROOT / "docs" / "decisions").glob(f"{rows[k]['deciding_adr']}-*.md"))[0]
            self.assertEqual(rows[k]["decision_date"], adr_effective(adr.read_text(encoding="utf-8")))
        renamed = copy.deepcopy(bands)
        renamed["balanced"]["en"] = "Steady"
        self.assertEqual(product_map.build(PS, tier_bands=renamed)[1]["public_name"], "Steady")
        self.assertNotIn("track_source", rows["balanced"])
        self.assertEqual(rows["balanced"]["book_file"], "data/hy_paper_trading.json")

    def test_conservative_track_start_must_equal_the_snapshots_anchor(self):
        with self.assertRaises(product_map.MappingConflict):
            product_map.checked(PS, evidenced_anchor="2026-07-01")
        self.assertEqual(product_map.checked(PS, evidenced_anchor="2026-06-22")[0]["evidenced_anchor"], "2026-06-22")

    def test_unreadable_status_is_unknown_not_a_number(self):
        rows = product_map.checked(None)
        self.assertTrue(all(r["maturity"] == "UNKNOWN" and r["valid_periods"] is None for r in rows))


# ── 2. the typed artifact ─────────────────────────────────────────────────────────────────────────
class TheArtifactIsTypedAndReproducible(_Scene):
    def test_every_return_is_typed_and_backtest_is_labelled(self):
        doc = self.shelf()
        self.assertEqual(doc["headline"]["apy"]["metric_type"], mt.REALIZED_PAPER_RETURN)
        self.assertEqual(doc["packages"]["conservative"]["apy"]["metric_type"], mt.BACKTEST_RETURN)
        self.assertEqual(doc["packages"]["conservative"]["drawdown"]["basis"], mt.BACKTEST)
        self.assertEqual(doc["headline"]["drawdown"]["basis"], mt.PAPER)

    def test_a_short_history_is_an_observation_with_no_value(self):
        b = self.shelf()["books"]["balanced"]["apy"]
        self.assertEqual(b["metric_type"], mt.OBSERVED_RETURN)
        self.assertIsNone(b["value"])
        self.assertFalse(b["reportable"])

    def test_provenance_binds_the_inputs(self):
        prov = self.shelf()["_provenance"]
        self.assertEqual(prov["schema_version"], bsn.SCHEMA_VERSION)
        self.assertEqual(prov["measurement_as_of"], "2026-10-07")
        self.assertEqual(set(prov["source_hashes"]),
                         {"landing/src/data/track_snapshot.json", "landing/src/lib/constitution.json"})

    def test_two_builds_from_the_same_inputs_are_byte_identical(self):
        a = json.dumps(self.shelf(), ensure_ascii=False, indent=2)
        b = json.dumps(self.shelf(), ensure_ascii=False, indent=2)
        self.assertEqual(a, b)

    def test_the_mapping_rides_in_the_artifact(self):
        self.assertEqual([r["profile"] for r in self.shelf()["profiles"]], ["conservative", "balanced", "aggressive"])


# ── 3. one cadence, every reader ──────────────────────────────────────────────────────────────────
class OneCadenceForEveryReader(_Scene):
    """Audit 2026-10-07: origin published 10-01 (next 10-08); the Mac built 10-05 (next 10-12) and never
    shipped it. Every reader must answer 10-08 — the rule over the PUBLISHED shelf."""

    def setUp(self):
        super().setUp()
        self.origin = self.shelf("2026-10-01")
        self.local = self.shelf("2026-10-05")
        self.mirror = self.d / "mirror"
        (self.mirror / "landing" / "src" / "data").mkdir(parents=True)
        self.origin_path = self.mirror / "landing" / "src" / "data" / "site_numbers.json"
        self.origin_path.write_text(json.dumps(self.origin), encoding="utf-8")
        (self.mirror / "landing" / "src" / "data" / "track_snapshot.json").write_text(json.dumps(SNAP))
        self.local_path = self.put(self.local, "local_site_numbers.json")

    def test_all_readers_give_the_same_next_date(self):
        rule = cadence.status(self.origin, today="2026-10-08")["next_publication"]
        # Director's cell is checked in test_company_truth_publication.py (ADR-580 C4 import ratchet)
        report = mon.evaluate(snapshot=SNAP, home_html="", track_html="", api={}, sitemap_statuses={},
                              verifier_sha=None, pin_sha=None,
                              now=datetime.datetime(2026, 10, 10, 6, 0, tzinfo=datetime.timezone.utc),
                              site_numbers=self.origin, local_site_numbers=self.local)
        self.assertEqual(rule, "2026-10-08")
        self.assertEqual(report["shelf_next_publication"], "2026-10-08")
        self.assertTrue(report["shelf_built_not_delivered"])
        self.assertIn("SHELF_NOT_DELIVERED", [f["code"] for f in report["fails"]])

    def test_the_builder_judges_due_by_the_published_copy(self):
        due, _ = bsn.publication_due(today="2026-10-08", published=self.origin_path)
        self.assertTrue(due)
        # the old operand (the unshipped local copy) would have said «not due until 10-12»
        stale_due, _ = bsn.publication_due(today="2026-10-08", out=self.local_path)
        self.assertFalse(stale_due)

    def test_a_declared_date_that_breaks_the_rule_is_named(self):
        bad = dict(self.origin, next_publication="2026-10-12")
        st = cadence.status(bad, today="2026-10-08")
        self.assertEqual(st["next_publication"], "2026-10-08")
        self.assertIn("declared_conflict", st)

    def test_the_monitor_uses_the_shared_operand_not_the_fetched_shelf(self):
        """Review P1-3: one operand for the date — the resolver's copy wins over whatever else was fetched."""
        report = mon.evaluate(snapshot=SNAP, home_html="", track_html="", api={}, sitemap_statuses={},
                              verifier_sha=None, pin_sha=None,
                              now=datetime.datetime(2026, 10, 10, 6, 0, tzinfo=datetime.timezone.utc),
                              site_numbers=self.local, published_shelf=self.origin,
                              published_shelf_leg="measured")
        self.assertEqual(report["shelf_next_publication"], "2026-10-08")
        self.assertEqual(report["cadence_operand_leg"], "measured")

    def test_no_mirror_means_not_measured_never_the_local_copy(self):
        """Review P1-3: without a published operand the builder refuses (exit 2) instead of judging the
        week by the unshipped file it wrote itself."""
        import os
        from unittest import mock
        with mock.patch.object(cadence, "DEFAULT_MIRROR", self.d / "no-mirror"), \
                mock.patch.dict(os.environ, {"SPA_PUBLISHED_SHELF": ""}):
            self.assertIsNone(cadence.published_shelf_path())
            with self.assertRaises(bsn.NotMeasured):
                bsn.run(published_at="2026-10-08", if_due=True, write=False)

    def test_a_built_but_undelivered_shelf_is_not_rebuilt_every_day(self):
        """Review P1-3: while delivery is refused the builder must not turn weekly into daily retries."""
        # the public shelf is still the old schema ⇒ the new candidate needs the owner ⇒ it waits
        v1 = dict(self.origin)
        v1["_provenance"] = dict(v1["_provenance"], schema_version="site_numbers/1")
        self.origin_path.write_text(json.dumps(v1), encoding="utf-8")
        before = self.local_path.read_bytes()
        out = bsn.run(published_at="2026-10-09", if_due=True, out=self.local_path, published=self.origin_path)
        self.assertFalse(out["published"])
        self.assertTrue(out["not_delivered"])
        self.assertIn("SHELF_NOT_DELIVERED", out["reason"])
        self.assertEqual(self.local_path.read_bytes(), before)

    def test_unreadable_published_shelf_is_not_measured(self):
        st = cadence.status(None, today="2026-10-08")
        self.assertFalse(st["measured"])
        self.assertIsNone(st["next_publication"])


# ── 4. the verifier: positive control + one scene per epic §9 failure ─────────────────────────────
class TheVerifierFailsClosed(_Scene):
    def test_an_honest_artifact_passes(self):
        doc = self.shelf()
        res = self.verify(doc, published=self.put(doc, "published.json"))
        self.assertEqual(res["outcome"], vp.PASS, res["findings"])

    def _fails_with(self, doc, needle, **kw):
        res = self.verify(doc, **kw)
        self.assertEqual(res["outcome"], vp.FAIL, res)
        self.assertTrue(any(needle in f for f in res["findings"]), (needle, res["findings"]))

    def test_stale_artifact_schema(self):
        doc = self.shelf()
        doc["_provenance"]["schema_version"] = "site_numbers/1"
        self._fails_with(doc, "stale artifact")

    def test_stale_artifact_age(self):
        doc = self.shelf()
        self._fails_with(doc, "stale publication artifact", published=self.put(doc, "p.json"), today="2026-10-15")

    def test_missing_source_is_not_measured(self):
        doc = self.shelf()
        pub = self.put(doc, "p.json")
        bsn.CONSTITUTION.unlink()
        self.assertEqual(self.verify(doc, published=pub)["outcome"], vp.NOT_MEASURED)

    def test_source_hash_mismatch(self):
        doc = self.shelf()
        bsn.SNAPSHOT.write_text(json.dumps(dict(SNAP, nav_usd=1.0)), encoding="utf-8")
        self._fails_with(doc, "source hash mismatch")

    def test_conflicting_mapping(self):
        doc = self.shelf()
        doc["profiles"][1]["internal_book"] = doc["profiles"][0]["internal_book"]
        self._fails_with(doc, "mapping:")

    def test_unknown_metric_type(self):
        doc = self.shelf()
        doc["headline"]["apy"]["metric_type"] = "APY"
        self._fails_with(doc, "without a known metric_type")

    def test_target_exposed_as_result(self):
        doc = self.shelf()
        doc["headline"]["apy"]["metric_type"] = mt.TARGET_RETURN
        self._fails_with(doc, "TARGET_RETURN carried by kind")

    def test_backtest_exposed_as_paper(self):
        doc = self.shelf()
        doc["packages"]["conservative"]["apy"]["metric_type"] = mt.REALIZED_PAPER_RETURN
        self._fails_with(doc, "BACKTEST source exposed")

    def test_backtest_drawdown_without_backtest_label(self):
        doc = self.shelf()
        doc["packages"]["conservative"]["drawdown"]["basis"] = mt.PAPER
        self._fails_with(doc, "backtest tail must say BACKTEST")

    def test_short_history_annualised_as_a_result(self):
        doc = self.shelf()
        doc["books"]["balanced"]["apy"].update(value=7.0, reportable=True, metric_type=mt.REALIZED_PAPER_RETURN)
        self._fails_with(doc, "short history annualised")

    def test_stale_measurement_date(self):
        doc = self.shelf()
        doc["measured_at"] = "2026-09-20"
        self._fails_with(doc, "stale measurement date")

    def test_cadence_conflict(self):
        doc = self.shelf()
        doc["next_publication"] = "2026-10-20"
        self._fails_with(doc, "cadence conflict")

    def test_site_numbers_differ_from_a_rebuild(self):
        doc = self.shelf()
        doc["headline"]["apy"]["value"] = 9.9
        self._fails_with(doc, "rebuild from canonical inputs")

    def test_missing_owner_approval_for_a_changed_public_decision(self):
        old = self.shelf()
        old["thresholds"]["kill_switch_soft"]["value"] = 6.0
        self._fails_with(self.shelf(), "missing owner approval", published=self.put(old, "p.json"))

    def test_an_owner_closed_card_naming_this_shelf_is_accepted(self):
        old = self.shelf()
        old["thresholds"]["kill_switch_soft"]["value"] = 6.0
        pub = self.put(old, "p.json")
        doc = self.shelf()
        self.assertEqual(self.verify(doc, published=pub, approval=self.approval_card(doc))["outcome"], vp.PASS)

    def test_an_open_card_is_not_an_approval(self):
        old = self.shelf()
        old["thresholds"]["kill_switch_soft"]["value"] = 6.0
        doc = self.shelf()
        self._fails_with(doc, "not closed by the owner", published=self.put(old, "p.json"),
                         approval=self.approval_card(doc, status="needs-owner"))

    def test_an_approval_of_another_shelf_is_refused(self):
        """Review P1-2: «any owner-done card qualifies» — the card must name THIS shelf's hash."""
        old = self.shelf()
        old["thresholds"]["kill_switch_soft"]["value"] = 6.0
        doc = self.shelf()
        other = vp.approval_line(doc, "0" * 64)
        self._fails_with(doc, "does not name this shelf", published=self.put(old, "p.json"),
                         approval=self.approval_card(doc, line=other))

    def test_a_missing_approval_file_is_a_finding_even_when_nothing_needs_it(self):
        self._fails_with(self.shelf(), "approval record not found", approval=str(self.d / "nope.md"))

    def test_null_to_value_needs_approval(self):
        """Review P1-2: a rate appearing for the first time is not a re-measurement."""
        old = self.shelf()
        old["headline"]["apy"]["value"] = None
        self._fails_with(self.shelf(), "null →", published=self.put(old, "p.json"))

    def test_first_publication_of_a_new_schema_needs_approval(self):
        """Review P1-1: site_numbers/1 → /2 is not covered by the standing weekly approval."""
        old = self.shelf()
        old["_provenance"]["schema_version"] = "site_numbers/1"
        self._fails_with(self.shelf(), "first publication of shelf schema", published=self.put(old, "p.json"))

    def test_no_published_location_is_not_measured(self):
        """Review P1-2: «published shelf unknown» is exit 2, not a FAIL and never a pass."""
        res = vp.verify(shelf=self.put(self.shelf()), published=None, today=TODAY, bsn=bsn)
        self.assertEqual(res["outcome"], vp.NOT_MEASURED)

    def test_a_remeasured_value_rides_on_the_standing_weekly_approval(self):
        old = self.shelf()
        old["headline"]["apy"]["value"] = 4.95   # same field, same type, new measurement
        res = self.verify(self.shelf(), published=self.put(old, "p.json"))
        self.assertFalse(any("approval" in f for f in res["findings"]), res["findings"])

    def test_candidate_older_than_the_live_publication(self):
        live = self.shelf("2026-10-08")
        self._fails_with(self.shelf("2026-10-07"), "older than the live publication",
                         published=self.put(live, "p.json"))

    def test_a_page_reading_a_deprecated_field(self):
        pages = self.d / "landing" / "src"
        pages.mkdir(parents=True)
        (pages / "Dash.jsx").write_text("const apy = facts?.paper_apy_pct ?? facts?.apy_today_pct ?? null;\n")
        doc = self.shelf()
        self._fails_with(doc, "deprecated field", published=self.put(doc, "p.json"), pages=pages)

    def test_every_occurrence_is_its_own_entry_and_or_fallbacks_count(self):
        """Review P2: a second offender in an already-listed file must be new; `||` is a fallback too."""
        pages = self.d / "landing" / "src"
        pages.mkdir(parents=True)
        (pages / "Dash.jsx").write_text("const a = f.paper_apy_pct ?? f.apy_today_pct;\n"
                                        "const b = f.rate || f.apy_today_pct;\n")
        self.assertEqual(len(vp.scan_pages(pages)), 2)


# ── 5. the freshness monitor judges what is PUBLISHED ─────────────────────────────────────────────
class TheMonitorJudgesThePublishedSnapshot(unittest.TestCase):
    NOW = datetime.datetime(2026, 10, 7, 6, 0, tzinfo=datetime.timezone.utc)

    def _ev(self, published_snapshot, leg=None):
        return mon.evaluate(snapshot={"as_of": "2026-10-07"}, home_html="", track_html="", api={},
                            sitemap_statuses={}, verifier_sha=None, pin_sha=None, now=self.NOW,
                            published_snapshot=published_snapshot, published_snapshot_leg=leg)

    def test_a_stuck_published_snapshot_is_red_even_when_the_local_one_is_fresh(self):
        r = self._ev({"as_of": "2026-10-02"})
        codes = [f["code"] for f in r["fails"]]
        self.assertIn("PUBLISHED_SNAPSHOT_STALE", codes)
        self.assertFalse(r["degrade_triggered"])          # alert only — degrading is a public change

    def test_a_fresh_published_snapshot_is_not_flagged(self):
        r = self._ev({"as_of": "2026-10-07"})
        self.assertNotIn("PUBLISHED_SNAPSHOT_STALE", [f["code"] for f in r["fails"]])

    def test_an_unreadable_published_snapshot_is_recorded_not_paged(self):
        r = self._ev(None, leg="unmeasured:git_unavailable:x")
        self.assertNotIn("PUBLISHED_SNAPSHOT_STALE", [f["code"] for f in r["fails"]])
        self.assertEqual(r["published_snapshot_leg"], "unmeasured:git_unavailable:x")
        self.assertIsNone(r["published_snapshot_age_h"])


# ── 7. pages: deprecated untyped reads can only shrink ────────────────────────────────────────────
BASELINE = ROOT / "scripts" / "publication_deprecated_reads_baseline.json"


class DeprecatedPageReadsRatchet(unittest.TestCase):
    """Today's landing reads a 1-day rate under mature labels (audit 2026-10-07). These are PUBLIC pages,
    so fixing them is the owner's publication gate (ADR-630), not a silent push. The base lists today's
    OCCURRENCES (file + normalised line) and may only shrink: a new one is red at once — also a second
    one in an already-listed file; a fixed one must leave the base."""

    def test_no_new_offender_and_no_stale_base_entry(self):
        base = set(json.loads(BASELINE.read_text(encoding="utf-8"))["offenders"])
        now = set(vp.scan_pages(ROOT / "landing" / "src"))
        self.assertFalse(now - base, f"new page reads of deprecated untyped fields: {sorted(now - base)}")
        self.assertFalse(base - now, f"fixed offenders still listed in the base — remove them: {sorted(base - now)}")


# ── 8. the real publisher path refuses an unapproved v2 shelf (sandbox: no network, no push) ─────
class TheOrchestratorPathRefusesAnUnapprovedShelf(unittest.TestCase):
    """Review P1-1: step (1е) = build_site_numbers --if-due → safe_site_push.py. The verifier was called by
    nobody, and the owner gate rarely matches a pretty-printed shelf. End to end in a sandbox: the shelf is
    built from the real repo inputs, the published copy is a site_numbers/1 shelf, the pusher is a stub."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="spa_pt02_e2e_"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_v2_shelf_without_owner_approval_never_reaches_the_pusher(self):
        import os
        from unittest import mock
        ssp = _load("_ssp_pt02", "scripts/safe_site_push.py")
        # the PUBLISHED copy: today's real origin shelf, schema v1 (no _provenance)
        published = self.d / "published" / "site_numbers.json"
        published.parent.mkdir(parents=True)
        today = datetime.date.today()   # the pusher's verifier judges by the wall clock; dates are relative to it
        v1 = {k: v for k, v in bsn.build(published_at=(today - datetime.timedelta(days=7)).isoformat()).items()
              if k not in ("_provenance", "profiles")}
        published.write_text(json.dumps(v1, ensure_ascii=False, indent=2), encoding="utf-8")
        # step (1е): the builder, judged by the published copy, builds the candidate into a sandbox tree
        cand = self.d / "landing" / "src" / "data" / "site_numbers.json"
        cand.parent.mkdir(parents=True)
        out = bsn.run(published_at=today.isoformat(), if_due=True, out=cand, published=published)
        self.assertTrue(out["published"], out)
        marker = self.d / "PUSHED"
        stub = self.d / "stub_push.py"
        stub.write_text(f"open({str(marker)!r}, 'w').write('pushed')\n", encoding="utf-8")
        cards = []
        with mock.patch.dict(os.environ, {"SPA_PUBLISHED_SHELF": str(published)}), \
                mock.patch.object(ssp, "_BATCH", stub), \
                mock.patch.object(ssp, "_find_publication_approval", lambda shelf: None), \
                mock.patch.object(ssp, "_route_to_owner_card",
                                  lambda files, report, msg, extra_lines=None: cards.append((report, extra_lines)) or True):
            rc = ssp.main(["--files", str(cand), "-m", "chore(site numbers): weekly shelf"])
        self.assertEqual(rc, 2)
        self.assertFalse(marker.exists(), "the pusher ran — an unapproved v2 shelf reached origin")
        self.assertEqual(len(cards), 1)
        texts = " ".join(v["matched_text"] for v in cards[0][0]["violations"])
        self.assertIn("first publication of shelf schema", texts)
        self.assertTrue(any(str(x).startswith("publication-approves: landing/src/data/site_numbers.json")
                            for x in cards[0][1]), "the card must carry the exact approval line")


if __name__ == "__main__":
    unittest.main()


# ── 9. re-review: interlocks on both pushers, recorded inputs, the retry after owner-done ─────────
class BothPushersRunThePublicationGate(unittest.TestCase):
    """Re-review (A): a direct push of the shelf (not via safe_site_push) must meet the same gate."""

    def test_a_direct_push_of_an_unverified_shelf_is_blocked_by_either_pusher(self):
        import os
        import subprocess
        import sys
        d = Path(tempfile.mkdtemp(prefix="spa_pt02_push_"))
        try:
            shelf = d / "landing" / "src" / "data" / "site_numbers.json"
            shelf.parent.mkdir(parents=True)
            shelf.write_text('{"published_at": "2026-10-07"}', encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != "SPA_SITE_PUSH_VERIFIED"}
            env.update(SPA_PUSH_ALLOW_CHANGE_EVIDENCE_UNMEASURED="1", SPA_PUBLISHED_SHELF=str(shelf))
            for pusher in ("push_to_github.py", "push_to_github_batch.py"):
                cp = subprocess.run([sys.executable, str(ROOT / pusher), "--files", str(shelf),
                                     "--message", "x", "--pat", "dummy"],
                                    capture_output=True, text=True, env=env, timeout=120)
                self.assertEqual(cp.returncode, 3, (pusher, cp.stdout[-400:], cp.stderr[-400:]))
                self.assertIn("publication gate", cp.stderr)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TheApprovedShelfVerifiesAgainstItsOwnInputs(_Scene):
    """Re-review (B): a shelf approved days after its build must verify against the inputs it was built
    from (preserved by hash), not against today's regenerated snapshot."""

    def test_recorded_inputs_survive_a_changed_snapshot(self):
        cand = self.d / "landing" / "src" / "data" / "site_numbers.json"
        cand.parent.mkdir(parents=True)
        bsn.run(published_at=TODAY, write=True, out=cand)
        bsn.SNAPSHOT.write_text(json.dumps(dict(SNAP, nav_usd=1.0)), encoding="utf-8")   # the day moved on
        doc = json.loads(cand.read_text(encoding="utf-8"))
        res = vp.verify(shelf=cand, published=self.put(doc, "pub.json"), today=TODAY, bsn=bsn)
        self.assertEqual(res["outcome"], vp.PASS, res["findings"])

    def test_without_the_preserved_copy_the_mismatch_is_named(self):
        cand = self.d / "landing" / "src" / "data" / "site_numbers.json"
        cand.parent.mkdir(parents=True)
        bsn.run(published_at=TODAY, write=True, out=cand)
        shutil.rmtree(cand.parent / ".publication_inputs")
        bsn.SNAPSHOT.write_text(json.dumps(dict(SNAP, nav_usd=1.0)), encoding="utf-8")
        doc = json.loads(cand.read_text(encoding="utf-8"))
        res = vp.verify(shelf=cand, published=self.put(doc, "pub.json"), today=TODAY, bsn=bsn)
        self.assertTrue(any("not preserved" in f for f in res["findings"]), res)

    def test_a_measurement_older_than_a_cadence_is_stale_however_approved(self):
        doc = self.shelf()
        self.assertTrue(any("stale measurement" in f for f in
                            self.verify(doc, today="2026-10-20")["findings"]))

    def test_an_unclearable_candidate_is_superseded_once_not_waited_on_forever(self):
        published = self.put(dict(self.shelf("2026-09-20"), published_at="2026-09-20"), "pub.json")
        cand = self.d / "landing" / "src" / "data" / "site_numbers.json"
        cand.parent.mkdir(parents=True)
        bsn.run(published_at="2026-10-05", write=True, out=cand)
        shutil.rmtree(cand.parent / ".publication_inputs")                     # inputs lost
        bsn.SNAPSHOT.write_text(json.dumps(dict(SNAP, nav_usd=1.0)), encoding="utf-8")
        old = cand.read_bytes()
        out = bsn.run(published_at=TODAY, if_due=True, out=cand, published=published)
        self.assertTrue(out["published"], out)
        self.assertNotEqual(cand.read_bytes(), old)
        log = (cand.parent / ".publication_inputs" / "superseded.jsonl").read_text(encoding="utf-8")
        self.assertIn("sha256", log)


class BuildRefuseApprovePush(unittest.TestCase):
    """Re-review (B): the whole loop in a sandbox — step (1е) builds, the gate refuses (owner card), the
    owner closes the card with the exact line, the NEXT run of the same step pushes. No network: the
    batch pusher is a stub that leaves a marker; the owner-gate linter is stubbed (separate gate)."""

    def test_build_refuse_approve_push(self):
        import os
        from unittest import mock
        d = Path(tempfile.mkdtemp(prefix="spa_pt02_loop_"))
        try:
            today = datetime.date.today()          # the pusher's gate judges by the wall clock
            snap_p, const_p = d / "track_snapshot.json", d / "constitution.json"
            snap_p.write_text(json.dumps(dict(SNAP, as_of=today.isoformat())), encoding="utf-8")
            const_p.write_text(json.dumps(CONST), encoding="utf-8")
            pub = d / "published" / "site_numbers.json"
            pub.parent.mkdir(parents=True)
            tracker = d / "tracker"
            tracker.mkdir()
            cand = d / "landing" / "src" / "data" / "site_numbers.json"
            cand.parent.mkdir(parents=True)
            marker = d / "PUSHED"
            stub = d / "stub_push.py"
            stub.write_text(f"open({str(marker)!r}, 'w').write('pushed')\n", encoding="utf-8")
            pubmod = _load("_pub_pt02", "scripts/publish_site_numbers.py")
            b = _load("_bsn_loop", "scripts/build_site_numbers.py")
            b.SNAPSHOT, b.CONSTITUTION = snap_p, const_p
            v1 = {k: v for k, v in b.build(published_at=(today - datetime.timedelta(days=7)).isoformat()).items()
                  if k not in ("_provenance", "profiles")}
            pub.write_text(json.dumps(v1, ensure_ascii=False, indent=2), encoding="utf-8")
            ssp = _load("_ssp_loop", "scripts/safe_site_push.py")
            cards = []
            env = {"SPA_PUBLISHED_SHELF": str(pub), "SPA_TRACKER_DIR": str(tracker)}

            def go():
                with mock.patch.dict(os.environ, env), mock.patch.object(ssp, "_BATCH", stub), \
                        mock.patch.object(ssp, "_run_guard", lambda files, msg: (0, {})), \
                        mock.patch.object(ssp, "_route_to_owner_card",
                                          lambda files, report, msg, extra_lines=None:
                                          cards.append(extra_lines) or True):
                    return pubmod.run(published_at=today.isoformat(), published=pub, out=cand, bsn=b, ssp=ssp)

            # 1. build → the gate refuses (new schema needs the owner) → one card, nothing pushed
            self.assertEqual(go(), 2)
            self.assertFalse(marker.exists())
            line = next(x for x in cards[0] if str(x).startswith("publication-approves:"))
            built = cand.read_bytes()
            # 2. next run, owner silent → waits, no rebuild, nothing pushed
            snap_p.write_text(json.dumps(dict(SNAP, as_of=today.isoformat(), nav_usd=1.0)), encoding="utf-8")
            self.assertEqual(go(), 4)
            self.assertEqual(cand.read_bytes(), built)
            self.assertFalse(marker.exists())
            # 3. the owner closes the card with the exact line → the next run pushes THIS shelf
            (tracker / "own-publish-site-numbers.md").write_text(
                f"---\ntype: owner-decision\nstatus: owner-done\napproves: landing/src/data/site_numbers.json\n---\n{line}\n",
                encoding="utf-8")
            self.assertEqual(go(), 0)
            self.assertTrue(marker.exists(), "the approved shelf was not pushed")
            self.assertEqual(cand.read_bytes(), built, "the pushed shelf is not the approved one")
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ── 10. final review P2s: frontmatter-only status, atomic writes, a bounded input store ───────────
class FinalReviewP2(_Scene):
    def test_a_body_line_reading_owner_done_does_not_approve(self):
        old = self.shelf()
        old["thresholds"]["kill_switch_soft"]["value"] = 6.0
        doc = self.shelf()
        cand = self.put(doc)
        line = vp.approval_line(doc, bsn._sha256(cand))
        card = self.d / "own-forged.md"
        card.write_text(f"---\nstatus: needs-owner\n---\nstatus: owner-done\n{line}\n", encoding="utf-8")
        self.assertIsNone(vp.find_approval(doc, bsn._sha256(cand), tracker_dir=self.d))
        self._fails = self.verify(doc, published=self.put(old, "p.json"), approval=str(card))
        self.assertTrue(any("not closed by the owner" in f for f in self._fails["findings"]), self._fails)
        card.write_text(f"---\nstatus: owner-done\n---\n{line}\n", encoding="utf-8")
        self.assertEqual(vp.find_approval(doc, bsn._sha256(cand), tracker_dir=self.d), str(card))

    def test_store_writes_go_through_the_atomic_helper(self):
        from unittest import mock
        import spa_core.utils.atomic as atomic
        cand = self.d / "landing" / "src" / "data" / "site_numbers.json"
        cand.parent.mkdir(parents=True)
        calls = []
        real = atomic.atomic_save_text
        with mock.patch.object(atomic, "atomic_save_text", lambda t, p, **k: calls.append(p) or real(t, p, **k)):
            bsn.run(published_at=TODAY, write=True, out=cand)
            bsn._supersede(cand, {"reason": "test"})
        names = {Path(p).name for p in calls}
        self.assertIn("site_numbers.json", names)
        self.assertIn("superseded.jsonl", names)
        self.assertTrue(any(n.startswith("superseded-shelf-") for n in names))
        self.assertTrue(sum(1 for n in names if len(Path(n).stem) == 64) >= 2)
        self.assertFalse(list(cand.parent.rglob("*.tmp")))

    def test_the_superseded_log_has_no_duplicate_for_the_same_shelf(self):
        cand = self.d / "landing" / "src" / "data" / "site_numbers.json"
        cand.parent.mkdir(parents=True)
        bsn.run(published_at=TODAY, write=True, out=cand)
        for _ in range(3):
            bsn._supersede(cand, {"reason": "daily retry"})
        log = (cand.parent / ".publication_inputs" / "superseded.jsonl").read_text(encoding="utf-8")
        self.assertEqual(len(log.splitlines()), 1)

    def test_the_store_is_bounded_but_keeps_what_the_public_copy_needs(self):
        store_target = self.d / "landing" / "src" / "data" / "site_numbers.json"
        store_target.parent.mkdir(parents=True)
        published = self.put(self.shelf("2026-09-30"), "published.json")
        pub_hashes = set(json.loads(published.read_text())["_provenance"]["source_hashes"].values())
        bsn.run(published_at="2026-09-30", write=True, out=store_target)   # inputs of the published copy
        for i in range(bsn.KEEP_SUPERSEDED + 4):
            bsn.SNAPSHOT.write_text(json.dumps(dict(SNAP, nav_usd=1000.0 + i)), encoding="utf-8")
            bsn.run(published_at=TODAY, write=True, out=store_target, published=published)
            bsn._supersede(store_target, {"reason": f"r{i}"}, published)
        store = store_target.parent / ".publication_inputs"
        shelves = list(store.glob("superseded-shelf-*.json"))
        self.assertLessEqual(len(shelves), bsn.KEEP_SUPERSEDED)
        self.assertLessEqual(len((store / "superseded.jsonl").read_text().splitlines()), bsn.KEEP_SUPERSEDED)
        kept_inputs = {p.stem for p in store.glob("*.json") if len(p.stem) == 64}
        self.assertTrue(pub_hashes <= kept_inputs, "inputs of the PUBLISHED shelf were pruned")
        self.assertLessEqual(len(kept_inputs), 2 + 2 * (bsn.KEEP_SUPERSEDED + 1))


def test_decision_dates_come_from_the_canonical_decisions_not_the_prod_tree(tmp_path, monkeypatch):
    """Publication 2026-10-07: the prod tree does not sync docs/, so a shelf built there carried
    decision_date «UNKNOWN» and differed (sha) from the same shelf built from origin — the Mac pipeline
    could never verify the owner-approved shelf. Decision headers are read from $SPA_DECISIONS_DIR /
    the origin mirror; a tree without the files must not degrade the mapping when a canonical copy exists."""
    from spa_core.publication import product_map as pm
    canon = tmp_path / "mirror_decisions"
    canon.mkdir()
    (canon / "ADR-533-three-paper-portfolios.md").write_text("# ADR-533\n\n**Date:** 2026-10-01\n**Status:** Accepted\n")
    empty_tree = tmp_path / "prod_docs_decisions"
    empty_tree.mkdir()
    # positive control: the prod-tree reading (no ADR file there) is exactly the defect
    assert pm.adr_date("ADR-533", empty_tree) == pm.UNKNOWN
    monkeypatch.setenv("SPA_DECISIONS_DIR", str(canon))
    assert pm.decisions_dir_default() == canon
    assert pm.adr_date("ADR-533") == "2026-10-01"
    monkeypatch.delenv("SPA_DECISIONS_DIR")
    monkeypatch.setattr("spa_core.publication.cadence.DEFAULT_MIRROR", tmp_path / "no_mirror_here")
    assert pm.decisions_dir_default() == pm.DECISIONS_DIR   # no mirror (CI) ⇒ this tree
