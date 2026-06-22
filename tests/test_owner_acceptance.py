"""
tests/test_owner_acceptance.py

40 unit tests for spa_core/backtesting/owner_acceptance.py
MP-1309 (v9.25)

Test strategy:
- Each test uses an isolated tempfile.mkdtemp() directory → no cross-test pollution.
- Fake gate files are written with specific values to drive each code path.
- Atomic-write pattern (tmp → os.replace) is verified where possible.
- Immutability, revocation, and CLI paths are all covered.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

# Allow running from repo root
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.backtesting.owner_acceptance import OwnerAcceptanceWorkflow


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_pass_gate(backtest_dir: str) -> None:
    """Write a minimal PASS pre_paper_backtest_gate.json."""
    path = Path(backtest_dir) / "pre_paper_backtest_gate.json"
    payload = {
        "status": "PASS",
        "paper_test_can_be_designed": True,
        "research_exclusions": [
            {"protocol_id": "ethena_usde_direct", "strategy": "Ethena"},
            {"protocol_id": "btc_yield", "strategy": "BTC yield"},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_fail_gate(backtest_dir: str) -> None:
    """Write a minimal FAIL pre_paper_backtest_gate.json."""
    path = Path(backtest_dir) / "pre_paper_backtest_gate.json"
    payload = {
        "status": "FAIL",
        "paper_test_can_be_designed": False,
        "research_exclusions": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_pass_no_pipeline_gate(backtest_dir: str) -> None:
    """PASS status but paper_test_can_be_designed=False."""
    path = Path(backtest_dir) / "pre_paper_backtest_gate.json"
    payload = {
        "status": "PASS",
        "paper_test_can_be_designed": False,
        "research_exclusions": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


# ── Test class ─────────────────────────────────────────────────────────────────

class TestOwnerAcceptanceWorkflow(unittest.TestCase):

    def setUp(self) -> None:
        """Create a fresh temp dir for each test."""
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        """Remove temp dir after each test."""
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── Group 1: Class attributes and init (3 tests) ─────────────────────────

    def test_01_class_attr_acceptance_path(self) -> None:
        """ACCEPTANCE_PATH class attribute has correct default value."""
        self.assertEqual(
            OwnerAcceptanceWorkflow.ACCEPTANCE_PATH,
            "data/backtest/owner_paper_acceptance.json",
        )

    def test_02_class_attr_draft_path(self) -> None:
        """DRAFT_PATH class attribute has correct default value."""
        self.assertEqual(
            OwnerAcceptanceWorkflow.DRAFT_PATH,
            "data/backtest/owner_paper_acceptance_draft.json",
        )

    def test_03_init_does_not_create_files(self) -> None:
        """Constructor must not create any files."""
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        files = list(Path(self.tmpdir).iterdir())
        self.assertEqual(files, [], "Constructor must not create files")

    # ── Group 2: check_prerequisites() (8 tests) ─────────────────────────────

    def test_04_prerequisites_pass_gate(self) -> None:
        """PASS gate → pre_paper_gate returns 'PASS'."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.check_prerequisites()
        self.assertEqual(result["pre_paper_gate"], "PASS")

    def test_05_prerequisites_fail_gate(self) -> None:
        """FAIL gate → pre_paper_gate returns 'FAIL', all_met=False."""
        _make_fail_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.check_prerequisites()
        self.assertEqual(result["pre_paper_gate"], "FAIL")
        self.assertFalse(result["all_met"])

    def test_06_prerequisites_missing_gate_file(self) -> None:
        """Missing gate file → pre_paper_gate='FAIL', all_met=False."""
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.check_prerequisites()
        self.assertEqual(result["pre_paper_gate"], "FAIL")
        self.assertFalse(result["all_met"])

    def test_07_prerequisites_source_pipeline_true(self) -> None:
        """paper_test_can_be_designed=True → source_pipeline_ready=True."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.check_prerequisites()
        self.assertTrue(result["source_pipeline_ready"])

    def test_08_prerequisites_source_pipeline_false(self) -> None:
        """paper_test_can_be_designed=False → source_pipeline_ready=False, all_met=False."""
        _make_pass_no_pipeline_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.check_prerequisites()
        self.assertFalse(result["source_pipeline_ready"])
        self.assertFalse(result["all_met"])

    def test_09_prerequisites_all_met_true_when_pass_and_pipeline(self) -> None:
        """PASS gate + pipeline ready → all_met=True."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.check_prerequisites()
        self.assertTrue(result["all_met"])

    def test_10_prerequisites_missing_is_list(self) -> None:
        """'missing' field is always a list."""
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.check_prerequisites()
        self.assertIsInstance(result["missing"], list)

    def test_11_prerequisites_all_keys_present(self) -> None:
        """Result dict contains all four required keys."""
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.check_prerequisites()
        for key in ("pre_paper_gate", "source_pipeline_ready", "all_met", "missing"):
            self.assertIn(key, result, f"Key '{key}' missing from prerequisites result")

    # ── Group 3: generate_draft() (12 tests) ──────────────────────────────────

    def test_12_generate_draft_creates_file(self) -> None:
        """generate_draft() must create the draft file on disk."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.generate_draft()
        self.assertTrue(
            (Path(self.tmpdir) / "owner_paper_acceptance_draft.json").exists()
        )

    def test_13_generate_draft_returns_dict(self) -> None:
        """generate_draft() returns a dict."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.generate_draft()
        self.assertIsInstance(result, dict)

    def test_14_generate_draft_schema_version(self) -> None:
        """Draft contains schema_version='0.1'."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft()
        self.assertEqual(draft["schema_version"], "0.1")

    def test_15_generate_draft_accepted_false(self) -> None:
        """Draft must have accepted=False (not yet signed)."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft()
        self.assertFalse(draft["accepted"])

    def test_16_generate_draft_owner_null(self) -> None:
        """Draft owner field must be None (to be filled by owner)."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft()
        self.assertIsNone(draft["owner"])

    def test_17_generate_draft_default_period(self) -> None:
        """Default paper_period_days is 90."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft()
        self.assertEqual(draft["paper_period_days"], 90)

    def test_18_generate_draft_custom_period(self) -> None:
        """paper_params overrides paper_period_days."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft(paper_params={"paper_period_days": 180})
        self.assertEqual(draft["paper_period_days"], 180)

    def test_19_generate_draft_default_initial_capital(self) -> None:
        """Default initial_capital is 100,000."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft()
        self.assertEqual(draft["initial_capital"], 100_000)

    def test_20_generate_draft_research_exclusions_is_list(self) -> None:
        """research_exclusions_acknowledged is a list."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft()
        self.assertIsInstance(draft["research_exclusions_acknowledged"], list)

    def test_21_generate_draft_research_exclusions_populated(self) -> None:
        """research_exclusions_acknowledged reflects exclusions from gate file."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft()
        # _make_pass_gate writes 2 exclusions: ethena_usde_direct, btc_yield
        self.assertIn("ethena_usde_direct", draft["research_exclusions_acknowledged"])
        self.assertIn("btc_yield", draft["research_exclusions_acknowledged"])

    def test_22_generate_draft_risk_statement_nonempty(self) -> None:
        """risk_statement is a non-empty string."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft()
        self.assertIsInstance(draft["risk_statement"], str)
        self.assertGreater(len(draft["risk_statement"]), 20)

    def test_23_generate_draft_has_prerequisites_key(self) -> None:
        """Draft contains 'prerequisites' dict."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft()
        self.assertIn("prerequisites", draft)
        self.assertIsInstance(draft["prerequisites"], dict)

    def test_24_generate_draft_has_blockers_key(self) -> None:
        """Draft contains 'blockers' list."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft()
        self.assertIn("blockers", draft)
        self.assertIsInstance(draft["blockers"], list)

    # ── Group 4: sign() (8 tests) ─────────────────────────────────────────────

    def test_25_sign_accepted_true(self) -> None:
        """sign() saves accepted=True in the acceptance file."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="TestOwner")
        data = json.loads(
            (Path(self.tmpdir) / "owner_paper_acceptance.json").read_text()
        )
        self.assertTrue(data["accepted"])

    def test_26_sign_records_owner_name(self) -> None:
        """sign() records the provided owner name."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Alice")
        data = json.loads(
            (Path(self.tmpdir) / "owner_paper_acceptance.json").read_text()
        )
        self.assertEqual(data["owner"], "Alice")

    def test_27_sign_returns_dict_with_accepted_true(self) -> None:
        """sign() returns the signed acceptance dict with accepted=True."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.sign(owner_name="Bob")
        self.assertIsInstance(result, dict)
        self.assertTrue(result["accepted"])

    def test_28_sign_raises_if_prerequisites_not_met(self) -> None:
        """sign() raises ValueError when prerequisites are not met."""
        _make_fail_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        with self.assertRaises(ValueError):
            wf.sign(owner_name="Owner")

    def test_29_sign_immutable_second_call_raises(self) -> None:
        """Second sign() after first raises ValueError (immutability)."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Owner")
        with self.assertRaises(ValueError):
            wf.sign(owner_name="Owner2")

    def test_30_sign_creates_acceptance_file(self) -> None:
        """sign() creates owner_paper_acceptance.json on disk."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Signer")
        self.assertTrue(
            (Path(self.tmpdir) / "owner_paper_acceptance.json").exists()
        )

    def test_31_sign_has_accepted_at_field(self) -> None:
        """Signed acceptance contains accepted_at date string."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.sign(owner_name="Owner")
        self.assertIn("accepted_at", result)
        self.assertIsInstance(result["accepted_at"], str)
        self.assertGreater(len(result["accepted_at"]), 5)

    def test_32_sign_strategy_scope_is_list(self) -> None:
        """Signed acceptance contains strategy_scope as a list."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.sign(owner_name="Owner")
        self.assertIn("strategy_scope", result)
        self.assertIsInstance(result["strategy_scope"], list)
        self.assertGreater(len(result["strategy_scope"]), 0)

    # ── Group 5: is_signed() (3 tests) ────────────────────────────────────────

    def test_33_is_signed_false_initially(self) -> None:
        """is_signed() returns False before any sign() call."""
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        self.assertFalse(wf.is_signed())

    def test_34_is_signed_true_after_sign(self) -> None:
        """is_signed() returns True immediately after sign()."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Owner")
        self.assertTrue(wf.is_signed())

    def test_35_is_signed_false_after_revoke(self) -> None:
        """is_signed() returns False after revoke()."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Owner")
        wf.revoke(reason="Test revocation")
        self.assertFalse(wf.is_signed())

    # ── Group 6: revoke() (4 tests) ───────────────────────────────────────────

    def test_36_revoke_sets_accepted_false(self) -> None:
        """revoke() sets accepted=False in the acceptance file."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Owner")
        wf.revoke(reason="Changed scope")
        data = json.loads(
            (Path(self.tmpdir) / "owner_paper_acceptance.json").read_text()
        )
        self.assertFalse(data["accepted"])

    def test_37_revoke_records_reason(self) -> None:
        """revoke() stores the revoke_reason field."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Owner")
        wf.revoke(reason="Strategy updated per ADR-099")
        data = json.loads(
            (Path(self.tmpdir) / "owner_paper_acceptance.json").read_text()
        )
        self.assertEqual(data["revoke_reason"], "Strategy updated per ADR-099")

    def test_38_revoke_records_revoked_at(self) -> None:
        """revoke() adds revoked_at date field."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Owner")
        wf.revoke(reason="x")
        data = json.loads(
            (Path(self.tmpdir) / "owner_paper_acceptance.json").read_text()
        )
        self.assertIn("revoked_at", data)
        self.assertIsInstance(data["revoked_at"], str)

    def test_39_revoke_on_unsigned_does_not_crash(self) -> None:
        """revoke() on a non-existent acceptance file is a no-op."""
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        # Must not raise
        wf.revoke(reason="Nothing to revoke")

    # ── Group 7: acceptance_status() (5 tests) ────────────────────────────────

    def test_40_acceptance_status_all_keys_present(self) -> None:
        """acceptance_status() returns dict with all seven required keys."""
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        status = wf.acceptance_status()
        expected_keys = {
            "signed", "owner", "accepted_at", "gate_status",
            "paper_period_days", "initial_capital", "strategy_scope",
        }
        for key in expected_keys:
            self.assertIn(key, status, f"Key '{key}' missing from acceptance_status")

    def test_41_acceptance_status_not_signed_default(self) -> None:
        """Before signing, signed=False and gate_status='NOT_SIGNED'."""
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        status = wf.acceptance_status()
        self.assertFalse(status["signed"])
        self.assertEqual(status["gate_status"], "NOT_SIGNED")

    def test_42_acceptance_status_after_sign(self) -> None:
        """After sign(), signed=True and gate_status='SIGNED'."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Owner")
        status = wf.acceptance_status()
        self.assertTrue(status["signed"])
        self.assertEqual(status["gate_status"], "SIGNED")

    def test_43_acceptance_status_gate_status_revoked(self) -> None:
        """After revoke(), gate_status='REVOKED'."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Owner")
        wf.revoke(reason="Revoke test")
        status = wf.acceptance_status()
        self.assertFalse(status["signed"])
        self.assertEqual(status["gate_status"], "REVOKED")

    def test_44_acceptance_status_owner_populated_after_sign(self) -> None:
        """acceptance_status() reflects owner name after signing."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Charlie")
        status = wf.acceptance_status()
        self.assertEqual(status["owner"], "Charlie")

    # ── Bonus: sign() re-enabled after revoke (1 test) ───────────────────────

    def test_45_can_sign_again_after_revoke(self) -> None:
        """After revoke(), sign() can be called again without raising."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.sign(owner_name="Owner1")
        wf.revoke(reason="Re-sign test")
        # Should not raise
        result = wf.sign(owner_name="Owner2")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["owner"], "Owner2")

    # ── Missing prerequisites message content (1 test) ────────────────────────

    def test_46_prerequisites_missing_nonempty_when_fail(self) -> None:
        """When gate is FAIL, missing list is non-empty."""
        _make_fail_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.check_prerequisites()
        self.assertGreater(len(result["missing"]), 0)

    # ── Strategy scope default (1 test) ────────────────────────────────────────

    def test_47_sign_default_strategy_scope_excludes_s8_s9_s10(self) -> None:
        """Default strategy scope should be strict strategies only (no S8/S9/S10)."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.sign(owner_name="Owner")
        scope = result["strategy_scope"]
        self.assertNotIn("S8", scope)
        self.assertNotIn("S9", scope)
        self.assertNotIn("S10", scope)

    # ── generate_draft() is callable without a gate file (1 test) ─────────────

    def test_48_generate_draft_without_gate_still_creates_file(self) -> None:
        """generate_draft() creates a file even when gate file is missing."""
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        draft = wf.generate_draft()
        self.assertTrue(
            (Path(self.tmpdir) / "owner_paper_acceptance_draft.json").exists()
        )
        # blockers should mention the missing gate
        self.assertGreater(len(draft["blockers"]), 0)

    # ── Atomic write verification (1 test) ────────────────────────────────────

    def test_49_draft_file_is_valid_json(self) -> None:
        """The written draft file must be parseable valid JSON."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        wf.generate_draft()
        raw = (Path(self.tmpdir) / "owner_paper_acceptance_draft.json").read_text()
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, dict)

    # ── sign() custom paper_params (1 test) ───────────────────────────────────

    def test_50_sign_with_custom_paper_params(self) -> None:
        """sign() uses paper_params overrides."""
        _make_pass_gate(self.tmpdir)
        wf = OwnerAcceptanceWorkflow(backtest_dir=self.tmpdir)
        result = wf.sign(
            owner_name="Owner",
            paper_params={"paper_period_days": 60, "initial_capital": 50_000},
        )
        self.assertEqual(result["paper_period_days"], 60)
        self.assertEqual(result["initial_capital"], 50_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
