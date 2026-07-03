# SPA Verifier Release Manifest

**Purpose.** Pin an *authentic* copy of the standalone proof verifier so a skeptical
reviewer can confirm the script they run is byte-for-byte the one SPA published — before
they trust a single verdict it prints. "Don't trust us, check us" only works if you can
also check the *checker*.

The verifier is `scripts/verify_spa.py`: a zero-dependency, no-network, no-`spa_core`
Python file that re-derives every published hash following only the public
[`docs/PROOF_CHAIN_SPEC.md`](./PROOF_CHAIN_SPEC.md) recipe. See [`/verify`](https://earn-defi.com/verify)
for the reviewer-facing walkthrough.

---

## Current release

| Field | Value |
|---|---|
| **Version tag** | `verifier-v1.1` |
| **File** | `scripts/verify_spa.py` |
| **SHA-256** | `bbc4853a33b0e92c52dd8d408d6572f01b5184989ce291a00b2268a6acd67cbb` |
| **Size** | 94634 bytes · 1675 lines |
| **Spec version** | PROOF_CHAIN_SPEC `1.0` |
| **Scope** | decision chain (A) · exit-NAV proofs (B) · anchors (C) · equity track (D) · tournament ranking chain (E) · RWA-backstop NAV proof (F) · sleeve forward-series proofs (G) |

### Verify the verifier (one command)

On macOS / Linux, after downloading `verify_spa.py`:

```bash
shasum -a 256 verify_spa.py
# must print:
# bbc4853a33b0e92c52dd8d408d6572f01b5184989ce291a00b2268a6acd67cbb  verify_spa.py
```

or with the GNU coreutils tool:

```bash
sha256sum verify_spa.py
# bbc4853a33b0e92c52dd8d408d6572f01b5184989ce291a00b2268a6acd67cbb  verify_spa.py
```

If the digest does not match this manifest **byte-for-byte**, you do not have the
authentic verifier — discard it and re-download from the pinned tag below.

### Then run it

If you have a checkout of the public `data/` dir:

```bash
python3 verify_spa.py data/
# exit 0 = every published hash (surfaces A–G) reproduces; exit 1 = any mismatch.
```

Or pull the COMPLETE public chains straight from the live API (no checkout needed) and verify those —
the full-chain download endpoints serve every byte uncapped:

```bash
mkdir -p data/rates_desk/paper data/tournament data/rwa_backstop
B=https://api.earn-defi.com/api/rates-desk/full-chain
curl -s $B/decision_log > data/rates_desk/decision_log.jsonl
curl -s $B/exit_nav     > data/rates_desk/exit_nav.json
curl -s $B/anchors      > data/rates_desk/anchors.jsonl
curl -s $B/equity_track > data/rates_desk/equity_track.jsonl
curl -s $B/tournament   > data/tournament/decision_log.jsonl
curl -s $B/nav_proof    > data/rwa_backstop/nav_proof.jsonl
curl -s $B/sleeve       > data/rates_desk/paper/rates_desk_fixed_carry_series_proof.jsonl
python3 verify_spa.py data/        # exit 0 = the live API's published heads reproduce end-to-end
```

`GET /api/rates-desk/full-chain` returns the index of every downloadable surface.

---

## What this release pins (and what it does NOT)

- **A tag + a SHA-256 are owner-independent integrity:** anyone can recompute the digest
  on their own machine and compare it to this manifest. No trust in SPA is required for the
  digest comparison itself — that is the whole point.
- **A SHA-256 proves identity, not provenance.** It proves *"this is the file the manifest
  describes."* It does **not**, by itself, cryptographically prove *"SPA's owner authored
  this manifest."* That stronger guarantee needs a **signature**.

### Owner actions (flagged — not done here)

These are intentionally **owner-gated** and are NOT performed by this manifest:

1. **`git tag verifier-v1.1`** over the commit that contains this exact
   `scripts/verify_spa.py`, then push the tag. A pushed git tag gives reviewers an
   immutable, fetchable reference point (`git fetch --tags` → `git show verifier-v1.1`).
2. **GPG-sign** the tag (`git tag -s verifier-v1.1`) and/or publish a detached
   signature of the SHA-256 with the project's published GPG key. *Only this* upgrades the
   digest from "identity" to "authenticated provenance." It requires the owner's private
   key and is therefore out of scope for an automated change.

Until the owner signs, the honest claim is precisely: *this manifest pins an
owner-independent SHA-256 + version label; a reviewer can confirm file identity against it
today; cryptographic provenance (a signed tag) is the owner's next step.*

---

## Re-pinning on a verifier change

If `scripts/verify_spa.py` ever changes, this is **not** automatic — bump the version,
recompute, and record it here:

```bash
shasum -a 256 scripts/verify_spa.py     # new digest
wc -c -l scripts/verify_spa.py          # new size / line count
```

Then add a row to the changelog below, update **Current release**, and (owner) cut a new
`verifier-vN.M` tag. A new digest with the **same** version tag is a contradiction — every
distinct verifier byte-image gets its own version.

| Version | SHA-256 | Date | Note |
|---|---|---|---|
| `verifier-v1.1` | `bbc4853a33b0e92c52dd8d408d6572f01b5184989ce291a00b2268a6acd67cbb` | 2026-06-28 | Pinned release (68526 bytes · 1207 lines). Verifies surfaces A–G — decision chain + exit-NAV + anchors + equity track + tournament ranking chain + RWA-backstop NAV proof + sleeve forward-series proofs — per PROOF_CHAIN_SPEC v1.0. Reproducible end-to-end from the live `/api/rates-desk/full-chain/*` download endpoints. |

---

*Referenced from `/verify`, `docs/DD_PACK.md`, and `/track-record`. Recipe:
`docs/PROOF_CHAIN_SPEC.md`. stdlib-only · deterministic · fail-CLOSED.*

---

## Changelog

- **verifier-v1.1** (2026-07-03) — re-pin after the verifier gained surface **[I]** external
  timestamp anchoring (OpenTimestamps/Bitcoin) + the earlier surface additions; the v1.0 pin
  (`0f8c270c8c1f0c59…`) no longer matched the shipped `scripts/verify_spa.py`. New SHA-256 `bbc4853a33b0e92c…`.
  The v1.0 tag was never pushed; v1.1 is the first real tag.
- **verifier-v1.0** (initial) — first published manifest (tag never pushed; superseded by v1.1).
