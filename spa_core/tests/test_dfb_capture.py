"""test_dfb_capture.py — the STANDING DFB capture agent: persistence + on-standard + idempotency.

Month-1 gate-PASSED the dfb_capture agent but never PERSISTED it (it would be lost on reboot).
Lane-2 Month-3 makes it standing. Three verifications:

  • PROPERTY  — the plist is on the STABLE-AGENT STANDARD (bash-wrapper ProgramArguments, NOT a
                direct python -m → no exit-78; /tmp logs, NOT ~/Documents → no TCC exit-78); the
                agent is registered in install_all_agents.sh so a clean reinstall re-persists it.
  • RED-TEAM  — re-running the capture for the SAME UTC day is a NO-OP on the history chain
                (idempotent), so a KeepAlive/retried/double-run agent never double-appends or
                corrupts the scarce refusal-state series.
  • SMOKE     — one capture tick over a fixture overlay appends exactly one record per pool,
                proof-chained and verifiable.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in (str(_SPA_CORE), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from spa_core.dfb import history as dfb_history  # noqa: E402
from spa_core.dfb import risk_overlay  # noqa: E402

_SCRIPTS = _PROJECT_ROOT / "scripts"
_LAUNCHD = _PROJECT_ROOT / "launchd"
_INSTALL = _SCRIPTS / "install_all_agents.sh"


def _plist_path() -> Path:
    """The committed plist (scripts/ is the install-script convention; launchd/ is the original)."""
    for cand in (_SCRIPTS / "com.spa.dfb_capture.plist", _LAUNCHD / "com.spa.dfb_capture.plist"):
        if cand.exists():
            return cand
    pytest.skip("com.spa.dfb_capture.plist not found")


# ── PROPERTY: persistence + on-standard ───────────────────────────────────────
def test_dfb_capture_in_install_script():
    """The agent is registered in install_all_agents.sh (re-persisted on a clean reinstall)."""
    assert _INSTALL.exists(), "install_all_agents.sh missing"
    txt = _INSTALL.read_text(encoding="utf-8")
    assert "com.spa.dfb_capture" in txt, "dfb_capture not registered in install_all_agents.sh"
    assert "com.spa.dfb_capture.plist" in txt


def test_dfb_capture_plist_uses_bash_wrapper_not_direct_python():
    """STABLE-AGENT STANDARD (CLAUDE.md rule #11): ProgramArguments must be the /bin/bash wrapper,
    never a direct miniconda python (which launchd cannot exec → exit 78)."""
    pl = plistlib.loads(_plist_path().read_bytes())
    args = pl.get("ProgramArguments")
    assert isinstance(args, list) and args, "ProgramArguments missing/empty"
    assert args[0] == "/bin/bash", f"first arg must be /bin/bash, got {args[0]!r}"
    assert any("agent_dfb_capture.sh" in str(a) for a in args), "must invoke the bash wrapper"
    # No direct python exec anywhere in ProgramArguments.
    assert not any("miniconda" in str(a) or a == "-m" for a in args), \
        "ProgramArguments must NOT exec miniconda python / -m directly (exit-78 hazard)"


def test_dfb_capture_plist_logs_to_tmp_not_documents():
    """STABLE-AGENT STANDARD: launchd Std*Path must be /tmp (TCC blocks ~/Documents → exit 78)."""
    pl = plistlib.loads(_plist_path().read_bytes())
    for key in ("StandardOutPath", "StandardErrorPath"):
        p = pl.get(key, "")
        assert p.startswith("/tmp/"), f"{key} must be under /tmp/, got {p!r}"
        assert "/Documents/" not in p


def test_dfb_capture_wrapper_targets_paper_dfb():
    """The bash wrapper runs the capture entrypoint (spa_core.dfb.paper_dfb)."""
    wrapper = _SCRIPTS / "agent_dfb_capture.sh"
    assert wrapper.exists(), "agent_dfb_capture.sh missing"
    txt = wrapper.read_text(encoding="utf-8")
    assert "spa_core.dfb.paper_dfb" in txt


# ── RED-TEAM: idempotency (no double-append on a same-day re-run) ──────────────
def test_dfb_capture_idempotent_same_utc_day(tmp_path):
    pool = _make_pool()
    ov = risk_overlay.overlay(pool, risk_override=_par_risk(pool.asset, pool.as_of))
    r1 = dfb_history.capture_pool(ov, "2026-06-30", data_dir=tmp_path)
    assert r1["appended"] is True
    r2 = dfb_history.capture_pool(ov, "2026-06-30", data_dir=tmp_path)
    assert r2["appended"] is False, "same UTC day must be a NO-OP (idempotent)"
    rows = dfb_history.read_history(pool.pool_id, data_dir=tmp_path)
    assert len(rows) == 1, "double-run must not double-append the scarce series"
    assert dfb_history.verify_history(pool.pool_id, data_dir=tmp_path)["valid"] is True


# ── SMOKE: one tick appends one verifiable record per pool ────────────────────
def test_dfb_capture_appends_one_verifiable_record(tmp_path):
    pool = _make_pool()
    ov = risk_overlay.overlay(pool, risk_override=_par_risk(pool.asset, pool.as_of))
    res = dfb_history.capture_pool(ov, "2026-06-29", data_dir=tmp_path)
    assert res["appended"] is True
    v = dfb_history.verify_history(pool.pool_id, data_dir=tmp_path)
    assert v["valid"] is True and v["length"] == 1


# ── fixtures ──────────────────────────────────────────────────────────────────
def _make_pool():
    from spa_core.dfb import Pool
    return Pool(
        pool_id="cap-test-pool", protocol="aave_v3", chain="Ethereum", asset="USDC",
        tier="T1", apy_base=3.0, apy_reward=0.0, apy_total=3.0, tvl_usd=5e7,
        il_risk="none", exposure="single", source="test", as_of="2026-06-30",
    )


def _par_risk(asset, as_of):
    from decimal import Decimal
    from spa_core.strategy_lab.rates_desk.contracts import D0, UnderlyingRisk
    return UnderlyingRisk(
        underlying=asset.lower(), as_of=as_of,
        nav_redemption_value=Decimal("1"), market_price=Decimal("1"),
        peg_distance=D0, peg_vol_30d=D0, redemption_sla_seconds=0,
        reserve_fund_ratio=D0, funding_neg_frac_90d=D0,
        oracle_kind="chainlink", oracle_staleness_seconds=0,
        nested_protocol_count=0, top_borrower_share=D0,
    )
