"""
Tests for API docs and package structure — MP-1530 (v11.46).

15 tests covering:
  - spa_core/api/__init__.py exports (__all__)
  - docs/API_REFERENCE.md content & completeness
  - Module importability
  - Public vs protected surface
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_DOCS_DIR = _ROOT / "docs"
_API_REF = _DOCS_DIR / "API_REFERENCE.md"


# ── package exports ───────────────────────────────────────────────────────────

class TestPackageExports:
    def test_api_package_importable(self):
        mod = importlib.import_module("spa_core.api")
        assert mod is not None

    def test_all_contains_app(self):
        import spa_core.api as api_pkg
        assert "app" in api_pkg.__all__

    def test_all_contains_spa_api_client(self):
        import spa_core.api as api_pkg
        assert "SPAApiClient" in api_pkg.__all__

    def test_all_contains_api_auth(self):
        import spa_core.api as api_pkg
        assert "APIAuth" in api_pkg.__all__

    def test_all_contains_get_auth(self):
        import spa_core.api as api_pkg
        assert "get_auth" in api_pkg.__all__

    def test_spa_api_client_importable_from_package(self):
        from spa_core.api import SPAApiClient
        assert callable(SPAApiClient)

    def test_api_auth_importable_from_package(self):
        from spa_core.api import APIAuth
        assert callable(APIAuth)

    def test_get_auth_importable_from_package(self):
        from spa_core.api import get_auth
        assert callable(get_auth)


# ── API_REFERENCE.md content ──────────────────────────────────────────────────

class TestAPIReferenceDocs:
    def test_api_reference_file_exists(self):
        assert _API_REF.exists(), f"Missing: {_API_REF}"

    def test_api_reference_has_health_endpoint(self):
        content = _API_REF.read_text(encoding="utf-8")
        assert "/health" in content

    def test_api_reference_has_v1_status(self):
        content = _API_REF.read_text(encoding="utf-8")
        assert "/api/v1/status" in content

    def test_api_reference_has_v1_golive(self):
        content = _API_REF.read_text(encoding="utf-8")
        assert "/api/v1/golive" in content

    def test_api_reference_has_v1_adapters(self):
        content = _API_REF.read_text(encoding="utf-8")
        assert "/api/v1/adapters" in content

    def test_api_reference_has_v1_evidence(self):
        content = _API_REF.read_text(encoding="utf-8")
        assert "/api/v1/evidence" in content

    def test_api_reference_has_authentication_section(self):
        content = _API_REF.read_text(encoding="utf-8")
        assert "Authentication" in content
