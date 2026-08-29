#!/usr/bin/env bash
set -e
cd ~/Documents/SPA_Claude

# Advisory pre-flight: warn (never block) if another pytest is already running
# in THIS tree — that class of collision has corrupted data/ before (cycle
# #352). Does not fail the script — `run_tests.sh` may be invoked routinely,
# and only the collision case is a real hazard; the check itself decides that.
python3 scripts/check_concurrent_pytest.py --cwd "$(pwd)" || true

python3 -m pytest tests/ -v --tb=short "$@"
