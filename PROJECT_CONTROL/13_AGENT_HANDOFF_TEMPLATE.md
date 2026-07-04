# 13 — AGENT HANDOFF TEMPLATE

When handing work between Claude Code CLI and Claude Dispatch (or ending a session), fill this:

- **Branch / state:** working tree branch + drift vs origin/main (fetch to confirm).
- **What changed (files):** absolute paths pushed to `main` (via push_to_github_batch commits).
- **Verification done:** tests run + result; if deploy-related, the LIVE freshness check result.
- **Not done / blocked:** UNKNOWNs + owner-gated items.
- **Live surfaces checked:** earn-defi.com freshness, api.earn-defi.com health, academy if touched.
- **Next step:** one concrete action.

Both actors read `00_START_HERE` + `01_MASTER_RULES` first. Neither bypasses RiskPolicy / execution boundary / secrets policy. Prior handoff notes: `HANDOFF_PARALLEL_CC.md`.
