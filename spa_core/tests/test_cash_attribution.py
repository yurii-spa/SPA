"""Y2 (ADR-055) — deterministic attribution of every idle dollar above the buffer.

The invariant: idle capital is a LOGGED DECISION, never a default. These tests pin
the waterfall (buffer → deployable-but-idle → aggregate caps → missing evidence →
per-protocol caps) with HAND-COMPUTED numbers, including the real 2026-08-04/05
book as the positive control, and the fail-CLOSED contract: a component whose
inputs are missing is UNCHECKED — never a zero that makes cash look explained.

RiskPolicy is an INPUT here (caps come from RiskConfig via the caller); nothing in
this file — or in the code under test — changes a threshold.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.allocator.rebalance_economics import attribute_cash
from spa_core.tests._freshness import ts

CAP = 100_000.0

# ── The real book (cycles #04-05.08.2026): the positive control ─────────────
# pendle 20k @ T2 cap · maple 20k @ T2 cap · morpho_steakhouse 40k @ T1 cap ·
# aave_v3 5k · cash 15k. Evidence exactly as prod recorded it on 2026-08-05:
# 13 live-APY adapters, live TVL only for {aave_v3, compound_v3, yearn_v3,
# euler_v2, maple, pendle} (the rest static — ADR-053 freezes them for NEW money).
BOOK_0408 = {"pendle": 20_000.0, "maple": 20_000.0,
             "morpho_steakhouse": 40_000.0, "aave_v3": 5_000.0}
APY_0408 = {"aave_v3": 3.3095, "compound_v3": 3.3022, "yearn_v3": 3.245,
            "euler_v2": 3.0548, "maple": 4.961, "pendle": 17.4478,
            "morpho_steakhouse": 3.5092, "aave_arbitrum": 2.4054,
            "aave_v3_polygon": 2.744, "morpho_blue": 3.5092,
            "aave_v3_base": 3.3412, "morpho_blue_base": 4.3201,
            "moonwell_base": 4.1623}
SRC_0408 = {k: "live" for k in APY_0408}
TVL_LIVE_0408 = {"aave_v3", "compound_v3", "yearn_v3", "euler_v2", "maple", "pendle"}
TIERS_0408 = {"aave_v3": "T1", "compound_v3": "T1", "aave_arbitrum": "T1",
              "aave_v3_polygon": "T1", "morpho_steakhouse": "T1",
              "pendle": "T2", "maple": "T2", "yearn_v3": "T2", "euler_v2": "T2",
              "morpho_blue": "T2", "aave_v3_base": "T2",
              "morpho_blue_base": "T2", "moonwell_base": "T2",
              "susde": "T3", "spark_susds": "T2"}
CAPS_0408 = {p: (0.40 if t == "T1" else 0.20) for p, t in TIERS_0408.items()}
BLOCKED_0408 = {"susde": "advisory", "spark_susds": "gsm_not_confirmed"}


class _FarAboveFloor(dict):
    """Каждый пул этого файла заведомо ВЫШЕ порога TVL ($5M).

    Порог — новое (08.08) измерение пригодности: до него атрибуция знала только
    ПРОИСХОЖДЕНИЕ TVL и записывала пул ниже порога в «пригодную комнату»
    (карточка `inbox-atributsiya-kesha-i-geit-riskpolicy-po-r`). Здесь он
    намеренно НЕ предмет проверки — эти тесты про капы, блоки и водопад, и их
    числа обязаны остаться прежними до цента. Сам порог проверяется отдельно, в
    обе стороны: `test_tvl_floor_one_definition.py`.
    """

    def get(self, key, default=None):  # noqa: D102 — «любой пул велик»
        return 1_000_000_000.0


# сентинел-ключ нужен, чтобы карта была НЕ ПУСТОЙ: пустая карта над непустой
# вселенной означает «посмотреть не смогли» и честно даёт UNCHECKED.
TVL_FAR_ABOVE_FLOOR = _FarAboveFloor({"__any_pool__": 1_000_000_000.0})
MIN_TVL_USD = 5_000_000.0


def _attr(**kw):
    kw.setdefault("positions", BOOK_0408)
    kw.setdefault("capital_usd", CAP)
    kw.setdefault("min_cash_frac", 0.05)
    kw.setdefault("apy_pct", APY_0408)
    kw.setdefault("apy_sources", SRC_0408)
    kw.setdefault("tvl_live", TVL_LIVE_0408)
    kw.setdefault("tier_caps", CAPS_0408)
    kw.setdefault("tiers", TIERS_0408)
    kw.setdefault("t2_total_cap", 0.50)
    kw.setdefault("t3_total_cap", 0.15)
    kw.setdefault("min_apy_pct", 1.0)
    kw.setdefault("tvl_usd", TVL_FAR_ABOVE_FLOOR)
    kw.setdefault("min_tvl_usd", MIN_TVL_USD)
    kw.setdefault("blocked", BLOCKED_0408)
    return attribute_cash(**kw)


def _by_kind(out):
    return {c["kind"]: c for c in out["components"]}


# ── positive control: the real 04-05.08 book, prod evidence ─────────────────


def test_real_book_0408_buffer_plus_honest_unexplained() -> None:
    """Hand-computed: 15k cash = 5k policy buffer + 10k UNEXPLAINED.

    With prod evidence, aave_v3 (T1, live APY+TVL) alone has $35k of headroom
    under every cap (T1 headroom 75k + T2 room min(40k, 50k−40k)=10k → 85k
    fundable), so the 10k above the buffer was deployable and no cap explains
    it. The honest ADR-055 verdict is UNEXPLAINED_CASH — the caps must NOT be
    allowed to launder the allocator's idleness.
    """
    out = _attr()
    assert out["status"] == "UNEXPLAINED_CASH"
    k = _by_kind(out)
    assert k["min_cash_buffer"]["usd"] == pytest.approx(5_000.0)
    assert k["unexplained_deployable"]["usd"] == pytest.approx(10_000.0)
    # forgone ≈ 10% of capital × best fundable live APY (aave_v3 3.3095%) ≈ 33 bps/yr
    assert k["unexplained_deployable"]["forgone_bps_yr"] == pytest.approx(33.1, abs=0.2)
    assert out["unexplained_pct"] == pytest.approx(10.0)
    assert "aggregate_cap" not in k and "per_protocol_cap" not in k
    assert out["unchecked"] == []


def test_real_book_0408_with_narrow_evidence_is_explained_by_caps_and_eligibility() -> None:
    """Same book on a day the evidence is narrower: live TVL only for the held
    pendle/maple/morpho — aave_v3's TVL feed static.

    Hand-computed: buffer 5k; NO fundable headroom (pendle/maple at the 20% T2
    cap, morpho at the 40% T1 cap — named; aave_v3's 35k room frozen by
    tvl_not_live); the whole 10k excess is bound by the eligible composition →
    explained, UNEXPLAINED_CASH gone, nothing UNCHECKED.
    """
    out = _attr(tvl_live={"pendle", "maple", "morpho_steakhouse"})
    assert out["status"] == "explained"
    k = _by_kind(out)
    assert k["min_cash_buffer"]["usd"] == pytest.approx(5_000.0)
    assert "unexplained_deployable" not in k
    g = k["insufficient_eligible_live"]
    assert g["usd"] == pytest.approx(10_000.0)
    assert any(s.startswith("aave_v3(") and "tvl_not_live" in s for s in g["protocols"])
    assert out["unexplained_pct"] == pytest.approx(0.0)
    assert out["unchecked"] == []


# ── each binder bucket, in isolation ─────────────────────────────────────────


def test_t2_total_cap_binds_and_is_priced() -> None:
    """T2 held at exactly 50%: moonwell's 10k per-protocol room is throttled by
    the aggregate cap → the 5k excess is attributed to aggregate_cap."""
    book = {"morpho_steakhouse": 40_000.0, "pendle": 20_000.0,
            "maple": 20_000.0, "moonwell_base": 10_000.0}
    universe = {p: "live" for p in book}
    out = _attr(positions=book, apy_sources=universe,
                tvl_live=set(book), blocked=None)
    assert out["status"] == "explained"
    k = _by_kind(out)
    assert k["aggregate_cap"]["usd"] == pytest.approx(5_000.0)
    assert "moonwell_base" in k["aggregate_cap"]["protocols"]
    # forgone at moonwell's live 4.1623% on 5% of capital ≈ 20.8 bps/yr
    assert k["aggregate_cap"]["forgone_bps_yr"] == pytest.approx(20.8, abs=0.2)
    assert out["unexplained_pct"] == pytest.approx(0.0)


def test_per_protocol_caps_bind_when_every_pool_is_pinned() -> None:
    """morpho/pendle/maple all AT their 40/20 caps, nothing else exists →
    the 15k excess is per_protocol_cap, protocols named."""
    book = {"morpho_steakhouse": 40_000.0, "pendle": 20_000.0, "maple": 20_000.0}
    out = _attr(positions=book, apy_sources={p: "live" for p in book},
                tvl_live=set(book), blocked=None)
    assert out["status"] == "explained"
    k = _by_kind(out)
    assert k["per_protocol_cap"]["usd"] == pytest.approx(15_000.0)
    named = " ".join(k["per_protocol_cap"]["protocols"])
    for proto in ("morpho_steakhouse@40%", "pendle@20%", "maple@20%"):
        assert proto in named
    assert out["unexplained_pct"] == pytest.approx(0.0)


def test_genuinely_lazy_cash_stays_the_alarm() -> None:
    """95k cash with 75k of fully-evidenced headroom: 75k UNEXPLAINED (the honest
    signal), the 15k overflow bound by per-protocol caps at the margin."""
    book = {"aave_v3": 5_000.0}
    srcs = {"aave_v3": "live", "compound_v3": "live"}
    out = _attr(positions=book, apy_sources=srcs,
                tvl_live={"aave_v3", "compound_v3"}, blocked=None)
    assert out["status"] == "UNEXPLAINED_CASH"
    k = _by_kind(out)
    assert k["unexplained_deployable"]["usd"] == pytest.approx(75_000.0)
    assert k["per_protocol_cap"]["usd"] == pytest.approx(15_000.0)
    assert out["unexplained_pct"] == pytest.approx(75.0)


def test_blocked_protocols_explain_room_with_their_reason() -> None:
    """Room that exists only in blocked pools is (г), reason verbatim."""
    book = {"morpho_steakhouse": 40_000.0, "pendle": 20_000.0, "maple": 20_000.0}
    srcs = {**{p: "live" for p in book}, "susde": "live"}
    out = _attr(positions=book, apy_sources=srcs, tvl_live=set(srcs),
                blocked={"susde": "advisory"})
    assert out["status"] == "explained"
    g = _by_kind(out)["insufficient_eligible_live"]
    assert g["usd"] == pytest.approx(15_000.0)
    assert any("susde" in s and "blocked:advisory" in s for s in g["protocols"])


def test_cash_at_the_buffer_needs_no_attribution() -> None:
    out = _attr(positions={"morpho_steakhouse": 40_000.0, "pendle": 20_000.0,
                           "maple": 20_000.0, "aave_v3": 15_000.0})
    assert out["status"] == "explained"
    assert out["excess_pct"] == pytest.approx(0.0)
    assert out["unexplained_pct"] == pytest.approx(0.0)


def test_empty_eligible_universe_is_an_explained_refusal() -> None:
    """All-cash book with no candidates at all (feeds down / everything refused):
    holding cash is fail-closed correctness, not laziness."""
    out = _attr(positions={}, apy_sources={}, tvl_live=set(), blocked=None)
    assert out["status"] == "explained"
    g = _by_kind(out)["insufficient_eligible_live"]
    assert g["usd"] == pytest.approx(95_000.0)
    assert out["unexplained_pct"] == pytest.approx(0.0)


# ── fail-CLOSED: missing inputs are UNCHECKED, never zero ────────────────────


@pytest.mark.parametrize("missing,flag", [
    ({"apy_sources": None}, "apy_provenance_unavailable"),
    ({"tvl_live": None}, "tvl_provenance_unavailable"),
    ({"tier_caps": None, "tiers": None}, "risk_caps_unresolved"),
    ({"t2_total_cap": None}, "aggregate_caps_unresolved"),
])
def test_missing_input_is_unchecked_not_zero(missing: dict, flag: str) -> None:
    out = _attr(**missing)
    assert out["status"] == "attribution_incomplete"
    assert flag in out["unchecked"]
    assert out["unexplained_pct"] is None            # unknown ≠ 0 and ≠ explained
    unattributed = [c for c in out["components"] if c["status"] == "UNCHECKED"]
    assert unattributed and unattributed[0]["usd"] == pytest.approx(10_000.0)


def test_invalid_capital_is_an_error() -> None:
    assert attribute_cash(positions={}, capital_usd=0.0, min_cash_frac=0.05,
                          apy_pct={}, apy_sources={}, tvl_live=set(),
                          tier_caps={}, tiers={}, t2_total_cap=0.5,
                          t3_total_cap=0.15, min_apy_pct=1.0)["status"] == "error"


def test_components_sum_to_the_whole_cash_pile() -> None:
    """Conservation: buffer + attributed + unexplained == cash, to the cent."""
    for out in (_attr(), _attr(tvl_live={"pendle", "maple", "morpho_steakhouse"})):
        total = sum(c["usd"] for c in out["components"])
        assert total == pytest.approx(15_000.0, abs=0.01)


# ── monitoring joins up (task Y2 §4): LAZY sees the attribution ──────────────


def _write_rationale(tmp_path: Path, cash: dict, *, age_h: float = 1.0) -> None:
    gen = datetime.now(timezone.utc) - timedelta(hours=age_h)
    (tmp_path / "allocation_rationale.json").write_text(json.dumps({
        "generated_at": gen.isoformat(), "mode": "SHADOW", "cash": cash,
    }), encoding="utf-8")


def _ce(monkeypatch, tmp_path: Path, *, cash_pct: float = 0.15):
    import spa_core.monitoring.capital_efficiency as ce
    pos = {"capital_usd": CAP, "cash_usd": cash_pct * CAP,
           "deployed_usd": (1 - cash_pct) * CAP,
           "positions": [{"protocol": "aave_v3", "usd": 40_000}]}
    # tvl_usd — новое (08.08) измерение пригодности: комната годится, только если
    # размер пула наблюдён и он выше порога RiskPolicy ($5M). Здесь пул заведомо
    # крупный, чтобы эти тесты остались про то, про что были — про то, что
    # неполная/протухшая атрибуция НЕ гасит тревогу. Отсутствие размера — отдельный
    # случай, он проверяется ниже (test_headroom_without_measured_tvl_is_unknown).
    # `apy_source`/`last_updated`/`generated_at` — с 16.08 обязательные поля строки
    # рейтинга: доходность, по которой считают цену простоя, обязана быть
    # наблюдением ЭТОГО цикла (карточка «два артефакта одного цикла расходятся
    # втрое»). Здесь они проставлены свежими намеренно — эти тесты про то, что
    # неполная/протухшая АТРИБУЦИЯ не гасит тревогу, и их числа обязаны остаться
    # прежними; провенанс доходности проверяется в
    # `test_apy_one_observation_per_cycle.py`.
    _stamp = ts(hours_ago=0.5)
    apy = {"generated_at": _stamp,
           "by_apy": [{"protocol": "compound_v3", "tier": "T1", "apy_pct": 3.3,
                       "tvl_usd": 1_500_000_000.0, "apy_source": "live",
                       "last_updated": _stamp}]}
    real_load = ce._load

    def fake_load(p):
        s = str(p)
        if s.endswith("current_positions.json"):
            return pos
        if s.endswith("apy_ranking.json"):
            return apy
        if s.endswith("allocation_rationale.json"):
            return real_load(tmp_path / "allocation_rationale.json")
        return None

    monkeypatch.setattr(ce, "_load", fake_load)
    return ce


def test_explained_cash_is_not_lazy(monkeypatch, tmp_path: Path) -> None:
    ce = _ce(monkeypatch, tmp_path)
    _write_rationale(tmp_path, {
        "status": "explained", "unexplained_pct": 0.0,
        "components": [{"kind": "min_cash_buffer", "usd": 5000.0, "pct": 5.0,
                        "status": "OK"}]})
    r = ce.assess()
    assert r["verdict"] == "EXPLAINED", r
    assert r["attribution_status"] == "explained"
    assert r["cash_attribution"]           # the split rides along for the reader


def test_unexplained_over_two_percent_stays_lazy(monkeypatch, tmp_path: Path) -> None:
    ce = _ce(monkeypatch, tmp_path)
    _write_rationale(tmp_path, {
        "status": "UNEXPLAINED_CASH", "unexplained_pct": 10.0,
        "components": [{"kind": "unexplained_deployable", "usd": 10_000.0,
                        "pct": 10.0, "forgone_bps_yr": 33.1, "status": "OK"}]})
    r = ce.assess()
    assert r["verdict"] == "WARNING", r
    assert "UNEXPLAINED" in r["reason"]
    assert r["forgone_yield_bps_est"] == 33
    assert r["cash_unexplained_pct"] == pytest.approx(10.0)


def test_small_unexplained_remainder_is_tolerated(monkeypatch, tmp_path: Path) -> None:
    ce = _ce(monkeypatch, tmp_path)
    _write_rationale(tmp_path, {
        "status": "UNEXPLAINED_CASH", "unexplained_pct": 1.5,
        "components": [{"kind": "unexplained_deployable", "usd": 1_500.0,
                        "pct": 1.5, "forgone_bps_yr": 5.0, "status": "OK"}]})
    r = ce.assess()
    assert r["verdict"] == "EXPLAINED", r


def test_incomplete_attribution_cannot_vouch(monkeypatch, tmp_path: Path) -> None:
    """attribution_incomplete ⇒ the legacy heuristic stays in force (fail-closed):
    idle book + qualifying headroom is still LAZY."""
    ce = _ce(monkeypatch, tmp_path)
    _write_rationale(tmp_path, {
        "status": "attribution_incomplete", "unexplained_pct": None,
        "components": [{"kind": "unattributed", "usd": 10_000.0, "pct": 10.0,
                        "status": "UNCHECKED"}]})
    r = ce.assess()
    assert r["verdict"] == "WARNING", r     # legacy LAZY, not silenced


def test_stale_attribution_cannot_vouch(monkeypatch, tmp_path: Path) -> None:
    ce = _ce(monkeypatch, tmp_path)
    _write_rationale(tmp_path, {
        "status": "explained", "unexplained_pct": 0.0,
        "components": [{"kind": "min_cash_buffer", "usd": 5000.0, "pct": 5.0,
                        "status": "OK"}]}, age_h=48.0)
    r = ce.assess()
    assert r["verdict"] == "WARNING", r     # a week-old story can't silence today


def test_agent_health_reports_explained_without_an_issue(tmp_path: Path) -> None:
    from spa_core.monitoring.agent_health_monitor import check_system
    (tmp_path / "capital_efficiency.json").write_text(json.dumps({
        "verdict": "EXPLAINED", "idle_excess_pct": 0.10,
        "attribution_status": "explained", "cash_unexplained_pct": 0.0,
    }), encoding="utf-8")
    checks, _status, issues = check_system(
        tmp_path, datetime.now(timezone.utc), autopush_log="/nonexistent")
    assert checks["capital_efficiency"] == "EXPLAINED"
    assert checks["capital_cash_attribution"] == "explained"
    assert not any("capital-efficiency" in i for i in issues)


def test_agent_health_lazy_message_names_the_unexplained_number(tmp_path: Path) -> None:
    from spa_core.monitoring.agent_health_monitor import check_system
    (tmp_path / "capital_efficiency.json").write_text(json.dumps({
        "verdict": "WARNING", "idle_excess_pct": 0.10,
        "attribution_status": "UNEXPLAINED_CASH", "cash_unexplained_pct": 10.0,
        "forgone_yield_bps_est": 33,
    }), encoding="utf-8")
    _checks, status, issues = check_system(
        tmp_path, datetime.now(timezone.utc), autopush_log="/nonexistent")
    lazy = [i for i in issues if "capital-efficiency LAZY" in i]
    assert lazy and "10.0% of capital idle UNEXPLAINED" in lazy[0]
    assert "33bps/yr" in lazy[0]
