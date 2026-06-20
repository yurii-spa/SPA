# tests/conftest.py — SPA-D003 (v1.8)
# sys.path setup for tests/ — merged from spa_core/tests/conftest.py (v1.7)
# plus path additions for scripts/ modules.
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent  # ~/Documents/SPA_Claude
_SCRIPTS = _ROOT / "scripts"
_SPA_CORE = _ROOT / "spa_core"

for _p in [str(_ROOT), str(_SCRIPTS), str(_SPA_CORE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
