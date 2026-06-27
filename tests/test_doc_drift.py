"""
tests/test_doc_drift.py — re-export shim.

The DR/runbook doc-drift guard lives canonically at
``spa_core/tests/test_doc_drift.py`` (alongside the rest of the suite). This
shim re-exports its tests so the guard also runs under the top-level ``tests/``
path, and so ``pytest spa_core/tests/test_doc_drift.py tests/test_doc_drift.py``
(the documented invocation) resolves both paths. Single source of truth — no
divergent logic here.
"""
from spa_core.tests.test_doc_drift import (  # noqa: F401
    test_canonical_doc_does_not_revive_retired_agents,
    test_canonical_doc_has_correct_ports,
    test_canonical_doc_references_current_reality_scripts,
    test_canonical_doc_uses_correct_installer,
    test_canonical_dr_doc_exists,
    test_superseded_docs_point_at_canonical,
)
