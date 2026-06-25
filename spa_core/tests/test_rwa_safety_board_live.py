"""
spa_core/tests/test_rwa_safety_board_live.py — RWA Collateral Safety Board PRODUCTIONIZATION tests.

Mirrors test_refusal_engine.py's production-contract coverage for the §SPA-RRB de-risk, now wired
as a LIVE DAILY ADVISORY engine (CLI + API + launchd agent):
  - the single-run CLI (`python3 -m spa_core.strategy_lab.rwa_backstop.safety_board`) produces a
    structurally-valid board JSON written atomically
  - the /api/rwa-safety-board endpoint serves the board VERBATIM and degrades gracefully (empty
    payload, not an error) when the file is missing — mirroring /api/refusal
  - the launchd agent invocation path is well-formed: plist points at the same module/CLI, is
    registered in install_all_agents.sh, and the module exposes a `main()` returning an int

These tests are hermetic (a FakeFetcher injects /pools payloads — no network) and deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import plistlib
from pathlib import Path

from spa_core.strategy_lab.rwa_backstop.collateral_registry import CollateralAsset
from spa_core.strategy_lab.rwa_backstop import safety_board as sb

_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude


# ── hermetic fixtures (mirror test_rwa_backstop.py) ────────────────────────────────────────────
def _pools_payload(pools):
    return {"status": "success", "data": pools}


def _dex_pool(symbol, tvl, project="uniswap-v3"):
    return {"project": project, "chain": "Ethereum", "symbol": symbol, "tvlUsd": tvl}


class _FakeFetcher:
    """url -> json. Returns the configured /pools payload regardless of URL (no network)."""
    def __init__(self, payload):
        self._payload = payload

    def __call__(self, url):
        return self._payload


def _transferable(symbol, contract="0xabc", documented=True):
    return CollateralAsset(
        symbol=symbol, issuer="Test Issuer", chain="ethereum", asset_class="tokenized_tbill",
        token_contract=contract, transfer_restricted=False,
        redemption_delay_days=2.0, redemption_fee_bps=0.0, min_redemption_usd=0.0,
        redemption_documented=documented,
    )


def _permissioned(symbol, documented=True):
    return CollateralAsset(
        symbol=symbol, issuer="Test Issuer", chain="ethereum", asset_class="tokenized_mmf",
        token_contract="0xdef", transfer_restricted=True,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=250_000.0,
        redemption_documented=documented,
    )


def _no_exit(symbol):
    return CollateralAsset(
        symbol=symbol, issuer="Test Issuer", chain="ethereum", asset_class="tokenized_mmf",
        token_contract=None, transfer_restricted=True,
        redemption_delay_days=2.0, redemption_fee_bps=0.0, min_redemption_usd=100_000.0,
        redemption_documented=False,
    )


def _mixed_assets():
    return [
        _transferable("DEEP", contract="0xabc"),   # deep DEX → LIQUID
        _permissioned("BUIDL", documented=True),    # restricted but redeemable → REDEMPTION_ONLY
        _no_exit("STAC"),                           # nothing → UNSAFE
    ]


# ── 1. the CLI run produces a valid board JSON (atomic, structurally complete) ─────────────────
def test_cli_run_produces_valid_board_json(tmp_path):
    """build_report(write=True) — the exact path main() drives — writes a re-readable, valid board
    with the full productionization shape and the right per-asset verdicts."""
    out = tmp_path / "rwa_safety_board.json"
    deep_pools = [_dex_pool("DEEP-USDC", tvl=5_000_000_000.0)]
    report = sb.build_report(
        write=True, fetcher=_FakeFetcher(_pools_payload(deep_pools)),
        out_path=out, assets=_mixed_assets(),
    )

    # file written and re-readable as valid JSON with the same shape
    on_disk = json.loads(out.read_text())
    assert on_disk == report
    assert on_disk["model"] == "rwa_backstop_liquidation_nav"
    assert on_disk["advisory"] is True
    assert on_disk["research_only"] is True
    assert on_disk["llm_forbidden"] is True
    for key in ("generated_at", "verdict_counts", "assets", "thesis_confirmed",
                "n_assets", "max_marketing_vs_liq_gap_pct_1m", "data_caveats"):
        assert key in on_disk

    # every asset carries a verdict from the closed set + a marketing-vs-LiqNAV gap field
    valid = {sb.LIQUID, sb.THIN, sb.REDEMPTION_ONLY, sb.UNSAFE}
    for a in on_disk["assets"]:
        assert a["verdict"] in valid
        assert "marketing_vs_liq_gap_pct_1m" in a

    by_sym = {a["symbol"]: a for a in on_disk["assets"]}
    assert by_sym["DEEP"]["verdict"] == sb.LIQUID
    assert by_sym["BUIDL"]["verdict"] == sb.REDEMPTION_ONLY
    assert by_sym["STAC"]["verdict"] == sb.UNSAFE
    # the headline thesis number: the unsafe asset is materially below marketing NAV at $1M
    assert by_sym["STAC"]["marketing_vs_liq_gap_pct_1m"] is not None
    assert by_sym["STAC"]["marketing_vs_liq_gap_pct_1m"] > 0.0


def test_cli_main_callable_returns_int(monkeypatch, tmp_path):
    """The module exposes a main() (the agent entrypoint) that returns an int exit code, and does
    NOT raise on the happy path. Patched to a hermetic fetcher + tmp output (no network / live file)."""
    out = tmp_path / "rwa_safety_board.json"
    deep_pools = [_dex_pool("DEEP-USDC", tvl=5_000_000_000.0)]
    monkeypatch.setattr(sb, "DEFAULT_OUT", out)

    orig_build = sb.build_report

    def _hermetic_build(*a, **k):
        k.setdefault("fetcher", _FakeFetcher(_pools_payload(deep_pools)))
        k.setdefault("assets", _mixed_assets())
        return orig_build(*a, **k)

    monkeypatch.setattr(sb, "build_report", _hermetic_build)
    rc = sb.main()
    assert rc == 0
    assert out.exists()
    assert json.loads(out.read_text())["model"] == "rwa_backstop_liquidation_nav"


# ── 2. API endpoint shape (verbatim + graceful) ────────────────────────────────────────────────
def test_api_endpoint_serves_board_verbatim_and_graceful(monkeypatch, tmp_path):
    """GET /api/rwa-safety-board returns the file VERBATIM, and an empty (not error) payload when
    the file is missing — mirroring /api/refusal."""
    try:
        from fastapi.testclient import TestClient
    except Exception:
        import pytest
        pytest.skip("fastapi not installed in this env")

    from spa_core.api import server

    # point the server's data dir at a temp dir we control
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path, raising=False)
    client = TestClient(server.app)

    # (a) missing file → graceful empty payload, HTTP 200, advisory shape
    r = client.get("/api/rwa-safety-board")
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "rwa_backstop_liquidation_nav"
    assert body["advisory"] is True
    assert body["assets"] == []

    # (b) real board on disk → served VERBATIM
    board = sb.build_report(
        write=True, fetcher=_FakeFetcher(_pools_payload([_dex_pool("DEEP-USDC", 5e9)])),
        out_path=tmp_path / "rwa_safety_board.json", assets=_mixed_assets(),
    )
    r2 = client.get("/api/rwa-safety-board")
    assert r2.status_code == 200
    assert r2.json() == board


def test_api_route_registered():
    """The route is registered on the app even if TestClient/uvicorn-stack is unavailable."""
    from spa_core.api import server
    paths = {getattr(r, "path", None) for r in server.app.routes}
    assert "/api/rwa-safety-board" in paths


# ── 3. agent invocation path (plist + install registration) ────────────────────────────────────
def test_launchd_plist_invokes_the_cli_module():
    """The launchd plist runs miniconda python on the same module the CLI exposes, logs to
    logs/rwa_safety_board.{log,err}, and RunAtLoad — mirroring com.spa.refusal."""
    plist = _ROOT / "scripts" / "com.spa.rwa_safety_board.plist"
    assert plist.exists()
    with open(plist, "rb") as fh:
        d = plistlib.load(fh)
    assert d["Label"] == "com.spa.rwa_safety_board"
    args = d["ProgramArguments"]
    assert args[-3:] == ["-m", "spa_core.strategy_lab.rwa_backstop.safety_board"] or \
        args[1:] == ["-m", "spa_core.strategy_lab.rwa_backstop.safety_board"]
    assert "python3" in args[0]
    assert d.get("RunAtLoad") is True
    assert d["StandardOutPath"].endswith("logs/rwa_safety_board.log")
    assert d["StandardErrorPath"].endswith("logs/rwa_safety_board.err")
    # daily cadence
    assert "StartCalendarInterval" in d


def test_agent_registered_in_install_script():
    """install_all_agents.sh installs the safety-board agent (so it survives a full reinstall)."""
    txt = (_ROOT / "scripts" / "install_all_agents.sh").read_text()
    assert "com.spa.rwa_safety_board.plist" in txt
    assert "com.spa.rwa_safety_board" in txt
