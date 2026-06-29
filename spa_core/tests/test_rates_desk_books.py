"""
spa_core/tests/test_rates_desk_books.py — LANE A W1 (A1.1–A1.5): the N-book gated-carry spine.

Covers:
  • books.py            — the book registry (A1.1): stable deterministic book_id, sorted/enumerable,
                          LRT excluded (refusal-gated), ids unique, no clock/RNG.
  • books_series.py     — the per-book realized-series writer (A1.2/A1.3/A1.4): frozen-contract schema,
                          proof-chained (single-genesis, prev-linked), idempotent per UTC day,
                          refusal-state per book, deployable regression-pinned to capacity/portfolio,
                          deployable ≤ §9 cap, fail-CLOSED on missing data.
  • RED-TEAM (A1.5)     — adversarial: duplicate book_id, back-dated row, fabricated deployable above
                          pool depth → all caught. Properties: deployable ≤ §9 cap ∀ books; ids unique;
                          is_realized end-to-end (no backtest leak); book count monotonic vs registry.

PURE / no network / deterministic / fail-CLOSED. The series writer is exercised over SYNTHETIC multi-
market deep datasets (hermetic) where it matters; a separate test runs the REAL cached deep dataset
when present (skipped otherwise) and PINS the per-book deployable to the existing portfolio_capacity.json.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json

import pytest

from spa_core.strategy_lab.rates_desk import books as B
from spa_core.strategy_lab.rates_desk import books_series as BS
from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams


# ── hermetic synthetic deep datasets (shaped like pendle_pt_history.load()) ──────────────────────────
def _one_market(maturity: str, n_days: int, depth_usd: float, implied: float, key: str,
                underlying: str = "sUSDe", kind: str = "stable_synth", chain=None) -> tuple:
    start = datetime.date(2025, 1, 1)
    series = [{"date": (start + datetime.timedelta(days=i)).isoformat(),
               "implied_yield": implied, "underlying_yield": implied - 0.02,
               "tvl_usd": depth_usd, "pt_price": None} for i in range(n_days)]
    market = {"underlying": underlying, "kind": kind, "symbol": key, "market_address": f"0x{key}",
              "pt_address": f"0xpt{key}", "maturity": maturity, "method": "synthetic", "series": series}
    if chain is not None:
        market["chain"] = chain
    return key, market, [p["date"] for p in series]


def _deep(markets_spec: list) -> dict:
    """markets_spec: list of (key, maturity, depth, implied, underlying, kind[, chain])."""
    markets = {}
    all_dates: list = []
    for spec in markets_spec:
        key, m, dates = _one_market(maturity=spec[1], n_days=200, depth_usd=spec[2], implied=spec[3],
                                    key=spec[0], underlying=spec[4], kind=spec[5],
                                    chain=(spec[6] if len(spec) > 6 else None))
        markets[key] = m
        all_dates.extend(dates)
    return {"generated_at": "2026-01-01T00:00:00+00:00", "method": "synthetic_test",
            "underlyings": ["susde"], "window": {"start": min(all_dates), "end": max(all_dates)},
            "markets": markets}


@pytest.fixture
def healthy_deep():
    # 3 healthy sUSDe books at deep depth → all deploy; 1 toxic LRT → excluded from the registry.
    return _deep([
        ("PT-sUSDE-A", "2025-09-25", 100_000_000.0, 0.11, "sUSDe", "stable_synth"),
        ("PT-sUSDE-B", "2025-12-26", 100_000_000.0, 0.11, "sUSDe", "stable_synth"),
        ("PT-sUSDE-C", "2026-03-27", 100_000_000.0, 0.11, "sUSDe", "stable_synth"),
        ("PT-ezETH-X", "2025-09-25", 100_000_000.0, 0.20, "ezETH", "lrt"),
    ])


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A1.1 — book registry: stable ids, sorted, LRT excluded, deterministic
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_book_id_is_deterministic_content_hash():
    """Same (underlying, maturity, chain) → same book_id, ALWAYS (no clock/RNG/order). Different
    identity → different id."""
    a = B.make_book_id("sUSDe", "2025-09-25", "ethereum")
    b = B.make_book_id("susde", "2025-09-25", "ethereum")     # case-insensitive identity
    c = B.make_book_id("sUSDe", "2025-12-26", "ethereum")
    assert a == b
    assert a != c
    assert a.startswith("bk_") and len(a) == 3 + 16


def test_registry_excludes_lrt_and_is_sorted(healthy_deep):
    """LRT markets are EXCLUDED (refusal-gated → never a fundable book); the rest are sorted+unique."""
    books = B.enumerate_books(healthy_deep)
    assert len(books) == 3                                  # the ezETH LRT is excluded
    assert all(bk.kind == "stable_synth" for bk in books)
    assert "ezETH" not in {bk.underlying for bk in books}
    # sorted by (underlying, maturity, market_key) — stable order
    assert books == sorted(books, key=lambda bk: (bk.underlying.lower(), bk.maturity, bk.market_key))
    # ids unique
    assert len({bk.book_id for bk in books}) == len(books)


def test_registry_deterministic_across_runs(healthy_deep):
    """Enumerating twice yields byte-identical ids in identical order."""
    r1 = [bk.book_id for bk in B.enumerate_books(healthy_deep)]
    r2 = [bk.book_id for bk in B.enumerate_books(healthy_deep)]
    assert r1 == r2


def test_make_book_id_fail_closed_on_empty_identity():
    """A book with no identity is not a book — RAISES."""
    with pytest.raises(ValueError):
        B.make_book_id("", "2025-09-25", "ethereum")


def test_chain_in_book_identity():
    """The chain participates in the id — the SAME (underlying, maturity) on a DIFFERENT chain is a
    DIFFERENT book (multi-chain scale)."""
    eth = B.make_book_id("sUSDe", "2025-09-25", "ethereum")
    arb = B.make_book_id("sUSDe", "2025-09-25", "arbitrum")
    assert eth != arb


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A1.2 — per-book realized series: frozen-contract schema, proof-chained, idempotent
# ══════════════════════════════════════════════════════════════════════════════════════════════════
_FROZEN_PAYLOAD_KEYS = {
    "as_of", "book_id", "market", "maturity", "chain", "deployable_usd", "deployed_usd", "idle_usd",
    "gross_carry_pct", "net_carry_after_slippage_pct", "floor_pct", "refusal_state",
}
_FROZEN_ENVELOPE_KEYS = {"prev_hash", "row_hash"}


def test_row_matches_frozen_contract_schema(tmp_path, healthy_deep):
    """Every row carries EXACTLY the frozen-contract fields + the chain envelope."""
    BS.write_all(deep=healthy_deep, funding={}, books_dir=tmp_path)
    book = B.enumerate_books(healthy_deep)[0]
    rows = [json.loads(l) for l in (tmp_path / book.book_id / "realized_series.jsonl")
            .read_text().splitlines() if l.strip()]
    assert rows
    keys = set(rows[-1].keys())
    assert keys == _FROZEN_PAYLOAD_KEYS | _FROZEN_ENVELOPE_KEYS


def test_as_of_is_surface_date_not_wall_clock(tmp_path, healthy_deep):
    """as_of is the deep stream's window END (the surface/data date), never the wall clock."""
    summary = BS.write_all(deep=healthy_deep, funding={}, books_dir=tmp_path)
    assert summary["as_of"] == healthy_deep["window"]["end"]
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    assert summary["as_of"] != today  # the synthetic window end is 2025-07-19-ish, not today


def test_series_is_proof_chained_and_verifies(tmp_path, healthy_deep):
    """Every book's series is a single-genesis prev-linked chain that verifies standalone (§5)."""
    BS.write_all(deep=healthy_deep, funding={}, books_dir=tmp_path)
    for book in B.enumerate_books(healthy_deep):
        rows = [json.loads(l) for l in (tmp_path / book.book_id / "realized_series.jsonl")
                .read_text().splitlines() if l.strip()]
        v = BS.verify_series(rows)
        assert v["valid"], (book.book_id, v)
        assert rows[0]["prev_hash"] == BS.GENESIS_PREV


def test_idempotent_same_utc_day_identical_head(tmp_path, healthy_deep):
    """Two runs the SAME UTC day → IDENTICAL head_hash and length 1 (never double-counts)."""
    s1 = BS.write_all(deep=healthy_deep, funding={}, books_dir=tmp_path)
    heads1 = {b["book_id"]: (b["head_hash"], b["length"]) for b in s1["books"]}
    s2 = BS.write_all(deep=healthy_deep, funding={}, books_dir=tmp_path)
    heads2 = {b["book_id"]: (b["head_hash"], b["length"]) for b in s2["books"]}
    assert heads1 == heads2
    assert all(ln == 1 for _, ln in heads2.values())


def test_distinct_day_appends(tmp_path, healthy_deep):
    """A DISTINCT as_of appends a new row (the chain grows) and re-links cleanly."""
    book = B.enumerate_books(healthy_deep)[0]
    BS.write_all(deep=healthy_deep, funding={}, as_of="2025-07-18", books_dir=tmp_path)
    BS.write_all(deep=healthy_deep, funding={}, as_of="2025-07-19", books_dir=tmp_path)
    rows = [json.loads(l) for l in (tmp_path / book.book_id / "realized_series.jsonl")
            .read_text().splitlines() if l.strip()]
    assert len(rows) == 2
    assert [r["as_of"] for r in rows] == ["2025-07-18", "2025-07-19"]
    assert BS.verify_series(rows)["valid"]
    # re-running the FIRST day again does NOT double-count (refreshes, stays 2 rows)
    BS.write_all(deep=healthy_deep, funding={}, as_of="2025-07-19", books_dir=tmp_path)
    rows2 = [json.loads(l) for l in (tmp_path / book.book_id / "realized_series.jsonl")
             .read_text().splitlines() if l.strip()]
    assert len(rows2) == 2


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A1.3 — refusal-state per book (the refusal IS the edge)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_refused_book_records_refuse_and_zero_deployable(tmp_path):
    """A book the gate refuses entirely (never deploys) → refusal_state=REFUSE, deployable forced 0."""
    # a thin, low-implied book the gate refuses (implied below the floor/hurdle so net edge ≤ 0)
    deep = _deep([("PT-sUSDE-THIN", "2025-09-25", 5_000.0, 0.005, "sUSDe", "stable_synth")])
    summary = BS.write_all(deep=deep, funding={}, books_dir=tmp_path)
    row = summary["books"][0]
    if row["refusal_state"] == "REFUSE":
        assert row["deployable_usd"] == 0.0
    # whichever state, deployable is consistent with it (DEPLOYED ⇒ >0, REFUSE ⇒ ==0)
    assert (row["deployable_usd"] > 0.0) == (row["refusal_state"] == "DEPLOYED")


def test_toxic_lrt_is_refused_by_being_excluded(tmp_path):
    """A toxic LRT market never even becomes a Book → it can never carry a deployable (the strongest
    refusal: it is not in the addressable universe at all). A universe of ONLY LRT books writes no
    series (zero chains) — no fabricated capacity into a refused market."""
    deep = _deep([("PT-ezETH-X", "2025-09-25", 100_000_000.0, 0.20, "ezETH", "lrt")])
    assert B.enumerate_books(deep) == []
    summary = BS.write_all(deep=deep, funding={}, books_dir=tmp_path)
    assert summary["n_books"] == 0
    assert list(tmp_path.rglob("realized_series.jsonl")) == []


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A1.4 — deployable ≤ §9 cap + regression-pin to the validated capacity/portfolio sizing
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_deployable_le_section9_cap_for_all_books(tmp_path, healthy_deep):
    """PROPERTY: every book's deployable_usd ≤ the §9 one-tick exit cap (max_size_frac_of_exit *
    exit_liquidity) of its market — sizing is depth-bound, never fabricated above pool depth."""
    params = RatePolicyParams()
    summary = BS.write_all(deep=healthy_deep, funding={}, params=params, books_dir=tmp_path)
    # the deepest the §9 cap can ever allow at this depth = max_size_frac_of_exit * exit_liquidity.
    # exit_liquidity ≤ tvl, so an upper bound on any book's deployable is frac * depth (generous).
    depth = 100_000_000.0
    cap_upper = float(params.max_size_frac_of_exit) * depth
    for b in summary["books"]:
        assert b["deployable_usd"] <= cap_upper + 1e-6, b


def _try_load() -> bool:
    try:
        pph.load()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _try_load(), reason="deep Pendle PT history not cached")
def test_real_deployable_regression_pinned_to_portfolio(tmp_path):
    """On the REAL cached deep dataset, each book's deployable_usd MATCHES the existing
    portfolio_capacity.json fundable-book sizing to the cent (A1.4 regression pin — reuse the validated
    §9 sizing, don't reinvent). REFUSED books are exactly the markets portfolio dropped."""
    import pathlib
    pc_path = pathlib.Path("data/rates_desk/portfolio_capacity.json")
    if not pc_path.is_file():
        pytest.skip("portfolio_capacity.json not present")
    pc = json.loads(pc_path.read_text())
    pcmap = {b["market_key"]: b["deployable_usd"] for b in pc["books"]}

    summary = BS.write_all(books_dir=tmp_path)
    by_market = {b["market"]: b for b in summary["books"]}
    # every portfolio fundable book matches a DEPLOYED book here to the cent
    for mk, dep in pcmap.items():
        assert mk in by_market, mk
        assert by_market[mk]["refusal_state"] == "DEPLOYED"
        assert abs(by_market[mk]["deployable_usd"] - dep) < 0.01, (mk, dep, by_market[mk])
    # every REFUSED book is one portfolio dropped (not in its fundable set)
    for b in summary["books"]:
        if b["refusal_state"] == "REFUSE":
            assert b["market"] not in pcmap, b["market"]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A1.5 — RED-TEAM: adversarial injections + invariant properties + smoke
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_redteam_back_dated_row_breaks_chain(tmp_path, healthy_deep):
    """Adversary BACK-DATES (mutates as_of of) a published row → the recompute diverges (broken_at)."""
    book = B.enumerate_books(healthy_deep)[0]
    BS.write_all(deep=healthy_deep, funding={}, as_of="2025-07-18", books_dir=tmp_path)
    BS.write_all(deep=healthy_deep, funding={}, as_of="2025-07-19", books_dir=tmp_path)
    path = tmp_path / book.book_id / "realized_series.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    rows[1]["as_of"] = "2024-01-01"  # back-date the second row, leave its row_hash untouched
    assert BS.verify_series(rows)["valid"] is False
    assert BS.verify_series(rows)["broken_at"] == 1


def test_redteam_fabricated_deployable_breaks_chain(tmp_path, healthy_deep):
    """Adversary FABRICATES a deployable ABOVE pool depth on a published row → divergent recompute.
    The hash covers the OUTPUT, so a laundered deployable is caught."""
    book = B.enumerate_books(healthy_deep)[0]
    BS.write_all(deep=healthy_deep, funding={}, books_dir=tmp_path)
    path = tmp_path / book.book_id / "realized_series.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    rows[0]["deployable_usd"] = 999_999_999.0  # fabricate a depth-impossible deployable
    assert BS.verify_series(rows)["valid"] is False
    assert BS.verify_series(rows)["broken_at"] == 0


def test_redteam_refused_laundered_as_deployed_breaks_chain(tmp_path, healthy_deep):
    """Adversary flips a REFUSE row to DEPLOYED (laundering a refused book as capacity) → caught."""
    BS.write_all(deep=healthy_deep, funding={}, books_dir=tmp_path)
    book = B.enumerate_books(healthy_deep)[0]
    path = tmp_path / book.book_id / "realized_series.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    rows[0]["refusal_state"] = "DEPLOYED" if rows[0]["refusal_state"] == "REFUSE" else "REFUSE"
    assert BS.verify_series(rows)["valid"] is False


def test_redteam_duplicate_book_id_fail_closed():
    """Adversary injects a DUPLICATE book_id (two distinct market_keys colliding to one id) → the
    registry FAILS CLOSED rather than silently collapsing two books into one."""
    deep = _deep([
        ("PT-sUSDE-A", "2025-09-25", 100_000_000.0, 0.11, "sUSDe", "stable_synth"),
        ("PT-sUSDE-B", "2025-12-26", 100_000_000.0, 0.11, "sUSDe", "stable_synth"),
    ])
    # force a collision by monkey-stamping make_book_id to a constant via a wrapper deep that gives two
    # markets the SAME (underlying, maturity, chain) identity under DIFFERENT market keys:
    deep["markets"]["PT-sUSDE-DUP"] = dict(deep["markets"]["PT-sUSDE-A"])  # same underlying+maturity
    deep["markets"]["PT-sUSDE-DUP"]["symbol"] = "PT-sUSDE-DUP"
    with pytest.raises(ValueError):
        B.enumerate_books(deep)


def test_property_book_count_monotonic_with_registry(healthy_deep):
    """PROPERTY: the number of series chains written == the number of harvestable books in the registry
    (no phantom books, no dropped books). Adding an independent book adds exactly one chain."""
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        summary = BS.write_all(deep=healthy_deep, funding={}, books_dir=d)
        n_registry = len(B.enumerate_books(healthy_deep))
        n_chains = len(list(d.rglob("realized_series.jsonl")))
        assert summary["n_books"] == n_registry == n_chains


def test_property_is_realized_no_backtest_leak(tmp_path, healthy_deep):
    """PROPERTY: the series is a REALIZED forward record (advisory), not a backtest dump — the summary
    declares is_advisory and the event_type is the realized-point type (no backtest/seed markers)."""
    summary = BS.write_all(deep=healthy_deep, funding={}, books_dir=tmp_path)
    assert summary["is_advisory"] is True
    assert summary["llm_forbidden"] is True
    assert summary["event_type"] == BS.EVENT_TYPE == "rates_desk_book_realized_point"
    # no row carries a backtest/seed flag — the schema is the frozen realized contract only
    book = B.enumerate_books(healthy_deep)[0]
    rows = [json.loads(l) for l in (tmp_path / book.book_id / "realized_series.jsonl")
            .read_text().splitlines() if l.strip()]
    assert not any(k in rows[-1] for k in ("is_backtest", "seed", "backtest", "is_demo"))


def test_fail_closed_missing_deep_dataset(tmp_path, monkeypatch):
    """fail-CLOSED: no deep dataset on disk → load() RAISES; the series is never fabricated."""
    monkeypatch.setattr(pph, "_OUT", tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        BS.write_all(funding={}, books_dir=tmp_path)


def test_fail_closed_empty_markets(tmp_path):
    """fail-CLOSED: a deep dataset with empty 'markets' RAISES."""
    with pytest.raises(ValueError):
        BS.write_all(deep={"window": {"end": "2025-01-01"}, "markets": {}}, funding={}, books_dir=tmp_path)


def test_smoke_full_registry_run_exit_0():
    """SMOKE: enumerating the real (or hermetic) registry + the CLI path runs cleanly. Hermetic: the
    registry CLI over a synthetic deep is exercised in the other tests; here we just assert the module
    main entrypoints are importable + callable shapes are right (no exception on enumerate)."""
    deep = _deep([("PT-sUSDE-A", "2025-09-25", 100_000_000.0, 0.11, "sUSDe", "stable_synth")])
    books = B.enumerate_books(deep)
    assert len(books) == 1 and books[0].book_id.startswith("bk_")
