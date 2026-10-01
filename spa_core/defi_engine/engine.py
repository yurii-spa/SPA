"""spa_core/defi_engine/engine.py — assemble the Phase 1 foundation and publish it (ADR-532).

``build(data_dir, now)`` reads the three books and every canonical input, and returns two documents:

* ``status`` — the published DeFi engine status contract (P1-15): per book the gate, APY contract
  (gross/net), mechanic exposure, exit profile, loss budget and monitoring coverage; the tier
  census; and a flat list of advisory ``findings`` a reader can act on;
* ``passports`` — one Position Passport per held position of every book.

``publish(data_dir)`` writes both atomically to ``data/defi_engine/`` (invariant #5). Both files are
DERIVED artifacts: rebuilt from scratch each run, never read back as an input by anything.

**No money-path effect.** Nothing here is imported by the cycle, the allocator, RiskPolicy or a
gate; ``money_path_effect`` in the status says so and ``test_defi_engine.py::test_money_path_never_imports_the_engine`` keeps it
true. The cycles that call ``publish`` do so after their own book is written, inside a guard that
swallows nothing silently and never changes the cycle's result.

CLI::

    python3 -m spa_core.defi_engine              # build + print a summary (no write)
    python3 -m spa_core.defi_engine --run        # build + atomic write to data/defi_engine/

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.defi_engine import SCHEMA_VERSION, PASSPORT_SCHEMA_VERSION
from spa_core.defi_engine import apy_contract, books as B, coverage, exit_model, loss_budget, mechanics, tiers
from spa_core.defi_engine import package_status
from spa_core.defi_engine.passport import EVIDENCE_LEVEL, build_passport

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = _ROOT / "data"
OUT_DIRNAME = "defi_engine"


def _data_dir(data_dir: "Path | str | None") -> Path:
    """Resolved at CALL time through ``SPA_DATA_DIR`` (test isolation), else the repo's data/."""
    from spa_core.utils.data_dir import own_data_dir
    return Path(data_dir) if data_dir is not None else own_data_dir(DEFAULT_DATA_DIR)


def _code_version() -> Optional[str]:
    """sha256 (12 hex) over this package's own sources — what code BUILT the document.

    Not ``git rev-parse HEAD``: the production tree receives code by file sync and its git index
    lags origin by design (ADR-152), so HEAD there names a commit the code is not. Measured on the
    first production run: HEAD said ``aeaab8bdca3b`` while the code was origin ``f705a951``.
    """
    import hashlib
    try:
        h = hashlib.sha256()
        for f in sorted(Path(__file__).resolve().parent.glob("*.py")):
            h.update(f.name.encode())
            h.update(f.read_bytes())
        return h.hexdigest()[:12]
    except Exception:  # noqa: BLE001 — unreadable sources: the field is unmeasured, not faked
        return None


def build(data_dir: "Path | str | None" = None, now: Optional[datetime] = None) -> tuple[dict, dict]:
    ddir = _data_dir(data_dir)
    now = now or datetime.now(timezone.utc)
    books = B.load_books(ddir)
    snap = B.pool_snapshot(ddir)
    pools = snap["pools"]
    cov = coverage.coverage_report(books, ddir, now.timestamp())
    cov_rows = {(b, r["protocol"]): r for b, rows in cov["books"].items() for r in rows}

    findings: list[dict] = []
    book_docs: dict[str, dict] = {}
    passports: list[dict] = []
    for book_id in B.BOOK_IDS:
        book = books.get(book_id) or {"measured": False, "reason": "not loaded"}
        budget = loss_budget.book_budget(book_id, book)
        exits = exit_model.book_exit(book, pools)
        base, basis = exit_model.exposure_base(book) if book.get("measured") else (None, None)
        expo = (dict(mechanics.mechanic_exposure(book.get("positions") or [], base), share_basis=basis)
                if book.get("measured") else {"measured": False, "reason": book.get("reason")})
        book_docs[book_id] = {
            "measured": bool(book.get("measured")),
            "reason": book.get("reason"),
            "engine": book.get("engine"),
            "gate": book.get("gate"),
            "nav_usd": book.get("nav_usd"),
            "cash_usd": book.get("cash_usd"),
            "cash_reason": book.get("cash_reason"),
            "notional_minus_nav_usd": book.get("notional_minus_nav_usd"),
            "n_positions": len(book.get("positions") or []),
            "series_basis": book.get("series_basis"),
            "pre_fix_rows": book.get("pre_fix_rows"),
            "apy": apy_contract.book_contract(book),
            "mechanic_exposure": expo,
            "exit": {k: v for k, v in exits.items() if k != "positions"},
            "loss_budget": budget,
            "evidence_level": EVIDENCE_LEVEL,
        }
        for f in expo.get("findings") or []:
            findings.append({"book": book_id, "kind": "mechanic_cap", **f})
        if exits.get("measured") and not exits.get("policy_ok"):
            findings.append({"book": book_id, "kind": "exit_liquidity",
                             "share_illiquid": exits["share_illiquid"],
                             "max_illiquid_share": exits["max_illiquid_share"],
                             "positions": exits["illiquid_positions"]})
        if budget.get("bound_by_enforced_stop") is False:   # None (stop unknown) is not "unbound"
            findings.append({"book": book_id, "kind": "loss_budget_unbound",
                             "budget_pct": budget["budget_pct"],
                             "nearest_enforced_stop_pct": budget["nearest_enforced_stop_pct"]})
        if budget.get("status") in ("warn", "breach"):
            findings.append({"book": book_id, "kind": "loss_budget", "status": budget["status"]})
        for p in book.get("positions") or [] if book.get("measured") else []:
            row = cov_rows.get((book_id, p["protocol"]))
            passports.append(build_passport(book_id, book, p, pools, budget, row))
            if row and row["rate_watch"].get("status") == "shock":
                findings.append({"book": book_id, "kind": "rate_shock", "protocol": p["protocol"],
                                 **{k: row["rate_watch"][k] for k in ("ratio", "spot_apy_pct",
                                                                      "baseline_median_pct")}})
            stamp = p.get("stamped_delta_neutral")
            computed = mechanics.price_delta_neutral(p["protocol"])
            if stamp is not None and computed is not None and bool(stamp) != computed:
                findings.append({"book": book_id, "kind": "delta_neutral_stamp_wrong",
                                 "protocol": p["protocol"], "stamped": stamp, "computed": computed})

    census = tiers.census(ddir)
    for r in census["disagreements"]:
        if r["money_path"] and r["direction"] == "looser":
            findings.append({"kind": "tier_copy_looser_on_money_path", **r})

    generated = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = f"{generated}#{_code_version() or 'nogit'}"
    status = {
        "schema": SCHEMA_VERSION,
        "generated_at": generated,
        "run_id": run_id,
        "code_version": _code_version(),
        "code_version_basis": "sha256 of spa_core/defi_engine/*.py (not git HEAD: the prod index lags)",
        "adr": "ADR-532",
        "money_path_effect": "none — advisory derived view; RiskPolicy v1.0 is the only hard gate",
        "live_capital_usd": 0,
        "execution_mode": "paper",
        "pool_snapshot": {"measured": snap["measured"], "as_of": snap["as_of"], "reason": snap["reason"],
                          "n_pools": len(pools)},
        "books": book_docs,
        "apy_definitions": apy_contract.DEFINITIONS,
        "pool_apy": apy_contract.pool_contract(pools),
        "tier_authority": census,
        "coverage": {k: v for k, v in cov.items() if k != "books"},
        "mechanics": {"vocabulary": sorted(mechanics.MECHANICS), "parameter_status": mechanics.PARAMETER_STATUS},
        "n_passports": len(passports),
        "findings": findings,
        # ADR-533: the ONE read model of the three paper portfolios (site + Director read this)
        "packages": package_status.build_all(ddir, now)["packages"],
    }
    passport_doc = {"schema": PASSPORT_SCHEMA_VERSION, "generated_at": generated, "run_id": run_id,
                    "derived_from": "data/defi_engine/status.json inputs (rebuilt every run; never an input)",
                    "passports": passports}
    return status, passport_doc


def publish(data_dir: "Path | str | None" = None, now: Optional[datetime] = None) -> dict:
    """Write passports FIRST, then status: a reader that finds a status may trust that the
    passports with the same ``run_id`` exist. Two cycles publishing at once each write a complete,
    self-consistent pair; a mixed pair is detectable by ``run_id``."""
    from spa_core.utils.atomic import atomic_save

    ddir = _data_dir(data_dir)
    status, passports = build(ddir, now)
    out = ddir / OUT_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    atomic_save(passports, str(out / "passports.json"))
    atomic_save(status, str(out / "status.json"))
    return status


def publish_advisory(data_dir: "Path | str | None" = None) -> Optional[str]:
    """For the cycles: publish, and on failure RETURN the reason (the caller logs it).

    A failure here must never change a cycle's outcome, and must never be silent either: the
    caller prints the returned reason into its own log.
    """
    try:
        publish(data_dir)
        return None
    except Exception as exc:  # noqa: BLE001 — advisory layer; the caller logs the named reason
        return f"defi_engine publish failed: {type(exc).__name__}: {exc}"
