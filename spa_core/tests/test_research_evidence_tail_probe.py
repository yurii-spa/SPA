"""spa_core/tests/test_research_evidence_tail_probe.py — the `research_evidence_tail_closed` acceptance probe
(card `inbox-hvost-adr-564-pyat-defektov-fabriki-issl`, .claude/rules/acceptance.md rule 3).

The probe is green on the intact contour and red on EVERY broken link — each red names its own link, compared
as a whole token of the verdict detail, never as a stray substring of free text (ADR-333).

# FROZEN-DATE-OK: injected-clock — the anchor NOW is passed to the probe as `now=`; every time the probe's
# scenes judge comes from that argument, nothing asks the wall clock.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.research_factory import evidence_contract as ec
from spa_core.research_factory import forward, http_client, registry_loader

NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
LINKS = ("lapse_period", "reviewer_allow_list", "observed_role_binding", "initial_url_normalised",
         "effective_until", "contract_computed_return")


def _probe():
    return ca.PROBES["research_evidence_tail_closed"](None, now=NOW)


def _broken_links(detail: str) -> set:
    assert detail.startswith("разорваны звенья: "), detail
    return {part.split("(", 1)[0].strip() for part in detail[len("разорваны звенья: "):].split(";")}


def test_probe_is_registered():
    assert "research_evidence_tail_closed" in ca.PROBES


def test_intact_contour_is_satisfied():
    verdict, detail = _probe()
    assert verdict == ca.SATISFIED, detail


MUTATIONS = {
    "lapse_period": lambda mp: mp.setattr(forward, "void_unconfirmed_periods", lambda *a, **k: []),
    "reviewer_allow_list": lambda mp: mp.setattr(ec, "FACT_REVIEWERS",
                                                  ec.FACT_REVIEWERS + ("probe-unlisted-reviewer",)),
    "observed_role_binding": lambda mp: mp.setattr(ec, "ROLE_OBSERVABLE_CLAIMS",
                                                    {r: ec.CHAIN_NATIVE_CLAIMS for r in ec.ROLES}),
    "initial_url_normalised": lambda mp: mp.setattr(http_client, "_path_is_canonical", lambda p: True),
    "effective_until": lambda mp: mp.setattr(registry_loader, "has_ended", lambda *a, **k: False),
    "contract_computed_return": lambda mp: mp.setattr(ec, "return_claim_type", lambda *a, **k: None),
}


@pytest.mark.parametrize("link", LINKS)
def test_each_broken_link_is_named_and_only_it(link, monkeypatch):
    MUTATIONS[link](monkeypatch)
    verdict, detail = _probe()
    assert verdict == ca.NOT_SATISFIED, detail
    assert _broken_links(detail) == {link}, detail


def test_every_link_has_a_mutation():
    assert set(MUTATIONS) == set(LINKS)


def test_a_scene_that_cannot_run_is_unmeasured_not_satisfied(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("scene setup failed")
    import spa_core.research_factory.failure_matrix_v2 as fm2
    monkeypatch.setattr(fm2, "_base_candidate", _boom)
    verdict, detail = _probe()
    assert verdict == ca.UNMEASURED, detail
    assert "RuntimeError" in detail


def test_effective_until_scene_catches_a_hash_that_counts_an_absent_field(monkeypatch):
    """Re-review M2: the scene compared a hash with itself. Mutant: an absent effective_until hashed as null
    (which would unbind every existing review) — the scene must now name the link."""
    real = ec.fact_content_sha256

    def _null_hash(row):
        return real(dict(row, effective_until=row.get("effective_until")))
    monkeypatch.setattr(ec, "fact_content_sha256", _null_hash)
    verdict, detail = _probe()
    assert verdict == ca.NOT_SATISFIED, detail
    assert "effective_until" in _broken_links(detail), detail


@pytest.mark.parametrize("path", ["/api/../admin", "/api/..;/admin", "/api/%2e%2e/admin", "/api/%252e%252e/admin",
                                  "/api/..%2fadmin", "/api/..%5cadmin", "/api/\uff0e\uff0e/admin", "/api/..%00/admin",
                                  "/api/./x", "/api\\..\\admin"])
def test_non_canonical_paths_never_reach_the_transport(path):
    calls = []

    def _transport(request, timeout_s):
        calls.append(request)
        raise OSError("never a socket")
    with pytest.raises(http_client.HttpRefused):
        http_client.fetch("https://usyc.hashnote.com" + path, now=NOW, transport=_transport)
    assert calls == []


def test_canonical_allowed_path_still_reaches_the_transport():
    calls = []

    def _transport(request, timeout_s):
        calls.append(request)
        raise OSError("never a socket")
    with pytest.raises(OSError):
        http_client.fetch("https://usyc.hashnote.com/api/price-reports", now=NOW, transport=_transport)
    assert len(calls) == 1


# ── re-review M4: every route that used to fake OBSERVED ─────────────────────────────────────────────
def _cit(origin, channel, claim=None, quote=None):
    return ec.citation(origin=origin, channel=channel, ref=f"chain:1:0x00:{claim}" if channel == ec.CHANNEL_ON_CHAIN
                       else "https://counterparty.example/api", retrieved_at=NOW.isoformat(), claim_type=claim,
                       quote=quote)


REG = {"chain:1": {"group": "onchain"}, "issuer:acme": {"group": "acme"}, "venue:known": {"group": "known"}}


@pytest.mark.parametrize("role,cit,issuer_group", [
    ("custodian", ("issuer:acme", ec.CHANNEL_ON_CHAIN, "balance"), "acme"),       # issuer posting on-chain
    ("custodian", ("chain:1", ec.CHANNEL_ON_CHAIN, "bytecode"), "acme"),          # claim does not fit the role
    ("legal_entity", ("venue:nobody", ec.CHANNEL_OFFICIAL_API, None), "acme"),    # unregistered API origin
    ("legal_entity", ("venue:known", ec.CHANNEL_OFFICIAL_API, None), None),       # no issuer group to compare
    ("legal_entity", ("issuer:acme", ec.CHANNEL_OFFICIAL_API, None), "acme"),     # the issuer's own API
    ("custodian", ("venue:known", ec.CHANNEL_OFFICIAL_API, None), "acme"),        # an API of the wrong role type
])
def test_observed_cannot_be_faked(role, cit, issuer_group):
    with pytest.raises(ValueError):
        ec.role_entry(ec.CP_OBSERVED, role=role, identity="X", citations=[_cit(*cit)], registry=REG,
                      issuer_group=issuer_group)


@pytest.mark.parametrize("role,cit", [
    ("custodian", ("chain:1", ec.CHANNEL_ON_CHAIN, "balance")),
    ("exchange", ("venue:known", ec.CHANNEL_OFFICIAL_API, None)),
])
def test_observed_still_reachable_honestly(role, cit):
    entry = ec.role_entry(ec.CP_OBSERVED, role=role, identity="X", citations=[_cit(*cit)], registry=REG,
                          issuer_group="acme")
    assert entry["state"] == ec.CP_OBSERVED


# ── re-review M1: N4 holds across a crashed run, and promotion never rides a voided period ─────────────
def _admitted(tmp_path):
    from spa_core.research_factory import failure_matrix_v2 as fm2
    cand = fm2._base_candidate()
    fm2._admit_to_paper_active_v2(tmp_path, cand, NOW)
    return cand


def _counted_obs(tmp_path, cid, t, period):
    from datetime import timedelta  # noqa: F401
    from spa_core.research_factory import contract as c1
    forward.record(tmp_path, cid, {"period": period, "backfill": False, "realised_index": None,
                                   "observed_return": c1.cell(c1.MEASURED, 0.05, source_ref="t",
                                                              source_class=c1.PRIMARY_PROTOCOL, source_root="chain:1",
                                                              as_of=t.isoformat(), now=t)}, t)


def test_a_period_left_by_a_crashed_run_is_voided_when_a_later_review_pauses(tmp_path):
    from datetime import timedelta
    from spa_core.research_factory import bundle as bundle_mod, lifecycle, run as rf_run
    cand = _admitted(tmp_path)
    cid = cand["candidate_id"]
    _counted_obs(tmp_path, cid, NOW + timedelta(hours=1), "p1")      # run 1 records, then "crashes" (no run row)
    assert forward.forward_periods(tmp_path, cid) == 1
    b = bundle_mod.latest_bundle(tmp_path, cid)
    rf_run._route_sherlock_outcome(tmp_path, cid, cand, lifecycle.current_state(tmp_path, cid), b, b,
                                   {"decision": ec.NEEDS_MORE_EVIDENCE, "rationale": ["lapsed"],
                                    "failed_gates": ["fees_measured"], "unknowns": []}, False,
                                   NOW + timedelta(hours=5))           # the re-run's review, later
    assert forward.forward_periods(tmp_path, cid) == 0


def test_a_period_confirmed_by_a_completed_run_is_never_voided(tmp_path):
    from datetime import timedelta
    from spa_core.research_factory import bundle as bundle_mod, lifecycle, run as rf_run
    from spa_core.research_factory._common import iso, ledger_for
    cand = _admitted(tmp_path)
    cid = cand["candidate_id"]
    _counted_obs(tmp_path, cid, NOW + timedelta(hours=1), "p1")
    t_run = NOW + timedelta(hours=2)
    ledger_for(tmp_path).append_idempotent("run", ["run", iso(t_run)], {"generated_at": iso(t_run)}, iso(t_run))
    b = bundle_mod.latest_bundle(tmp_path, cid)
    rf_run._route_sherlock_outcome(tmp_path, cid, cand, lifecycle.current_state(tmp_path, cid), b, b,
                                   {"decision": ec.NEEDS_MORE_EVIDENCE, "rationale": ["lapsed"],
                                    "failed_gates": ["fees_measured"], "unknowns": []}, False,
                                   NOW + timedelta(hours=3))
    assert forward.forward_periods(tmp_path, cid) == 1  # confirmed by the completed run, kept


def test_promotion_runs_after_the_review_and_never_on_a_voided_period(tmp_path, monkeypatch):
    """Re-review M1(b): _process_candidate no longer promotes; _promote_after_review does, after Sherlock."""
    import inspect
    from spa_core.research_factory import run as rf_run
    src = inspect.getsource(rf_run._process_candidate)
    assert "EVIDENCE_ACCUMULATING" not in src.split('"""')[-1] or "transition(" not in src.split("forward.record")[-1]
    body = inspect.getsource(rf_run.run_once)
    assert body.index("_sherlock_review_all(") < body.index("_promote_after_review(")


@pytest.mark.parametrize("url", ["https://usyc.hashnote.com:8443/api/price-reports",
                                 "https://evil.com\\@usyc.hashnote.com/api/price-reports",
                                 "https://user@usyc.hashnote.com/api/price-reports"])
def test_initial_url_with_userinfo_or_other_port_never_reaches_the_transport(url):
    calls = []

    def _transport(request, timeout_s):
        calls.append(request)
        raise OSError("never a socket")
    with pytest.raises(http_client.HttpRefused):
        http_client.fetch(url, now=NOW, transport=_transport)
    assert calls == []


@pytest.mark.parametrize("ref,declared", [("chain:1:0xdead:bytecode", "balance"),
                                          ("chain:1:0xdead:unknownMethod", "balance")])
def test_on_chain_observed_needs_the_ref_to_read_the_declared_claim(ref, declared):
    cit = ec.citation(origin="chain:1", channel=ec.CHANNEL_ON_CHAIN, ref=ref, retrieved_at=NOW.isoformat(),
                      claim_type=declared)
    with pytest.raises(ValueError):
        ec.role_entry(ec.CP_OBSERVED, role="custodian", identity="X", citations=[cit], registry=REG,
                      issuer_group="acme")

