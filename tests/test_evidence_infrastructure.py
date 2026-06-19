"""
tests/test_evidence_infrastructure.py

MP-1426 (v10.42) — 25 tests for Evidence + Data Sources infrastructure.
Tests:
  - assess_data_sources() score >= 8
  - assess_evidence() with empty/init history → >= 10 pts
  - paper_evidence_history.json exists after init
  - Evidence pts grow with each completed_day tier
  - Data sources checks verified
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# ── Repo root on sys.path ──────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport, CategoryScore


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_report(tmp_dir: Path) -> GoLiveReadinessReport:
    return GoLiveReadinessReport(base_dir=str(tmp_dir))


def scaffold_minimal(tmp_dir: Path, completed_days: int = 0) -> None:
    """Write minimal data files for a standalone test repo."""
    data = tmp_dir / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "backtest").mkdir(parents=True, exist_ok=True)

    # evidence files
    paper_ev_days = [{"date": f"2026-06-{i:02d}"} for i in range(1, completed_days + 1)]
    (data / "paper_evidence.json").write_text(
        json.dumps({"days": paper_ev_days})
    )
    (data / "paper_evidence_history.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "initialized_at": "2026-06-19",
            "day_count": completed_days,
            "days": paper_ev_days,
            "total_evidence_points": float(completed_days),
            "status": "initialized",
        })
    )

    # analytics module stubs
    analytics = tmp_dir / "spa_core" / "analytics"
    analytics.mkdir(parents=True, exist_ok=True)
    (analytics / "evidence_auto_calculator.py").write_text(
        "# evidence_auto_calculator stub\nSCHEMA_VERSION = '1.0'\n"
    )
    (analytics / "t1_data_verifier.py").write_text("# t1 verifier stub\n")
    (analytics / "__init__.py").write_text("")

    # utils
    utils = tmp_dir / "spa_core" / "utils"
    utils.mkdir(parents=True, exist_ok=True)
    (utils / "defillama.py").write_text("# defillama stub\n")
    (utils / "__init__.py").write_text("")

    # promotion engine
    (tmp_dir / "promotion_engine.py").write_text("# stub\n")

    # source pipeline
    clean = {f"src_{i}": "clean_included" for i in range(8)}
    dirty = {f"dirty_{i}": "source_needed" for i in range(16)}
    (data / "backtest" / "source_pipeline.json").write_text(
        json.dumps({"sources": {**clean, **dirty}})
    )

    # other required files
    (data / "paper_trading_status.json").write_text(
        json.dumps({"virtual_capital": 100_000.0, "is_demo": False})
    )
    (data / "current_positions.json").write_text(
        json.dumps({"capital_usd": 100_000.0, "is_demo": False})
    )
    (data / "equity_curve_daily.json").write_text(json.dumps({"daily": []}))
    (data / "golive_status.json").write_text(
        json.dumps({"checks": {}, "blockers": []})
    )
    (data / "backtest" / "pre_paper_backtest_gate.json").write_text(
        json.dumps({"status": "PASS"})
    )
    (data / "backtest" / "paper_ready_gate.json").write_text(
        json.dumps({"status": "NOT_READY"})
    )


# ── Tests: paper_evidence_history.json ────────────────────────────────────────

class TestPaperEvidenceHistoryFile:
    """paper_evidence_history.json infrastructure."""

    def test_history_file_exists(self):
        path = REPO_ROOT / "data" / "paper_evidence_history.json"
        assert path.exists(), "data/paper_evidence_history.json must exist (MP-1426)"

    def test_history_file_valid_json(self):
        path = REPO_ROOT / "data" / "paper_evidence_history.json"
        data = json.load(open(path))
        assert isinstance(data, dict)

    def test_history_file_has_schema_version(self):
        data = json.load(open(REPO_ROOT / "data" / "paper_evidence_history.json"))
        assert data.get("schema_version") == "1.0"

    def test_history_file_has_days_list(self):
        data = json.load(open(REPO_ROOT / "data" / "paper_evidence_history.json"))
        assert "days" in data and isinstance(data["days"], list)

    def test_history_file_has_day_count(self):
        data = json.load(open(REPO_ROOT / "data" / "paper_evidence_history.json"))
        assert "day_count" in data

    def test_history_file_has_initialized_at(self):
        data = json.load(open(REPO_ROOT / "data" / "paper_evidence_history.json"))
        assert "initialized_at" in data

    def test_history_file_target_pts(self):
        data = json.load(open(REPO_ROOT / "data" / "paper_evidence_history.json"))
        assert data.get("target_pts", 0) == 30.0


# ── Tests: assess_evidence() ──────────────────────────────────────────────────

class TestAssessEvidence:
    """assess_evidence() scoring and infrastructure credits."""

    def test_assess_evidence_returns_category_score(self):
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        s = r.assess_evidence()
        assert isinstance(s, CategoryScore)

    def test_assess_evidence_max_score_is_25(self):
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        s = r.assess_evidence()
        assert s.max_score == 25.0

    def test_assess_evidence_name(self):
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        s = r.assess_evidence()
        assert s.name == "evidence"

    def test_assess_evidence_with_empty_history_ge_10(self):
        """With history initialized (even empty): >= 10 pts from infrastructure."""
        with tempfile.TemporaryDirectory() as tmp:
            scaffold_minimal(Path(tmp), completed_days=0)
            r = make_report(Path(tmp))
            s = r.assess_evidence()
            assert s.score >= 10.0, \
                f"Evidence with empty history must be >= 10, got {s.score}"

    def test_assess_evidence_without_history_gives_5(self):
        """Without paper_evidence_history.json: only +5 for calc exists."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            scaffold_minimal(tmp_p, completed_days=0)
            # Remove history file
            (tmp_p / "data" / "paper_evidence_history.json").unlink()
            r = make_report(tmp_p)
            s = r.assess_evidence()
            assert s.score == pytest.approx(5.0), \
                f"Without history, evidence should be 5.0 (calc only), got {s.score}"

    def test_assess_evidence_without_both_infra_gives_0(self):
        """Without calc AND without history: 0 pts infrastructure."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            scaffold_minimal(tmp_p, completed_days=0)
            (tmp_p / "data" / "paper_evidence_history.json").unlink()
            (tmp_p / "spa_core" / "analytics" / "evidence_auto_calculator.py").unlink()
            r = make_report(tmp_p)
            s = r.assess_evidence()
            assert s.score == pytest.approx(0.0), \
                f"No infra → 0 pts, got {s.score}"

    def test_assess_evidence_5_cycles_adds_5pts(self):
        """5 completed cycles → +5 pts on top of infrastructure."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            scaffold_minimal(tmp_p, completed_days=0)
            r0 = make_report(tmp_p)
            s0 = r0.assess_evidence()

            scaffold_minimal(tmp_p, completed_days=5)
            r5 = make_report(tmp_p)
            s5 = r5.assess_evidence()

            assert s5.score - s0.score == pytest.approx(5.0), \
                f"5 cycles should add 5 pts: {s0.score} → {s5.score}"

    def test_assess_evidence_10_cycles_adds_10pts(self):
        """10 completed cycles → +10 pts on top of infrastructure."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            scaffold_minimal(tmp_p, completed_days=0)
            r0 = make_report(tmp_p)
            s0 = r0.assess_evidence()

            scaffold_minimal(tmp_p, completed_days=10)
            r10 = make_report(tmp_p)
            s10 = r10.assess_evidence()

            assert s10.score - s0.score == pytest.approx(10.0)

    def test_assess_evidence_20_cycles_gives_25pts(self):
        """20+ completed cycles → max 25 pts (all tiers)."""
        with tempfile.TemporaryDirectory() as tmp:
            scaffold_minimal(Path(tmp), completed_days=20)
            r = make_report(Path(tmp))
            s = r.assess_evidence()
            assert s.score == pytest.approx(25.0)

    def test_assess_evidence_pts_grow_monotonically(self):
        """More cycles → more pts (monotone)."""
        scores = []
        for days in [0, 5, 10, 20]:
            with tempfile.TemporaryDirectory() as tmp:
                scaffold_minimal(Path(tmp), completed_days=days)
                r = make_report(Path(tmp))
                scores.append(r.assess_evidence().score)
        assert scores == sorted(scores), f"Scores should be non-decreasing: {scores}"

    def test_real_repo_evidence_score(self):
        """Real repo: evidence should be >= 10 (history initialized)."""
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        s = r.assess_evidence()
        assert s.score >= 10.0, f"Real repo evidence >= 10, got {s.score}"


# ── Tests: assess_data_sources() ──────────────────────────────────────────────

class TestAssessDataSources:
    """assess_data_sources() scoring and verified connections."""

    def test_assess_data_sources_returns_category_score(self):
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        s = r.assess_data_sources()
        assert isinstance(s, CategoryScore)

    def test_assess_data_sources_max_score_is_10(self):
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        s = r.assess_data_sources()
        assert s.max_score == 10.0

    def test_assess_data_sources_name(self):
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        s = r.assess_data_sources()
        assert s.name == "data_sources"

    def test_assess_data_sources_ge_8(self):
        """After MP-1426 verification: score >= 8/10."""
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        s = r.assess_data_sources()
        assert s.score >= 8.0, \
            f"Data sources score must be >= 8 after MP-1426 verification, got {s.score}"

    def test_defillama_client_gives_2pts(self):
        """defillama.py existence gives +2 pts."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            scaffold_minimal(tmp_p)
            r_with = make_report(tmp_p)
            s_with = r_with.assess_data_sources()

            (tmp_p / "spa_core" / "utils" / "defillama.py").unlink()
            r_without = make_report(tmp_p)
            s_without = r_without.assess_data_sources()

            assert s_with.score - s_without.score == pytest.approx(2.0)

    def test_t1_verifier_gives_2pts(self):
        """t1_data_verifier.py existence gives +2 pts."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            scaffold_minimal(tmp_p)
            r_with = make_report(tmp_p)
            s_with = r_with.assess_data_sources()

            (tmp_p / "spa_core" / "analytics" / "t1_data_verifier.py").unlink()
            r_without = make_report(tmp_p)
            s_without = r_without.assess_data_sources()

            assert s_with.score - s_without.score == pytest.approx(2.0)

    def test_promotion_engine_gives_2pts(self):
        """promotion_engine.py gives +2 pts."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            scaffold_minimal(tmp_p)
            r_with = make_report(tmp_p)
            s_with = r_with.assess_data_sources()

            (tmp_p / "promotion_engine.py").unlink()
            r_without = make_report(tmp_p)
            s_without = r_without.assess_data_sources()

            assert s_with.score - s_without.score == pytest.approx(2.0)

    def test_5_clean_sources_gives_2pts(self):
        """≥5 CLEAN sources → +2 pts."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            scaffold_minimal(tmp_p)
            r_with = make_report(tmp_p)
            s_with = r_with.assess_data_sources()

            # Remove clean sources → 0 CLEAN
            (tmp_p / "data" / "backtest" / "source_pipeline.json").write_text(
                json.dumps({"sources": {f"dirty_{i}": "source_needed" for i in range(10)}})
            )
            r_without = make_report(tmp_p)
            s_without = r_without.assess_data_sources()

            assert s_with.score - s_without.score == pytest.approx(2.0)

    def test_data_sources_in_categories(self):
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        names = [c.name for c in r._get_categories()]
        assert "data_sources" in names


# ── Tests: Total Score ────────────────────────────────────────────────────────

class TestTotalScoreAfterBothMPs:
    """After MP-1425 + MP-1426: total score >= 65."""

    def test_total_score_ge_65(self):
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        score = r.total_score()
        assert score >= 65.0, \
            f"Total score after MP-1425+MP-1426 must be >= 65, got {score}"

    def test_evidence_category_max_25(self):
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        cats = r._get_categories()
        ev = next(c for c in cats if c.name == "evidence")
        assert ev.max_score == 25.0

    def test_all_category_names_correct(self):
        r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
        names = [c.name for c in r._get_categories()]
        expected = {"gates", "evidence", "infrastructure", "financial", "data_sources", "documentation"}
        assert set(names) == expected
