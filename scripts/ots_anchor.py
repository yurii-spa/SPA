#!/usr/bin/env python3
"""
scripts/ots_anchor.py — daily external-anchoring runner (ADR-YL-010).

Usage:
  python3 scripts/ots_anchor.py stamp     # stamp the CURRENT chain head (idempotent per head)
  python3 scripts/ots_anchor.py upgrade   # promote pending .ots proofs to Bitcoin-confirmed
  python3 scripts/ots_anchor.py both       # stamp then upgrade (the daily agent default)

Wires into the existing daily head-checkpoint (see docs/PROOF_CHAIN_SPEC.md / ADR-YL-010 deploy
checklist). Reads a hash, writes proof files under proofs/ots/ — NO keys, NO fund movement. If the
external `ots` client is absent the run still records the head digest append-only (status
client_unavailable) and exits 0, so it never blocks the pipeline.
"""
# LLM_FORBIDDEN
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spa_core.audit import ots_anchor


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "both"
    out = {}
    if cmd in ("stamp", "both"):
        out["stamp"] = ots_anchor.stamp_latest_head()
    if cmd in ("upgrade", "both"):
        out["upgrade"] = ots_anchor.upgrade_pending()
    if cmd not in ("stamp", "upgrade", "both"):
        print(__doc__)
        return 2
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
