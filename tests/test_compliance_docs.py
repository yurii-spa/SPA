"""
tests/test_compliance_docs.py
MP-1517 (v11.33): 15 tests verifying COMPLIANCE_POLICY.md and RISK_DISCLOSURE.md.
"""

import os
import unittest

DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
COMPLIANCE_PATH = os.path.join(DOCS_DIR, "COMPLIANCE_POLICY.md")
RISK_PATH = os.path.join(DOCS_DIR, "RISK_DISCLOSURE.md")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class TestCompliancePolicyExists(unittest.TestCase):
    """COMPLIANCE_POLICY.md existence and structure."""

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(COMPLIANCE_PATH),
                        "COMPLIANCE_POLICY.md must exist")

    def test_file_not_empty(self):
        self.assertGreater(os.path.getsize(COMPLIANCE_PATH), 200)

    def test_has_kyc_section(self):
        self.assertIn("KYC", _read(COMPLIANCE_PATH))

    def test_has_aml_section(self):
        self.assertIn("AML", _read(COMPLIANCE_PATH))

    def test_mentions_data_protection(self):
        self.assertIn("Data Protection", _read(COMPLIANCE_PATH))

    def test_mentions_gdpr(self):
        self.assertIn("GDPR", _read(COMPLIANCE_PATH))

    def test_mentions_bank_transfer(self):
        self.assertIn("bank transfer", _read(COMPLIANCE_PATH).lower())

    def test_mentions_annual_renewal(self):
        self.assertIn("Annual Renewal", _read(COMPLIANCE_PATH))


class TestRiskDisclosureExists(unittest.TestCase):
    """RISK_DISCLOSURE.md existence and structure."""

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(RISK_PATH),
                        "RISK_DISCLOSURE.md must exist")

    def test_file_not_empty(self):
        self.assertGreater(os.path.getsize(RISK_PATH), 200)

    def test_mentions_market_risk(self):
        self.assertIn("Market Risk", _read(RISK_PATH))

    def test_mentions_smart_contract_risk(self):
        self.assertIn("Smart Contract Risk", _read(RISK_PATH))

    def test_mentions_liquidity_risk(self):
        self.assertIn("Liquidity Risk", _read(RISK_PATH))

    def test_mentions_no_guarantee(self):
        content = _read(RISK_PATH).lower()
        self.assertIn("no guarantee", content)

    def test_mentions_regulatory_risk(self):
        self.assertIn("Regulatory Risk", _read(RISK_PATH))

    def test_compliance_cross_references_risk(self):
        """Compliance policy must reference the risk disclosure document."""
        compliance_content = _read(COMPLIANCE_PATH)
        self.assertIn("RISK_DISCLOSURE", compliance_content)


if __name__ == "__main__":
    unittest.main()
