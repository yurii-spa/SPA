#!/usr/bin/env python3
"""findings_to_cards.py — CLI-шим моста «находка → карточка» (ADR-066 Фаза 3).
Логика — spa_core/monitoring/findings_bridge.py (тестируемый модуль)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from spa_core.monitoring.findings_bridge import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["--run"]))
